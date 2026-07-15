#!/usr/bin/env python3
"""Build cna.parquet (GISTIC2 thresholded copy-number, -2..+2) for the TCGA ladder cohorts,
from cBioPortal's PanCancer Atlas `data_cna.txt`.

Why cBioPortal (not GDC): the episode path (executor + prompt + OS cohort) expects GISTIC2
*thresholded* calls where 0 = neutral, ± = amp/del (coverage mask `cna != 0`). cBioPortal's
`data_cna.txt` is exactly that — one clean genes × samples matrix per study.

Output: data/tcga/<cohort>/cna.parquet (samples × genes, int; index = patient barcode
TCGA-XX-XXXX to match expression.parquet). load_tcga() picks it up automatically; episode.py
anonymizes the gene columns via the shared gene_map. No integration code needed.

Usage:
    # auto-download each study tarball from the cBioPortal datahub, extract data_cna.txt, build:
    python scripts/download/download_cbioportal_cna.py --cohorts BRCA LIHC LUAD OV

    # OR if you already grabbed data_cna.txt from the cBioPortal web UI (Download tab, small):
    python scripts/download/download_cbioportal_cna.py --cohorts OV --from-dir ~/Downloads
    #   expects <dir>/<COHORT>_data_cna.txt  (or <study>/data_cna.txt)
"""
from __future__ import annotations

import argparse
import io
import sys
from pathlib import Path

import pandas as pd
import requests
import urllib3

# Corp network does SSL interception → we request with verify=False (like the other download
# scripts). Silence the resulting per-request warning; integrity is checked on the data itself.
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

# ladder cohort -> cBioPortal PanCancer Atlas study id
STUDY = {
    "BRCA": "brca_tcga_pan_can_atlas_2018",
    "LIHC": "lihc_tcga_pan_can_atlas_2018",
    "LUAD": "luad_tcga_pan_can_atlas_2018",
    "OV":   "ov_tcga_pan_can_atlas_2018",
    "UCEC": "ucec_tcga_pan_can_atlas_2018",
    "PRAD": "prad_tcga_pan_can_atlas_2018",
    "LUSC": "lusc_tcga_pan_can_atlas_2018",
}
# cBioPortal datahub lives on GitHub LFS; the media.* host resolves the real file content
# (the plain raw.githubusercontent host returns only the LFS pointer). ~30-40 MB per cohort —
# just data_cna.txt, no giant study tarball. (The old S3 datahub tarball URL now 403s.)
DATAHUB_LFS = "https://media.githubusercontent.com/media/cBioPortal/datahub/master/public/{study}/data_cna.txt"


def fetch_data_cna_text(cohort: str, from_dir: Path | None) -> str:
    """Return the raw text of the cohort's data_cna.txt, from a local file if given
    (<COHORT>_data_cna.txt or <study>/data_cna.txt) else the datahub GitHub-LFS file."""
    study = STUDY[cohort]
    if from_dir:
        for cand in (from_dir / f"{cohort}_data_cna.txt", from_dir / study / "data_cna.txt",
                     from_dir / "data_cna.txt"):
            if cand.exists():
                print(f"  [{cohort}] using local {cand}")
                return cand.read_text()
        raise FileNotFoundError(f"no data_cna.txt for {cohort} under {from_dir}")

    url = DATAHUB_LFS.format(study=study)
    print(f"  [{cohort}] downloading {url} ...")
    # Retry on dropped connections / IncompleteRead — the big files (BRCA ~60MB) are exposed to
    # flaky networks. Stream + read so a partial transfer raises here and we retry the whole GET.
    import time
    last = None
    for attempt in range(6):
        try:
            r = requests.get(url, timeout=600, verify=False, stream=True)
            r.raise_for_status()
            txt = r.content.decode()          # forces a full read; IncompleteRead raises here
            if txt.startswith("version https://git-lfs"):
                raise RuntimeError("got an LFS pointer, not content — need the media.githubusercontent.com host")
            return txt
        except Exception as e:
            last = e
            if attempt < 5:
                wait = 2 ** attempt
                print(f"  [{cohort}] retry {attempt+1}/6 after {type(e).__name__} — waiting {wait}s")
                time.sleep(wait)
    raise last


def build_cna_parquet(cohort: str, text: str, out_dir: Path, force: bool) -> None:
    cache = out_dir / "cna.parquet"
    if cache.exists() and not force:
        print(f"  [{cohort}] SKIP — cna.parquet exists ({cache.stat().st_size / 1e6:.0f} MB)")
        return

    df = pd.read_csv(io.StringIO(text), sep="\t")
    df = df.drop(columns=[c for c in ("Entrez_Gene_Id",) if c in df.columns])
    gene_col = "Hugo_Symbol" if "Hugo_Symbol" in df.columns else df.columns[0]
    df = df.dropna(subset=[gene_col])
    df = df[~df[gene_col].duplicated(keep="first")].set_index(gene_col)

    cna = df.T                                   # samples × genes (sample barcodes on the index)
    # cBioPortal samples are TCGA-XX-XXXX-01; expression is indexed by patient TCGA-XX-XXXX
    cna.index = [str(s)[:12] for s in cna.index]
    cna = cna[~cna.index.duplicated(keep="first")]   # one sample per patient
    cna.index.name = "sample_id"
    cna = cna.apply(pd.to_numeric, errors="coerce").round().astype("Int8")

    out_dir.mkdir(parents=True, exist_ok=True)
    cna.to_parquet(cache)
    nz = int((cna.fillna(0) != 0).to_numpy().sum())
    print(f"  [{cohort}] built cna.parquet {cna.shape} — {nz} non-neutral calls → {cache}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cohorts", nargs="+", default=list(STUDY), help="ladder cohorts (BRCA LIHC LUAD OV)")
    ap.add_argument("--data-dir", default="data/tcga")
    ap.add_argument("--from-dir", default=None, help="use a locally-downloaded data_cna.txt instead of the datahub")
    ap.add_argument("--force", action="store_true", help="rebuild even if cna.parquet exists")
    a = ap.parse_args()
    from_dir = Path(a.from_dir).expanduser() if a.from_dir else None

    for cohort in [c.upper() for c in a.cohorts]:
        if cohort not in STUDY:
            print(f"[{cohort}] SKIP — no cBioPortal study mapped", file=sys.stderr); continue
        try:
            text = fetch_data_cna_text(cohort, from_dir)
            build_cna_parquet(cohort, text, Path(a.data_dir) / cohort.lower(), a.force)
        except Exception as e:
            print(f"[{cohort}] ERROR: {e}", file=sys.stderr)
    print("\nDone. Verify one, then re-run the ladder so episodes include the CNA modality.")


if __name__ == "__main__":
    main()
