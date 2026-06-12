"""
Process TARGET (Therapeutically Applicable Research to Generate Effective
Treatments) pediatric pan-cancer RNA-seq into benchmark format.

This is a counts-only external cohort used for validation / analysis. Unlike
SGH-OS (process_os_jia2022.py) there is no survival, mutation, CNA, or
methylation — only a raw count matrix plus per-sample class labels.

Inputs  (data/external/TARGET/):
  TargetRawCountMatrix_unfiltered.txt    — raw counts, genes × samples (tab-sep,
                                           first column 'gene_name' = HUGO symbol)
  TARGET_All_labels_v4.txt               — columns: sample_id, class_label
                                           (disease + molecular subtype)

Outputs (data/external/TARGET/):
  expression.parquet     — samples × genes, log2(CPM+1), float32
                           (filtered to TCGA protein-coding gene reference,
                           matching process_os_jia2022.py for comparability)
  TARGET_labels.tsv       — case_id, class_label (raw subtype), cancer_type (coarse)

Normalization and gene-filtering choices mirror process_os_jia2022.py so that
TARGET expression is directly comparable to the other external/TCGA cohorts.

Sample coverage:
  1560 samples in count matrix; 1555 carry a class label. The 5 unlabeled
  samples (the '_hiseq'-suffixed ones) are dropped on intersection.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

DATA_DIR     = Path("data/external/TARGET")
COUNTS_PATH  = DATA_DIR / "TargetRawCountMatrix_unfiltered.txt"
LABELS_PATH  = DATA_DIR / "TARGET_All_labels_v4.txt"
TCGA_REF     = Path("data/tcga/lihc/expression.parquet")

# Coarse cancer_type derived from the fine-grained class_label. Order matters:
# the first matching rule wins, so the ALL_* prefixes precede the bare "ALL".
# Anything unmatched falls back to the raw label (surfaced as a warning).
def _coarse_cancer_type(label: str) -> str:
    lab = label.strip()
    if lab.startswith("AML"):
        return "AML"            # acute myeloid leukemia (all fusion subtypes)
    if lab.startswith("BALL"):
        return "B-ALL"          # B-lineage acute lymphoblastic leukemia
    if lab.startswith("TALL"):
        return "T-ALL"          # T-lineage acute lymphoblastic leukemia
    if lab.startswith("ALL"):
        return "ALL"            # ALL_Target — lineage unspecified
    direct = {
        "NBL":  "Neuroblastoma",
        "WT":   "Wilms tumor",
        "OS":   "Osteosarcoma",
        "RT":   "Rhabdoid tumor",
        "CCSK": "Clear cell sarcoma of kidney",
    }
    return direct.get(lab, lab)


def load_labels() -> pd.DataFrame:
    print("Loading labels...")
    labels = pd.read_csv(LABELS_PATH, sep="\t")
    labels["sample_id"]   = labels["sample_id"].astype(str).str.strip()
    labels["class_label"] = labels["class_label"].astype(str).str.strip()
    labels["cancer_type"] = labels["class_label"].map(_coarse_cancer_type)

    unmatched = labels.loc[labels["cancer_type"] == labels["class_label"], "class_label"]
    unmatched = sorted(set(unmatched))
    if unmatched:
        print(f"  Warning: {len(unmatched)} label(s) fell through to raw value: {unmatched}")

    print(f"  {len(labels)} labeled samples, {labels['cancer_type'].nunique()} coarse cancer types")
    return labels.set_index("sample_id")


def build_expression(labeled_samples: list[str], gene_filter: bool) -> pd.DataFrame:
    print("Loading count matrix (this is ~246 MB; may take a moment)...")
    counts = pd.read_csv(COUNTS_PATH, sep="\t", index_col=0)
    counts.columns = counts.columns.astype(str).str.strip()
    print(f"  Raw counts: {counts.shape[1]} samples × {counts.shape[0]} genes")

    # Keep only samples that carry a class label (drops the 5 unlabeled ones)
    keep = [c for c in counts.columns if c in set(labeled_samples)]
    counts = counts[keep]
    print(f"  After intersecting with labels: {counts.shape[1]} samples retained")

    # CPM → log2(CPM+1), samples × genes (matches process_os_jia2022.py)
    cpm  = counts.div(counts.sum(axis=0), axis=1) * 1e6
    expr = np.log2(cpm + 1).astype("float32").T
    expr.index.name = "case_id"

    if gene_filter and TCGA_REF.exists():
        import pyarrow.parquet as pq
        tcga_genes = pq.read_schema(TCGA_REF).names
        keep_genes = [g for g in tcga_genes if g in expr.columns]
        expr = expr[keep_genes]
        print(f"  Filtered to {len(keep_genes)} protein-coding genes (TCGA reference)")
    elif gene_filter:
        print(f"  Warning: TCGA reference {TCGA_REF} not found — keeping all genes.")

    print(f"  Expression matrix: {expr.shape[0]} samples × {expr.shape[1]} genes")
    return expr


def main():
    parser = argparse.ArgumentParser(description="Process TARGET pediatric pan-cancer RNA-seq.")
    parser.add_argument("--no-gene-filter", action="store_true",
                        help="Keep all genes instead of filtering to the TCGA "
                             "protein-coding reference set.")
    args = parser.parse_args()

    print(f"\n{'='*55}")
    print(f"  TARGET — pediatric pan-cancer RNA-seq processing")
    print(f"{'='*55}\n")

    labels = load_labels()
    print()
    expr = build_expression(labels.index.tolist(), gene_filter=not args.no_gene_filter)

    # Align labels to the expression cohort
    clin = labels.reindex(expr.index)
    clin.index.name = "case_id"

    print("\nCohort composition (coarse cancer_type):")
    for ctype, n in clin["cancer_type"].value_counts().items():
        print(f"    {ctype}: {n}")

    expr_path = DATA_DIR / "expression.parquet"
    clin_path = DATA_DIR / "TARGET_labels.tsv"
    expr.to_parquet(expr_path)
    clin.to_csv(clin_path, sep="\t")

    print(f"\nSaved:")
    print(f"  {expr_path}  {expr_path.stat().st_size // 1024} KB")
    print(f"  {clin_path}  {clin_path.stat().st_size // 1024} KB")
    print()


if __name__ == "__main__":
    main()
