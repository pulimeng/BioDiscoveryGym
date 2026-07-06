"""
Download gene set and protein interaction databases for pathway enrichment.

Downloads:
  MSigDB GMT files (Broad Institute, v2023.2):
    - h.all       Hallmark gene sets (50 sets)
    - c2.cp.kegg  KEGG canonical pathways
    - c2.cp.reactome  Reactome canonical pathways
    - c5.go.bp    GO Biological Process
    - c5.go.mf    GO Molecular Function

  STRING DB (v12.0, human — 9606):
    - protein.links     all interactions with combined score
    - protein.info      ENSP → gene symbol mapping
    Filtered to combined_score >= 700 (high confidence) and saved as TSV.

Output layout:
  data/genesets/
    msigdb/
      h.all.v2023.2.Hs.symbols.gmt
      c2.cp.kegg.v2023.2.Hs.symbols.gmt
      c2.cp.reactome.v2023.2.Hs.symbols.gmt
      c5.go.bp.v2023.2.Hs.symbols.gmt
      c5.go.mf.v2023.2.Hs.symbols.gmt
    stringdb/
      protein.links.v12.0.txt.gz      (raw, full)
      protein.info.v12.0.txt.gz       (raw)
      human_ppi_high_conf.tsv         (gene1, gene2, score ≥ 700)

Usage:
    python scripts/download_genesets.py
    python scripts/download_genesets.py --no-string   # MSigDB only
    python scripts/download_genesets.py --no-msigdb   # STRING only
    python scripts/download_genesets.py --string-threshold 900
"""

import argparse
import gzip
import shutil
from pathlib import Path

import pandas as pd
import requests
import urllib3
from tqdm import tqdm

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

MSIGDB_VERSION = "2023.2"
MSIGDB_BASE = f"https://data.broadinstitute.org/gsea-msigdb/msigdb/release/{MSIGDB_VERSION}.Hs"

MSIGDB_FILES = {
    "h.all":          f"h.all.v{MSIGDB_VERSION}.Hs.symbols.gmt",
    "c2.cp.kegg":     f"c2.cp.kegg_medicus.v{MSIGDB_VERSION}.Hs.symbols.gmt",
    "c2.cp.reactome": f"c2.cp.reactome.v{MSIGDB_VERSION}.Hs.symbols.gmt",
    "c5.go.bp":       f"c5.go.bp.v{MSIGDB_VERSION}.Hs.symbols.gmt",
    "c5.go.mf":       f"c5.go.mf.v{MSIGDB_VERSION}.Hs.symbols.gmt",
}

STRING_VERSION = "12.0"
STRING_TAXON = "9606"  # human
STRING_BASE = "https://stringdb-downloads.org/download"
STRING_FILES = {
    "links": f"protein.links.v{STRING_VERSION}/{STRING_TAXON}.protein.links.v{STRING_VERSION}.txt.gz",
    "info":  f"protein.info.v{STRING_VERSION}/{STRING_TAXON}.protein.info.v{STRING_VERSION}.txt.gz",
}


# ---------------------------------------------------------------------------
# Shared download helper
# ---------------------------------------------------------------------------

def download_file(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and dest.stat().st_size > 0:
        print(f"  [skip] {dest.name}")
        return
    print(f"  Downloading {dest.name} ...")
    tmp = dest.with_suffix(dest.suffix + ".tmp")
    try:
        with requests.get(url, stream=True, timeout=300, verify=False) as r:
            r.raise_for_status()
            total = int(r.headers.get("content-length", 0))
            with open(tmp, "wb") as f, tqdm(total=total, unit="B", unit_scale=True, leave=False) as bar:
                for chunk in r.iter_content(1 << 20):
                    f.write(chunk)
                    bar.update(len(chunk))
        if tmp.stat().st_size == 0:
            tmp.unlink()
            raise RuntimeError(f"Empty response for {dest.name}")
        tmp.rename(dest)
    except Exception:
        if tmp.exists():
            tmp.unlink()
        raise


# ---------------------------------------------------------------------------
# MSigDB
# ---------------------------------------------------------------------------

def download_msigdb(out_dir: Path) -> None:
    print("\n=== MSigDB ===")
    msigdb_dir = out_dir / "msigdb"
    for key, fname in MSIGDB_FILES.items():
        url = f"{MSIGDB_BASE}/{fname}"
        dest = msigdb_dir / fname
        try:
            download_file(url, dest)
        except requests.HTTPError as e:
            print(f"  [warn] {key} failed ({e}) — skipping")
    print(f"  MSigDB done → {msigdb_dir}")


# ---------------------------------------------------------------------------
# STRING DB
# ---------------------------------------------------------------------------

def download_string(out_dir: Path, threshold: int = 700) -> None:
    print("\n=== STRING DB ===")
    string_dir = out_dir / "stringdb"

    links_gz = string_dir / f"{STRING_TAXON}.protein.links.v{STRING_VERSION}.txt.gz"
    info_gz  = string_dir / f"{STRING_TAXON}.protein.info.v{STRING_VERSION}.txt.gz"

    download_file(f"{STRING_BASE}/{STRING_FILES['links']}", links_gz)
    download_file(f"{STRING_BASE}/{STRING_FILES['info']}", info_gz)

    hc_path = string_dir / "human_ppi_high_conf.tsv"
    if hc_path.exists() and hc_path.stat().st_size > 0:
        print(f"  [skip] {hc_path.name}")
    else:
        print(f"  Building high-confidence PPI (score ≥ {threshold}) ...")
        _build_hc_ppi(links_gz, info_gz, hc_path, threshold)

    print(f"  STRING done → {string_dir}")


def _build_hc_ppi(links_gz: Path, info_gz: Path, out_tsv: Path, threshold: int) -> None:
    # Load ENSP → gene symbol map
    with gzip.open(info_gz, "rt") as f:
        info = pd.read_csv(f, sep="\t", usecols=[0, 1], header=0,
                           names=["protein_id", "gene_symbol"])
    id_to_gene = dict(zip(info["protein_id"], info["gene_symbol"]))

    # Stream links, filter by score, map to gene symbols
    rows = []
    with gzip.open(links_gz, "rt") as f:
        next(f)  # skip header
        for line in tqdm(f, desc="  Filtering links", unit=" lines", unit_scale=True):
            p1, p2, score = line.rstrip().split()
            if int(score) >= threshold:
                g1 = id_to_gene.get(p1)
                g2 = id_to_gene.get(p2)
                if g1 and g2:
                    rows.append((g1, g2, int(score)))

    df = pd.DataFrame(rows, columns=["gene1", "gene2", "combined_score"])
    df.to_csv(out_tsv, sep="\t", index=False)
    print(f"  Kept {len(df):,} interactions (threshold={threshold})")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="data/genesets")
    parser.add_argument("--no-msigdb", action="store_true")
    parser.add_argument("--no-string", action="store_true")
    parser.add_argument("--string-threshold", type=int, default=700,
                        help="Minimum STRING combined score to keep (0-1000, default 700)")
    args = parser.parse_args()

    out_dir = Path(args.out)

    if not args.no_msigdb:
        download_msigdb(out_dir)

    if not args.no_string:
        download_string(out_dir, threshold=args.string_threshold)

    print("\nDone.")


if __name__ == "__main__":
    main()
