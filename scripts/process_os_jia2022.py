"""
Process SGH-OS (Jia et al. 2022, Nat Comms) data into benchmark format.

Inputs  (data/external/os_jia2022/):
  sgh-count.csv                — raw counts, genes × samples
  clinical_sgh.xlsx            — per-sample metadata + subtype labels
  Supplementary Data 2.xlsx    — per-sample somatic mutations (41 genes)

Outputs (data/external/os_jia2022/):
  expression.parquet           — samples × genes, log2(CPM+1), float32
  mutations.parquet            — samples × genes, binary float32
  OS_clinical.tsv              — case_id, vital_status, days_to_death, subtype, ...

Subtype mapping (iCluster → paper label):
  1 → S-IA  (Immune Activated,        n=25)
  2 → S-IS  (Immune Suppressed,       n=22)
  3 → S-HRD (HR Deficiency Dominant,  n=23)
  4 → S-MD  (MYC Driven,              n=21)
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

DATA_DIR = Path("data/external/os_jia2022")

ICLUSTER_MAP = {1: "S-IA", 2: "S-IS", 3: "S-HRD", 4: "S-MD"}

SOMATIC_GENES = [
    "TP53", "ATRX", "POLD1", "ARID1A", "MSH2", "RAD52", "BRCA2", "MSH6",
    "POLE", "RAD50", "CDC27", "DMD", "HYDIN", "MST1", "PKHD1", "GNAS",
    "SMG1", "MTOR", "RIOK1", "ERBB4", "FAT3", "NOTCH2", "CDH1", "EGFR",
    "MET", "FOXA2", "NCOA3", "PRDM16", "FBXO11", "MYC", "NCOA6", "RB1",
    "CEP350", "MKI67", "CDK12", "BRD9", "H3F3A", "EP400", "SUPT16H",
    "KMT2C", "KMT2D",
]


def build_expression(clinical: pd.DataFrame) -> pd.DataFrame:
    print("Loading count matrix...")
    counts = pd.read_csv(DATA_DIR / "sgh-count.csv", index_col=0)
    print(f"  Raw counts: {counts.shape[1]} samples × {counts.shape[0]} genes")

    # Map raw RNA-seq IDs → SGH-OS-XXX using clinical table
    rna_to_sgh = dict(zip(
        clinical["RNAseq编号"].astype(str),
        clinical["SampleID"].astype(str),
    ))
    counts = counts.rename(columns=rna_to_sgh)

    # Keep only samples with clinical data
    keep = [c for c in counts.columns if c in rna_to_sgh.values()]
    counts = counts[keep]
    print(f"  After ID mapping: {counts.shape[1]} samples retained")

    # Counts → log2(CPM+1)
    # CPM: divide each column by its sum, multiply by 1e6
    cpm = counts.div(counts.sum(axis=0), axis=1) * 1e6
    expr = np.log2(cpm + 1).astype("float32")

    # Transpose to samples × genes
    expr = expr.T
    expr.index.name = "case_id"

    # Filter to protein-coding genes using TCGA reference gene list
    tcga_ref = Path("data/tcga/lihc/expression.parquet")
    if tcga_ref.exists():
        tcga_genes = pd.read_parquet(tcga_ref, columns=[]).columns.tolist()
        # Use parquet metadata trick to get column names without loading data
        import pyarrow.parquet as pq
        tcga_genes = pq.read_schema(tcga_ref).names
        keep_genes = [g for g in tcga_genes if g in expr.columns]
        expr = expr[keep_genes]
        print(f"  Filtered to {len(keep_genes)} protein-coding genes (TCGA reference)")

    print(f"  Expression matrix: {expr.shape[0]} samples × {expr.shape[1]} genes")
    print(f"  Value range: [{expr.values.min():.2f}, {expr.values.max():.2f}]")
    return expr


def build_mutations(clinical: pd.DataFrame) -> pd.DataFrame:
    print("Loading mutation data...")
    mut_raw = pd.read_excel(DATA_DIR / "Supplementary Data 2.xlsx", header=1)

    keep_cols = ["SampleID"] + [g for g in SOMATIC_GENES if g in mut_raw.columns]
    mut = mut_raw[keep_cols].copy()

    # Binary: any non-NaN value = 1 (mutated), NaN = 0
    for g in SOMATIC_GENES:
        if g in mut.columns:
            mut[g] = mut[g].notna().astype("float32")

    # Deduplicate multi-sample patients: OR logic (max per sample)
    mut = mut.groupby("SampleID")[SOMATIC_GENES].max().reset_index()

    # Keep only samples with clinical data
    valid = set(clinical["SampleID"].astype(str))
    mut = mut[mut["SampleID"].isin(valid)].set_index("SampleID")
    mut.index.name = "case_id"

    print(f"  Mutation matrix: {mut.shape[0]} samples × {mut.shape[1]} genes")
    print(f"  Mutation rate per gene (top 10):")
    top = mut.mean().sort_values(ascending=False).head(10)
    for gene, rate in top.items():
        print(f"    {gene}: {rate:.1%}")
    return mut.astype("float32")


def build_clinical(clinical: pd.DataFrame, expr_samples: list[str]) -> pd.DataFrame:
    print("Building clinical table...")
    df = clinical.copy()

    df["case_id"]       = df["SampleID"].astype(str)
    df["vital_status"]  = df["Status"].map({0: "Alive", 1: "Dead"})
    df["days_to_death"] = df["OS"].where(df["Status"] == 1, other=np.nan)
    df["days_to_last_follow_up"] = df["OS"].where(df["Status"] == 0, other=np.nan)
    df["subtype"]       = df["iCluster-分组"].map(ICLUSTER_MAP)
    df["age_at_diagnosis"] = df["Age"]
    df["gender"]        = df["Gender"].str.lower()
    df["tumor_stage"]   = df["Ennking.Stage"]
    df["metastasis"]    = df["Metastasis"]
    df["pathology"]     = df["Pathology"]
    df["tmb"]           = df["TMB"]
    df["hrd_score"]     = df["HRD"]
    df["mrna_cluster"]  = df["mRNA.Cluster"]

    keep = [
        "case_id", "vital_status", "days_to_death", "days_to_last_follow_up",
        "subtype", "age_at_diagnosis", "gender", "tumor_stage",
        "metastasis", "pathology", "tmb", "hrd_score", "mrna_cluster",
    ]
    df = df[keep].set_index("case_id")

    # Keep only samples with expression data
    df = df.loc[df.index.isin(expr_samples)]

    print(f"  Clinical table: {len(df)} samples")
    print(f"  Subtype distribution:")
    for s, n in df["subtype"].value_counts().sort_index().items():
        print(f"    {s}: {n}")
    print(f"  Vital status: {df['vital_status'].value_counts().to_dict()}")
    return df


def main():
    print(f"\n{'='*55}")
    print(f"  SGH-OS (Jia 2022) — data processing")
    print(f"{'='*55}\n")

    print("Loading clinical file...")
    clinical = pd.read_excel(DATA_DIR / "clinical_sgh.xlsx")
    print(f"  {len(clinical)} samples, {len(clinical.columns)} columns")

    expr = build_expression(clinical)
    print()
    mut  = build_mutations(clinical)
    print()
    clin = build_clinical(clinical, expr.index.tolist())

    # Align all three to the same sample set
    shared = sorted(set(expr.index) & set(mut.index) & set(clin.index))
    expr = expr.loc[shared]
    mut  = mut.loc[shared]
    clin = clin.loc[shared]
    print(f"\nFinal aligned sample count: {len(shared)}")

    # Save
    expr_path = DATA_DIR / "expression.parquet"
    mut_path  = DATA_DIR / "mutations.parquet"
    clin_path = DATA_DIR / "OS_clinical.tsv"

    expr.to_parquet(expr_path)
    mut.to_parquet(mut_path)
    clin.to_csv(clin_path, sep="\t")

    print(f"\nSaved:")
    print(f"  {expr_path}  {expr_path.stat().st_size // 1024} KB")
    print(f"  {mut_path}   {mut_path.stat().st_size // 1024} KB")
    print(f"  {clin_path}  {clin_path.stat().st_size // 1024} KB")
    print()


if __name__ == "__main__":
    main()
