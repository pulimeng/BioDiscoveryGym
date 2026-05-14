"""
Build expression.parquet caches for TCGA cohorts.

Extracts per-sample TPM values from the GDC batch tarballs downloaded by
download_tcga.py and saves a samples × genes DataFrame to expression.parquet.

Must be run after download_tcga.py for each cohort.

Usage:
    python scripts/process_tcga.py                         # all target-discovery cohorts
    python scripts/process_tcga.py --cohorts COAD HNSC     # specific cohorts
    python scripts/process_tcga.py --cohorts all           # all known cohorts
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

TARGET_DISCOVERY_COHORTS = [
    "BRCA", "COAD", "HNSC", "KIRC", "LIHC", "LUAD", "LUSC", "OV", "PRAD", "SKCM",
]

ANOMALY_BENCHMARK_COHORTS = [
    "BRCA", "LUAD", "LUSC", "LIHC", "OV", "PRAD", "UCEC",
]

ALL_COHORTS = sorted(set(TARGET_DISCOVERY_COHORTS) | set(ANOMALY_BENCHMARK_COHORTS))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--cohorts",
        nargs="+",
        default=TARGET_DISCOVERY_COHORTS,
        help="Cohorts to process. Use 'all' for every known cohort.",
    )
    parser.add_argument("--data-dir", default="data/tcga")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Rebuild expression.parquet even if it already exists.",
    )
    args = parser.parse_args()

    cohorts = ALL_COHORTS if args.cohorts == ["all"] else [c.upper() for c in args.cohorts]

    from biodiscoverygym.utils.data_loader import DataLoader
    dl = DataLoader()

    print(f"Processing {len(cohorts)} cohorts: {cohorts}")
    print()

    for cohort in cohorts:
        tcga_dir = Path(args.data_dir) / cohort.lower()
        cache = tcga_dir / "expression.parquet"
        raw_dir = tcga_dir / "expression_raw"

        if not tcga_dir.exists():
            print(f"[{cohort}] SKIP — directory not found: {tcga_dir}")
            continue
        if not raw_dir.exists() or not any(raw_dir.glob("batch_*.tar.gz")):
            print(f"[{cohort}] SKIP — no raw downloads in {raw_dir}. Run download_tcga.py first.")
            continue
        if cache.exists() and not args.force:
            print(f"[{cohort}] SKIP — expression.parquet already exists ({cache.stat().st_size / 1e6:.0f} MB)")
            continue

        print(f"[{cohort}] Building expression.parquet ...")
        try:
            ds = dl.load_tcga(cohort, tcga_dir=str(tcga_dir), use_cache=not args.force)
            print(f"[{cohort}] Done: {ds['expression'].shape[0]} samples × {ds['expression'].shape[1]} genes")
        except Exception as e:
            print(f"[{cohort}] ERROR: {e}", file=sys.stderr)

    print("\nDone.")


if __name__ == "__main__":
    main()
