"""
HPC-side preparation: subset 850K methylation data to CTA gene promoter probes.

Uses GENCODE GTF (hg19/lift37) + 850k.bed probe positions — no Illumina manifest needed.

Usage (from the directory containing sample .txt files):
    python methylation_prep_hpc.py

Outputs (transfer both to local analysis/data/):
    cta_probes_beta.parquet   — beta values (0–1), probes × samples
    cta_probes_mval.parquet   — M-values (logit scale), probes × samples

Rows have two annotation columns ('gene', 'region') prepended to sample columns.
Sample columns are named SGH-OS-XXX (requires meth_sample_map.csv alongside script).
"""

import sys
import gzip
import re
import pandas as pd
from pathlib import Path

# ── Config ────────────────────────────────────────────────────────────────────

HERE = Path(__file__).resolve().parent   # directory containing this script

# Per-sample .txt files live in the methylation/ subdirectory
DATA_DIR = HERE / "methylation"

# Genome annotation — GENCODE v41lift37 (hg19)
GTF_PATH = HERE / "gencode.v41lift37.basic.annotation.gtf"

# 850K probe BED: chr | start | end | cpg_id  (1-bp intervals, hg19)
BED_PATH = HERE / "850k.bed"

# Sample ID mapping (transfer from local alongside this script)
SAMPLE_MAP_CSV = Path("meth_sample_map.csv")

# Outputs
OUT_BETA = Path("cta_probes_beta.parquet")
OUT_MVAL = Path("cta_probes_mval.parquet")

# CTA genes to query
CTA_GENES = [
    "SPATA31A6", "PRAMEF25", "GOLGA6A", "GOLGA6B",
    "TRIM49B", "TRIM51", "TRIM64B", "CFAP65", "RCOR2",
]

# Promoter window around TSS (bp).  Captures TSS1500 + TSS200 + a little downstream.
UPSTREAM   = 2000
DOWNSTREAM = 500

# ── GTF parsing ───────────────────────────────────────────────────────────────

def parse_gtf_tss(gtf_path: Path, genes: list) -> pd.DataFrame:
    """
    Extract strand-aware TSS for all 'gene' records matching our target gene names.
    Returns DataFrame: gene | chrom | tss (0-based)
    """
    gene_set = set(genes)
    re_name = re.compile(r'gene_name "([^"]+)"')
    records = []

    opener = gzip.open if str(gtf_path).endswith(".gz") else open
    print(f"Parsing GTF: {gtf_path}")
    with opener(gtf_path, "rt") as fh:
        for line in fh:
            if line.startswith("#"):
                continue
            parts = line.rstrip().split("\t")
            if len(parts) < 9 or parts[2] != "gene":
                continue
            m = re_name.search(parts[8])
            if not m:
                continue
            gname = m.group(1)
            if gname not in gene_set:
                continue
            chrom, start, end, strand = parts[0], int(parts[3]), int(parts[4]), parts[6]
            # GTF is 1-based inclusive; TSS = start−1 (0-based) for + strand
            tss = (start - 1) if strand == "+" else (end - 1)
            records.append({"gene": gname, "chrom": chrom, "tss": tss, "strand": strand})

    df = pd.DataFrame(records)
    if df.empty:
        print(f"WARNING: none of {genes} found in GTF. Check gene names.")
    else:
        found = df["gene"].unique().tolist()
        missing = [g for g in genes if g not in found]
        print(f"Found TSS entries: {len(df)} across {len(found)} genes")
        if missing:
            print(f"  Not in GTF: {missing}")
    return df


def tss_to_windows(tss_df: pd.DataFrame, upstream: int, downstream: int) -> pd.DataFrame:
    """Convert TSS points to promoter windows (strand-aware)."""
    rows = []
    for _, r in tss_df.iterrows():
        if r["strand"] == "+":
            win_start = r["tss"] - upstream
            win_end   = r["tss"] + downstream
        else:
            win_start = r["tss"] - downstream
            win_end   = r["tss"] + upstream
        rows.append({
            "gene":   r["gene"],
            "chrom":  r["chrom"],
            "win_start": max(0, win_start),
            "win_end":   win_end,
        })
    return pd.DataFrame(rows)


# ── Probe selection ───────────────────────────────────────────────────────────

