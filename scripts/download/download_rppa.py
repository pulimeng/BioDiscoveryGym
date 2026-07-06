"""
Download TCGA pan-cancer RPPA (Reverse Phase Protein Array) data from UCSC Xena.

Source: TCGA-RPPA-pancan-clean.xena.gz  (~258 proteins × 7754 pan-cancer samples)
  - Protein expression z-scores (RBN normalized)
  - Includes phosphosite measurements (AKT_pS473, mTOR_pS2448, etc.)

Per cohort, saves:
  data/tcga/{cohort}/rppa.parquet  (samples × proteins, filtered to cohort)

Protein name format:
  - Gene-level:     AKT, CTNNB1, TP53BP1
  - Phosphosites:   AKT_pS473, MTOR_pS2481
  - Legacy names:   X1433EPSILON (= YWHAE / 14-3-3-epsilon)

Usage:
    python scripts/download_rppa.py --cohorts LIHC BRCA
    python scripts/download_rppa.py  # all 5 default cohorts
"""

import argparse
import gzip
import io
from pathlib import Path

import pandas as pd
import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

XENA_URL = "https://pancanatlas.xenahubs.net/download/TCGA-RPPA-pancan-clean.xena.gz"
DEFAULT_COHORTS = ["BRCA", "PRAD", "UCEC", "LUAD", "LIHC"]


def fetch_rppa() -> pd.DataFrame:
    """Download and parse full pan-cancer RPPA matrix (proteins × samples)."""
    print(f"Downloading RPPA from Xena ...")
    r = requests.get(XENA_URL, verify=False, timeout=300)
    r.raise_for_status()
    df = pd.read_csv(io.BytesIO(gzip.decompress(r.content)), sep="\t", index_col=0)
    print(f"  {df.shape[0]} proteins × {df.shape[1]} samples")
    return df  # proteins × samples


def filter_cohort(rppa: pd.DataFrame, cohort_samples: set[str]) -> pd.DataFrame:
    """
    Select samples belonging to a cohort, transpose to samples × proteins.
    Matches on 12-char TCGA participant barcode (TCGA-XX-XXXX).
    """
    cols = [c for c in rppa.columns if c[:12] in cohort_samples]
    if not cols:
        return pd.DataFrame()
    sub = rppa[cols].T.copy()
    sub.index.name = "sample_id"
    sub.columns.name = None
    # Prefer primary tumor samples (-01) over normals (-11) before collapsing to 12-char barcode
    sub = sub.sort_index()  # -01 sorts before -11
    sub.index = sub.index.str[:12]
    sub = sub[~sub.index.duplicated(keep="first")]
    return sub


def process_cohort(
    cohort: str,
    rppa: pd.DataFrame,
    expr_index: pd.Index,
    out_dir: Path,
) -> None:
    cache = out_dir / "rppa.parquet"
    if cache.exists():
        print(f"  [skip] {cohort} — rppa.parquet already exists")
        return

    cohort_samples = set(expr_index.str[:12])
    sub = filter_cohort(rppa, cohort_samples)

    if sub.empty:
        print(f"  {cohort}: no RPPA samples found")
        return

    # Align index to expression samples (keep only intersection)
    sub = sub.reindex(cohort_samples.intersection(sub.index))
    sub = sub.dropna(how="all")

    print(f"  {cohort}: {sub.shape[0]} samples × {sub.shape[1]} proteins")
    sub.to_parquet(cache)
    print(f"  Saved → {cache}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cohorts", nargs="+", default=DEFAULT_COHORTS)
    parser.add_argument("--out", default="data/tcga")
    args = parser.parse_args()

    rppa = fetch_rppa()

    for cohort in args.cohorts:
        cohort = cohort.upper()
        out_dir = Path(args.out) / cohort.lower()
        out_dir.mkdir(parents=True, exist_ok=True)
        print(f"\n=== {cohort} ===")

        expr_path = out_dir / "expression.parquet"
        if not expr_path.exists():
            print(f"  SKIP — expression.parquet not found (run download_tcga.py first)")
            continue

        expr_index = pd.read_parquet(expr_path, columns=[]).index
        process_cohort(cohort, rppa, expr_index, out_dir)

    print("\nDone.")


if __name__ == "__main__":
    main()
