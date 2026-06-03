"""
Process SGH-OS (Jia et al. 2022, Nat Comms) data into benchmark format.

Inputs  (data/external/os_jia2022/):
  sgh-count.csv                          — raw counts, genes × samples
  clinical_sgh.xlsx                      — per-sample metadata + subtype labels
                                           WES编号 = MAF Tumor_Sample_Barcode
                                           Oncoscan.CNV = GISTIC/array file stem
  OS_82+25s_keep.0.01_filterVAF_variants_maf_new.xlsx
                                         — full WES somatic MAF (107 samples: 82 SGH + 25 ext)
  BH190104_850k_Gistic/
    all_lesions.conf_90.txt              — binary CNA calls per GISTIC peak × sample
    amp_genes.conf_90.txt                — genes per amplification peak
    del_genes.conf_90.txt                — genes per deletion peak
  methylation/                           — per-sample Illumina 850K beta-value .txt files
  meth_sample_map.csv                    — columns: meth_file_stem, sample_id

Outputs (data/external/os_jia2022/):
  expression.parquet     — samples × genes, log2(CPM+1), float32
  mutations.parquet      — samples × genes, binary float32  (full WES, functional only)
  cna.parquet            — samples × genes, int8 CNA calls (+1=amp, -1=del, 0=neutral)
  methylation.parquet    — samples × CpGs (top 10,000 by std), beta, float32
  OS_clinical.tsv        — case_id, vital_status, days_to_death, subtype, ...

Sample coverage (out of 91 expression samples):
  mutations  : 77 samples with WES
  cna        : 47 samples with Oncoscan CNA array → GISTIC
  methylation: 91 samples (all)

Subtype mapping (iCluster → paper label):
  1 → S-IA  (Immune Activated,        n=25)
  2 → S-IS  (Immune Suppressed,       n=22)
  3 → S-HRD (HR Deficiency Dominant,  n=23)
  4 → S-MD  (MYC Driven,              n=21)
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

DATA_DIR  = Path("data/external/os_jia2022")
GISTIC_DIR = DATA_DIR / "BH190104_850k_Gistic"
MAF_PATH  = DATA_DIR / "OS_82+25s_keep.0.01_filterVAF_variants_maf_new.xlsx"

ICLUSTER_MAP = {1: "S-IA", 2: "S-IS", 3: "S-HRD", 4: "S-MD"}

# Functional variant classes to retain; Silent excluded
FUNCTIONAL_CLASSES = {
    "Missense_Mutation", "Nonsense_Mutation", "Frame_Shift_Del",
    "Frame_Shift_Ins", "In_Frame_Del", "In_Frame_Ins", "Splice_Site",
    "Nonstop_Mutation", "Inframe_Substitution", "Frameshift_Substitution",
}

# Excel auto-converts MARCH/SEPT gene names to date strings; map them back
EXCEL_DATE_FIX = {
    "2020-03-02 00:00:00": "MARCH2",
    "2020-09-01 00:00:00": "SEPT1",
    "2020-09-02 00:00:00": "SEPT2",
    "2020-09-10 00:00:00": "SEPT10",
}

import re as _re

# GISTIC artifact gene patterns to drop from CNA matrix
# Applied as: any gene matching any pattern is excluded
CNA_BLACKLIST_PATTERNS = [
    _re.compile(r"^DUX"),     # 4q35 DUX4 paralog cluster — subtelomeric noise
    _re.compile(r"^OR\d"),    # olfactory receptor family — repetitive-region false-calls
]


def _is_blacklisted(gene: str) -> bool:
    return any(p.match(gene) for p in CNA_BLACKLIST_PATTERNS)

# Known OS driver genes absent from GISTIC narrow peaks; borrow from nearest amp peak
# Key = cytoband of the GISTIC peak whose samples carry the amplicon
PEAK_GENE_ADDITIONS = {
    "8q24.13": ["MYC"],   # MYC at 8q24.21 — just outside the narrow peak boundary
    "12q15":   ["CDK4"],  # CDK4 at 12q14.1 — co-amplifies with MDM2 in the 12q13-15 amplicon
}


# ──────────────────────────────────────────────────────────────────────────────
# Expression
# ──────────────────────────────────────────────────────────────────────────────

def build_expression(clinical: pd.DataFrame) -> pd.DataFrame:
    print("Loading count matrix...")
    counts = pd.read_csv(DATA_DIR / "sgh-count.csv", index_col=0)
    print(f"  Raw counts: {counts.shape[1]} samples × {counts.shape[0]} genes")

    rna_to_sgh = dict(zip(
        clinical["RNAseq编号"].astype(str),
        clinical["SampleID"].astype(str),
    ))
    counts = counts.rename(columns=rna_to_sgh)
    keep = [c for c in counts.columns if c in rna_to_sgh.values()]
    counts = counts[keep]
    print(f"  After ID mapping: {counts.shape[1]} samples retained")

    cpm  = counts.div(counts.sum(axis=0), axis=1) * 1e6
    expr = np.log2(cpm + 1).astype("float32").T
    expr.index.name = "case_id"

    tcga_ref = Path("data/tcga/lihc/expression.parquet")
    if tcga_ref.exists():
        import pyarrow.parquet as pq
        tcga_genes = pq.read_schema(tcga_ref).names
        keep_genes = [g for g in tcga_genes if g in expr.columns]
        expr = expr[keep_genes]
        print(f"  Filtered to {len(keep_genes)} protein-coding genes (TCGA reference)")

    print(f"  Expression matrix: {expr.shape[0]} samples × {expr.shape[1]} genes")
    return expr


# ──────────────────────────────────────────────────────────────────────────────
# Mutations (full WES MAF → binary samples × genes)
# ──────────────────────────────────────────────────────────────────────────────

def build_mutations(clinical: pd.DataFrame, min_vaf: float = 0.05) -> pd.DataFrame:
    """
    Build a binary samples × genes mutation matrix from the full WES MAF.

    Sample barcode mapping uses clinical_sgh.xlsx WES编号 column.
    Functional variant classes only (Silent excluded).
    min_vaf: drop variants below this tumor VAF (default 0.05 — standard somatic filter).
    """
    print(f"Loading WES mutations (full MAF, min_vaf={min_vaf})...")
    wes_to_sgh = {
        str(wes): str(sgh)
        for wes, sgh in zip(clinical["WES编号"], clinical["SampleID"])
        if pd.notna(wes)
    }

    maf = pd.read_excel(
        MAF_PATH,
        usecols=["Tumor_Sample_Barcode", "Hugo_Symbol", "Variant_Classification", "Tumor_VAF"],
    )
    print(f"  Total MAF rows: {len(maf)}")

    maf = maf[maf["Variant_Classification"].isin(FUNCTIONAL_CLASSES)].copy()
    print(f"  After functional filter: {len(maf)} rows")

    maf["Tumor_VAF"] = pd.to_numeric(maf["Tumor_VAF"], errors="coerce")
    maf = maf[maf["Tumor_VAF"] >= min_vaf].copy()
    print(f"  After VAF ≥ {min_vaf} filter: {len(maf)} rows")

    maf["case_id"] = maf["Tumor_Sample_Barcode"].astype(str).map(wes_to_sgh)
    maf = maf.dropna(subset=["case_id"])
    print(f"  Samples mapped to cohort: {maf['case_id'].nunique()}")

    # Hugo_Symbol may contain Excel-converted date strings for MARCH/SEPT genes
    maf["Hugo_Symbol"] = maf["Hugo_Symbol"].astype(str).replace(EXCEL_DATE_FIX)

    maf["mutated"] = 1.0
    mut = (
        maf.pivot_table(
            index="case_id",
            columns="Hugo_Symbol",
            values="mutated",
            aggfunc="max",
            fill_value=0.0,
        )
        .astype("float32")
    )
    mut.columns.name = None
    mut.index.name = "case_id"

    # Rename any date-string columns that slipped through as column names
    date_cols_found = {c for c in mut.columns if str(c) in EXCEL_DATE_FIX}
    if date_cols_found:
        mut = mut.rename(columns={c: EXCEL_DATE_FIX[str(c)] for c in date_cols_found})
        print(f"  Fixed {len(date_cols_found)} Excel date column(s): {sorted(str(c) for c in date_cols_found)}")

    print(f"  Mutation matrix: {mut.shape[0]} samples × {mut.shape[1]} genes")
    print(f"  Mean mutations/sample: {mut.sum(axis=1).mean():.1f}")
    top = mut.mean().sort_values(ascending=False).head(10)
    print("  Top mutated genes:")
    for gene, rate in top.items():
        print(f"    {gene}: {rate:.1%}")
    return mut


# ──────────────────────────────────────────────────────────────────────────────
# CNA (GISTIC2 → gene-level +1/0/-1 samples × genes)
# ──────────────────────────────────────────────────────────────────────────────

def _parse_gistic_genes(path: Path) -> dict[str, list[str]]:
    """
    Parse amp_genes.conf_90.txt or del_genes.conf_90.txt.
    Returns {cytoband: [gene_symbol, ...]} — keyed by cytoband, not peak index.
    amp_genes and del_genes columns are sorted by q-value (significance order),
    not genomic order, so cytoband is the only reliable join key with all_lesions.
    """
    df = pd.read_csv(path, sep="\t", header=None)
    # Row 0 = cytoband, rows 1-3 = stats/boundaries, rows 4+ = genes
    cytoband_genes: dict[str, list[str]] = {}
    n_peaks = df.shape[1] - 1  # col 0 is the row label
    for col_idx in range(1, n_peaks + 1):
        cytoband = str(df.iloc[0, col_idx]).strip()
        genes = df.iloc[4:, col_idx].dropna().astype(str).tolist()
        # Filter out non-gene artifacts (hsa-mir-*, LOC*, empty)
        genes = [g for g in genes if g and not g.startswith("LOC") and not g.startswith("hsa-")]
        if genes:
            cytoband_genes[cytoband] = genes
    return cytoband_genes


def build_cna(clinical: pd.DataFrame) -> pd.DataFrame | None:
    """
    Build a gene-level CNA matrix from GISTIC2 all_lesions output.

    Values: +1 = amplification, -1 = deletion, 0 = no event.
    Sample mapping uses clinical_sgh.xlsx Oncoscan.CNV column (same stems as
    meth_sample_map.csv and GISTIC sample column names).
    """
    lesions_path = GISTIC_DIR / "all_lesions.conf_90.txt"
    if not lesions_path.exists():
        print("Warning: GISTIC all_lesions.conf_90.txt not found — skipping CNA.")
        return None

    print("Loading GISTIC CNA data...")

    # Build oncoscan_stem → SGH-OS-XXX map from clinical file
    oncoscan_to_sgh = {}
    for _, row in clinical.iterrows():
        stem = str(row["Oncoscan.CNV"]) if pd.notna(row["Oncoscan.CNV"]) else None
        if stem:
            oncoscan_to_sgh[stem] = str(row["SampleID"])

    # Parse all_lesions binary matrix
    df = pd.read_csv(lesions_path, sep="\t")
    amp_thresh_col = list(df.columns).index("Amplitude Threshold")
    raw_sample_cols = [c for c in df.columns[amp_thresh_col + 1:] if not c.startswith("Unnamed")]

    # Map GISTIC column names → SGH-OS-XXX
    sample_map = {c: oncoscan_to_sgh[c] for c in raw_sample_cols if c in oncoscan_to_sgh}
    print(f"  GISTIC samples: {len(raw_sample_cols)}, mapped to cohort: {len(sample_map)}")

    # Each peak has two rows: binary indicator and "- CN values" (continuous); keep binary only
    amp_rows = df[
        df["Unique Name"].str.startswith("Amplification") &
        ~df["Unique Name"].str.contains("CN values")
    ].reset_index(drop=True)
    del_rows = df[
        df["Unique Name"].str.startswith("Deletion") &
        ~df["Unique Name"].str.contains("CN values")
    ].reset_index(drop=True)
    print(f"  Amplification peaks: {len(amp_rows)}, Deletion peaks: {len(del_rows)}")

    # Parse gene lists per peak — keyed by cytoband (significance order ≠ genomic order)
    amp_cytoband_genes = _parse_gistic_genes(GISTIC_DIR / "amp_genes.conf_90.txt")
    del_cytoband_genes = _parse_gistic_genes(GISTIC_DIR / "del_genes.conf_90.txt")

    # Inject known OS drivers missing from GISTIC narrow peak boundaries
    # Also handles peaks whose gene lists were entirely filtered out (LOC*, hsa-*)
    for cytoband, extra_genes in PEAK_GENE_ADDITIONS.items():
        existing = set(amp_cytoband_genes.get(cytoband, []))
        added = [g for g in extra_genes if g not in existing]
        if added:
            amp_cytoband_genes.setdefault(cytoband, []).extend(added)
            print(f"  Peak {cytoband}: added {added} (peak borrowing)")

    # Collect all gene symbols, excluding known artifacts
    all_genes: set[str] = set()
    for genes in amp_cytoband_genes.values():
        all_genes.update(genes)
    for genes in del_cytoband_genes.values():
        all_genes.update(genes)
    blacklisted = {g for g in all_genes if _is_blacklisted(g)}
    all_genes -= blacklisted
    if blacklisted:
        dux_n = sum(1 for g in blacklisted if g.startswith("DUX"))
        or_n  = sum(1 for g in blacklisted if g.startswith("OR"))
        print(f"  Blacklisted {len(blacklisted)} artifact genes (DUX family: {dux_n}, OR family: {or_n})")

    cohort_samples = sorted(sample_map.values())
    cna = pd.DataFrame(0, index=cohort_samples, columns=sorted(all_genes), dtype="int8")
    cna.index.name = "case_id"

    # Join all_lesions rows to gene lists via cytoband (Descriptor column)
    mapped_cols = [c for c in raw_sample_cols if c in sample_map]

    # Fill amplifications (+1) — any GISTIC-called event (value > 0)
    for _, row in amp_rows.iterrows():
        cytoband = str(row["Descriptor"]).strip()
        genes = amp_cytoband_genes.get(cytoband, [])
        if not genes:
            continue
        vals = pd.to_numeric(row[mapped_cols], errors="coerce")
        called_raw = vals[vals > 0].index.tolist()
        called_sgh = [sample_map[c] for c in called_raw]
        valid_genes = [g for g in genes if g in cna.columns]
        if called_sgh and valid_genes:
            cna.loc[called_sgh, valid_genes] = 1

    # Fill deletions (-1) — only overwrite if not already +1 (amp takes priority)
    for _, row in del_rows.iterrows():
        cytoband = str(row["Descriptor"]).strip()
        genes = del_cytoband_genes.get(cytoband, [])
        if not genes:
            continue
        vals = pd.to_numeric(row[mapped_cols], errors="coerce")
        called_raw = vals[vals > 0].index.tolist()
        called_sgh = [sample_map[c] for c in called_raw]
        valid_genes = [g for g in genes if g in cna.columns]
        for sample in called_sgh:
            for gene in valid_genes:
                if cna.at[sample, gene] == 0:
                    cna.at[sample, gene] = -1

    n_altered = int((cna != 0).any(axis=1).sum())
    amp_events = int((cna == 1).sum().sum())
    del_events = int((cna == -1).sum().sum())
    print(f"  CNA matrix: {cna.shape[0]} samples × {cna.shape[1]} genes")
    print(f"  Samples with any alteration: {n_altered}")
    print(f"  Amplification events: {amp_events}, Deletion events: {del_events}")

    top_amp = (cna == 1).mean().sort_values(ascending=False).head(8)
    top_del = (cna == -1).mean().sort_values(ascending=False).head(8)
    print("  Top amplified genes (frequency):")
    for g, f in top_amp.items():
        print(f"    {g}: {f:.1%}")
    print("  Top deleted genes (frequency):")
    for g, f in top_del.items():
        print(f"    {g}: {f:.1%}")

    return cna


# ──────────────────────────────────────────────────────────────────────────────
# Methylation
# ──────────────────────────────────────────────────────────────────────────────

def build_methylation(shared_samples: list[str]) -> pd.DataFrame | None:
    """
    Load Illumina 850K per-sample beta-value files and build a samples × CpGs matrix.
    Filters to the top 10,000 most variable CpGs. Only samples in shared_samples included.
    """
    meth_dir = DATA_DIR / "methylation"
    map_path = DATA_DIR / "meth_sample_map.csv"

    if not map_path.exists() or not meth_dir.exists():
        print("Warning: methylation files not found — skipping methylation.")
        return None

    print("Loading methylation data...")
    sample_map = pd.read_csv(map_path)
    sample_map = sample_map[sample_map["sample_id"].isin(shared_samples)].copy()
    print(f"  {len(sample_map)} samples in map (matched to aligned set)")

    frames: dict[str, pd.Series] = {}
    for _, row in sample_map.iterrows():
        stem = str(row["meth_file_stem"])
        sample_id = str(row["sample_id"])
        fpath = meth_dir / f"{stem}.txt"
        if not fpath.exists():
            print(f"  Warning: missing {fpath} — skipping {sample_id}")
            continue
        df = pd.read_csv(fpath, sep="\t", usecols=["cpg_id", "beta"])
        frames[sample_id] = df.set_index("cpg_id")["beta"]

    if not frames:
        print("  Warning: no methylation files loaded — skipping.")
        return None

    meth = pd.DataFrame(frames).T
    meth.index.name = "case_id"
    print(f"  Raw methylation matrix: {meth.shape[0]} samples × {meth.shape[1]} CpGs")

    top_cpgs = meth.std(axis=0).nlargest(10_000).index
    meth = meth[top_cpgs].astype("float32")
    print(f"  Filtered to top {meth.shape[1]} CpGs by variance")

    out_path = DATA_DIR / "methylation.parquet"
    meth.to_parquet(out_path)
    print(f"  Saved: {out_path}  {out_path.stat().st_size // 1024} KB")
    return meth


# ──────────────────────────────────────────────────────────────────────────────
# Clinical
# ──────────────────────────────────────────────────────────────────────────────

def build_clinical(clinical: pd.DataFrame, expr_samples: list[str]) -> pd.DataFrame:
    print("Building clinical table...")
    df = clinical.copy()
    df["case_id"]                = df["SampleID"].astype(str)
    df["vital_status"]           = df["Status"].map({0: "Alive", 1: "Dead"})
    df["days_to_death"]          = df["OS"].where(df["Status"] == 1, other=np.nan)
    df["days_to_last_follow_up"] = df["OS"].where(df["Status"] == 0, other=np.nan)
    df["subtype"]                = df["iCluster-分组"].map(ICLUSTER_MAP)
    df["age_at_diagnosis"]       = df["Age"]
    df["gender"]                 = df["Gender"].str.lower()
    df["tumor_stage"]            = df["Ennking.Stage"]
    df["metastasis"]             = df["Metastasis"]
    df["pathology"]              = df["Pathology"]
    df["tmb"]                    = df["TMB"]
    df["hrd_score"]              = df["HRD"]
    df["icluster"]               = df["iCluster-分组"]

    keep = [
        "case_id", "vital_status", "days_to_death", "days_to_last_follow_up",
        "subtype", "age_at_diagnosis", "gender", "tumor_stage",
        "metastasis", "pathology", "tmb", "hrd_score", "icluster",
    ]
    df = df[keep].set_index("case_id").loc[lambda x: x.index.isin(expr_samples)]
    print(f"  Clinical table: {len(df)} samples")
    for s, n in df["subtype"].value_counts().sort_index().items():
        print(f"    {s}: {n}")
    return df


# ──────────────────────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Process SGH-OS (Jia 2022) data.")
    parser.add_argument("--skip-methylation", action="store_true",
                        help="Skip methylation.parquet (use if raw files unavailable).")
    parser.add_argument("--skip-cna", action="store_true",
                        help="Skip cna.parquet (use if GISTIC output unavailable).")
    parser.add_argument("--min-vaf", type=float, default=0.05,
                        help="Minimum tumor VAF to retain a somatic variant (default 0.05).")
    args = parser.parse_args()

    print(f"\n{'='*55}")
    print(f"  SGH-OS (Jia 2022) — data processing")
    print(f"{'='*55}\n")

    print("Loading clinical file...")
    clinical = pd.read_excel(DATA_DIR / "clinical_sgh.xlsx")
    print(f"  {len(clinical)} samples, {len(clinical.columns)} columns\n")

    expr = build_expression(clinical)
    print()
    mut  = build_mutations(clinical, min_vaf=args.min_vaf)
    print()
    clin = build_clinical(clinical, expr.index.tolist())

    # Align expression + mutations + clinical (mutations may cover fewer samples)
    shared_expr_clin = sorted(set(expr.index) & set(clin.index))
    expr = expr.loc[shared_expr_clin]
    clin = clin.loc[shared_expr_clin]
    # Mutations: left-join on expression cohort — missing = 0 (no WES)
    mut = mut.reindex(shared_expr_clin).fillna(0.0).astype("float32")
    print(f"\nAligned cohort: {len(shared_expr_clin)} samples")
    print(f"  With WES data: {int((mut.sum(axis=1) > 0).sum())} samples")

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

    # CNA
    if not args.skip_cna:
        print()
        cna = build_cna(clinical)
        if cna is not None:
            # Reindex to full expression cohort (samples without CNA = 0)
            cna = cna.reindex(shared_expr_clin).fillna(0).astype("int8")
            cna_path = DATA_DIR / "cna.parquet"
            cna.to_parquet(cna_path)
            print(f"  Saved: {cna_path}  {cna_path.stat().st_size // 1024} KB")
    else:
        print("\n[--skip-cna] Skipping CNA processing.")

    # Methylation
    if not args.skip_methylation:
        print()
        build_methylation(shared_expr_clin)
    else:
        print("\n[--skip-methylation] Skipping methylation processing.")

    print()


if __name__ == "__main__":
    main()