def load_bed(bed_path: Path) -> pd.DataFrame:
    """Load 850k.bed → DataFrame with chrom, pos (0-based), cpg_id."""
    print(f"Loading probe BED: {bed_path}")
    bed = pd.read_csv(
        bed_path, sep="\t", header=None,
        names=["chrom", "start", "end", "cpg_id"],
        usecols=["chrom", "start", "cpg_id"],
    )
    bed = bed.rename(columns={"start": "pos"})
    print(f"  {len(bed):,} probes loaded")
    return bed


def intersect_probes(bed: pd.DataFrame, windows: pd.DataFrame) -> pd.DataFrame:
    """
    Pure-pandas interval intersection: find all probes within any promoter window.
    Returns DataFrame: cpg_id | gene | region
    """
    hits = []
    for chrom, grp in windows.groupby("chrom"):
        probes_chr = bed[bed["chrom"] == chrom]
        if probes_chr.empty:
            continue
        for _, win in grp.iterrows():
            mask = (probes_chr["pos"] >= win["win_start"]) & \
                   (probes_chr["pos"] <  win["win_end"])
            for cpg_id in probes_chr.loc[mask, "cpg_id"]:
                hits.append({"cpg_id": cpg_id, "gene": win["gene"]})

    if not hits:
        sys.exit("No probes found in any promoter window. Check genome build compatibility.")

    probes = (
        pd.DataFrame(hits)
        .drop_duplicates()
        .groupby("cpg_id")["gene"]
        .apply(lambda x: ";".join(sorted(set(x))))
        .reset_index()
        .rename(columns={"gene": "gene"})
    )
    probes["region"] = "promoter"
    print(f"\nProbes in CTA promoter windows: {len(probes)}")
    print(probes.groupby("gene").size().rename("n_probes").to_string())
    return probes


# ── Sample processing ─────────────────────────────────────────────────────────

def load_sample_map(path: Path) -> dict:
    if not path.exists():
        print(f"WARNING: {path} not found — columns will use raw filename stems.")
        return {}
    df = pd.read_csv(path)
    return dict(zip(df["meth_file_stem"].astype(str), df["sample_id"].astype(str)))


def build_matrix(
    txt_files: list,
    probe_ids: set,
    stem_to_sid: dict,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    beta_cols, mval_cols = {}, {}
    total = len(txt_files)
    skipped = []
    for i, fp in enumerate(txt_files, 1):
        stem = fp.stem
        sid = stem_to_sid.get(stem, stem)
        if stem not in stem_to_sid:
            skipped.append(stem)
        print(f"  [{i}/{total}] {stem} → {sid}", end="\r", flush=True)
        df = pd.read_csv(fp, sep="\t", usecols=["cpg_id", "beta", "mval"])
        df = df[df["cpg_id"].isin(probe_ids)].set_index("cpg_id")
        beta_cols[sid] = df["beta"]
        mval_cols[sid] = df["mval"]
    print()
    if skipped:
        print(f"WARNING: {len(skipped)} files not in sample map: {skipped[:5]}")
    return pd.DataFrame(beta_cols), pd.DataFrame(mval_cols)


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    # 1. Parse GTF → TSS → promoter windows
    tss_df   = parse_gtf_tss(GTF_PATH, CTA_GENES)
    windows  = tss_to_windows(tss_df, UPSTREAM, DOWNSTREAM)

    # 2. Load probe BED → intersect with windows
    bed      = load_bed(BED_PATH)
    probes   = intersect_probes(bed, windows)
    probe_ids = set(probes["cpg_id"])

    # 3. Sample map
    stem_to_sid = load_sample_map(SAMPLE_MAP_CSV)
    print(f"\nSample map: {len(stem_to_sid)} entries")

    # 4. Find and process sample files
    txt_files = sorted(DATA_DIR.glob("*.txt"))
    if not txt_files:
        sys.exit(f"No .txt files found in {DATA_DIR.resolve()}")
    print(f"Processing {len(txt_files)} sample files...")
    beta, mval = build_matrix(txt_files, probe_ids, stem_to_sid)

    # 5. Attach gene/region annotation and save
    annot = probes.set_index("cpg_id")[["gene", "region"]]
    beta  = annot.join(beta,  how="inner")
    mval  = annot.join(mval, how="inner")

    beta.to_parquet(OUT_BETA)
    mval.to_parquet(OUT_MVAL)
    print(f"\nSaved: {OUT_BETA}  ({beta.shape[0]} probes × {beta.shape[1]-2} samples)")
    print(f"Saved: {OUT_MVAL}")
    print("\nTransfer both parquets to local analysis/data/ then run cta_methylation.py")


if __name__ == "__main__":
    main()
