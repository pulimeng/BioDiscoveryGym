"""
Download gnomAD gene constraint metrics.

Source: gnomAD v2.1.1 (wider adoption) and v4.1 (latest).
We use v2.1.1 as the primary — it is the version most commonly cited
in published papers (including the IRS4 paper) and has the most
validated pLI / LOEUF scores.

Key columns used downstream:
  gene          — HGNC symbol
  pLI           — P(loss-of-function intolerant); >0.9 = essential, <0.1 = dispensable
  oe_lof_upper  — LOEUF; <0.35 (v2) or <0.6 (v4) = constrained
  obs_lof       — observed LoF variants in healthy population
  exp_lof       — expected LoF variants

Output:
  data/gnomad/gnomad.v2.1.1.lof_metrics.by_gene.tsv   (~10 MB uncompressed)
  data/gnomad/gnomad.v4.1.constraint_metrics.tsv       (~15 MB)

Usage:
    python scripts/download_gnomad.py
    python scripts/download_gnomad.py --version v4
"""

import argparse
import gzip
import shutil
from pathlib import Path

import requests
import urllib3
from tqdm import tqdm

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

OUT_DIR = Path("data/gnomad")

SOURCES = {
    "v2": {
        "url": "https://storage.googleapis.com/gcp-public-data--gnomad/release/2.1.1/constraint/gnomad.v2.1.1.lof_metrics.by_gene.txt.bgz",
        "out": "gnomad.v2.1.1.lof_metrics.by_gene.tsv",
        "compressed": True,
    },
    "v4": {
        "url": "https://storage.googleapis.com/gcp-public-data--gnomad/release/4.1/constraint/gnomad.v4.1.constraint_metrics.tsv",
        "out": "gnomad.v4.1.constraint_metrics.tsv",
        "compressed": False,
    },
}


def download(url: str, dest: Path, compressed: bool) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and dest.stat().st_size > 0:
        print(f"  [skip] {dest.name} already exists")
        return

    tmp = dest.with_suffix(dest.suffix + ".tmp")
    print(f"  Downloading {dest.name} ...")
    try:
        with requests.get(url, stream=True, timeout=300, verify=False) as r:
            r.raise_for_status()
            total = int(r.headers.get("content-length", 0))
            with open(tmp, "wb") as f, tqdm(total=total, unit="B", unit_scale=True) as bar:
                for chunk in r.iter_content(1 << 20):
                    f.write(chunk)
                    bar.update(len(chunk))

        if compressed:
            print(f"  Decompressing → {dest.name} ...")
            with gzip.open(tmp, "rb") as f_in, open(dest, "wb") as f_out:
                shutil.copyfileobj(f_in, f_out)
            tmp.unlink()
        else:
            tmp.rename(dest)

        print(f"  Done: {dest} ({dest.stat().st_size / 1e6:.1f} MB)")
    except Exception:
        if tmp.exists():
            tmp.unlink()
        raise


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", choices=["v2", "v4", "both"], default="v2",
                        help="Which gnomAD constraint version to download (default: v2)")
    parser.add_argument("--out", default=str(OUT_DIR))
    args = parser.parse_args()

    out_dir = Path(args.out)
    versions = ["v2", "v4"] if args.version == "both" else [args.version]

    for v in versions:
        src = SOURCES[v]
        print(f"\n=== gnomAD {v} constraint metrics ===")
        download(src["url"], out_dir / src["out"], src["compressed"])

    print("\nDone.")
    print(f"Key columns: gene, pLI (>0.9=essential), oe_lof_upper/LOEUF (<0.35=constrained), obs_lof, exp_lof")


if __name__ == "__main__":
    main()
