"""
Process COSMIC datasets for BioDiscoveryGym.

COSMIC requires manual download from cancer.sanger.ac.uk (free account).
Place the downloaded .tar files in data/cosmic/ then run this script.

Files processed:
  Cosmic_CancerGeneCensus_*_GRCh38.tar         → cancer_gene_census.parquet
  Cosmic_CancerGeneCensusHallmarks*_GRCh38.tar → hallmarks.parquet
  Cosmic_Fusion_*_GRCh38.tar                   → fusions.parquet
  Cosmic_ResistanceMutations_*_GRCh38.tar      → resistance_mutations.parquet
  Cosmic_MutantCensus_*_GRCh38.tar             → mutation_freq.parquet (summarized)

Usage:
    python scripts/download_cosmic.py
    python scripts/download_cosmic.py --force    # rebuild existing parquets
"""

import argparse
import sys
import tarfile
from pathlib import Path

import pandas as pd

COSMIC_DIR = Path("data/cosmic")


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _find(pattern: str) -> Path | None:
    """Find first file matching a glob pattern in COSMIC_DIR."""
    hits = sorted(COSMIC_DIR.glob(pattern))
    return hits[0] if hits else None


def _ensure_extracted(tar_pattern: str, tsv_pattern: str) -> Path | None:
    """Extract tsv.gz from tar if not already present; return path or None."""
    tsv = _find(tsv_pattern)
    if tsv:
        return tsv
    tar = _find(tar_pattern)
    if tar is None:
        return None
    print(f"  Extracting {tar.name} ...", end=" ", flush=True)
    with tarfile.open(tar) as tf:
        for member in tf.getmembers():
            if member.name.endswith(".tsv.gz"):
                tf.extract(member, path=COSMIC_DIR)
                extracted = COSMIC_DIR / member.name
                print(f"→ {extracted.name}")
                return extracted
    return None


# ------------------------------------------------------------------
# Processors
# ------------------------------------------------------------------

def process_cgc(force: bool = False) -> bool:
    out = COSMIC_DIR / "cancer_gene_census.parquet"
    if out.exists() and not force:
        print(f"  [skip] {out.name}")
        return True
    src = _ensure_extracted("Cosmic_CancerGeneCensus_Tsv_*.tar", "Cosmic_CancerGeneCensus_v*.tsv.gz")
    if src is None:
        print("  [skip] Cancer Gene Census tar not found")
        return False
    df = pd.read_csv(src, sep="\t")
    keep = ["GENE_SYMBOL", "TIER", "ROLE_IN_CANCER", "SOMATIC",
            "TUMOUR_TYPES_SOMATIC", "TUMOUR_TYPES_GERMLINE", "MOLECULAR_GENETICS"]
    keep = [c for c in keep if c in df.columns]
    df = df[keep].rename(columns={
        "GENE_SYMBOL": "gene",
        "TIER": "cgc_tier",
        "ROLE_IN_CANCER": "role_in_cancer",
        "SOMATIC": "somatic",
        "TUMOUR_TYPES_SOMATIC": "tumour_types_somatic",
        "TUMOUR_TYPES_GERMLINE": "tumour_types_germline",
        "MOLECULAR_GENETICS": "molecular_genetics",
    })
    df["cgc_tier"] = pd.to_numeric(df["cgc_tier"], errors="coerce").astype("Int8")
    for col in ("somatic",):
        if col in df.columns:
            df[col] = df[col].str.strip().str.lower().eq("y")
    df = df.dropna(subset=["gene"]).set_index("gene")
    df.to_parquet(out)
    print(f"  CGC: {len(df):,} genes → {out.name}")
    return True


def process_hallmarks(force: bool = False) -> bool:
    out = COSMIC_DIR / "hallmarks.parquet"
    if out.exists() and not force:
        print(f"  [skip] {out.name}")
        return True
    src = _ensure_extracted("Cosmic_CancerGeneCensusHallmarks*Tsv_*.tar",
                            "Cosmic_CancerGeneCensusHallmarks*v*.tsv.gz")
    if src is None:
        print("  [skip] Hallmarks tar not found")
        return False
    df = pd.read_csv(src, sep="\t")
    # Aggregate: one row per gene with all unique hallmarks joined
    df = df[["GENE_SYMBOL", "HALLMARK"]].dropna(subset=["GENE_SYMBOL", "HALLMARK"])
    df = df[df["HALLMARK"].str.strip() != "function summary"]  # skip meta-rows
    agg = (df.groupby("GENE_SYMBOL")["HALLMARK"]
             .apply(lambda x: "; ".join(sorted(set(x.str.strip()))))
             .reset_index()
             .rename(columns={"GENE_SYMBOL": "gene", "HALLMARK": "hallmarks"}))
    agg = agg.set_index("gene")
    agg.to_parquet(out)
    print(f"  Hallmarks: {len(agg):,} genes → {out.name}")
    return True


def process_fusions(force: bool = False) -> bool:
    out = COSMIC_DIR / "fusions.parquet"
    if out.exists() and not force:
        print(f"  [skip] {out.name}")
        return True
    src = _ensure_extracted("Cosmic_Fusion_Tsv_*.tar", "Cosmic_Fusion_v*.tsv.gz")
    if src is None:
        print("  [skip] Fusion tar not found")
        return False
    df = pd.read_csv(src, sep="\t",
                     usecols=["FIVE_PRIME_GENE_SYMBOL", "THREE_PRIME_GENE_SYMBOL",
                               "COSMIC_SAMPLE_ID", "FUSION_TYPE"])
    df = df.dropna(subset=["FIVE_PRIME_GENE_SYMBOL", "THREE_PRIME_GENE_SYMBOL"])
    # Summarize: unique sample count per fusion pair
    summary = (df.groupby(["FIVE_PRIME_GENE_SYMBOL", "THREE_PRIME_GENE_SYMBOL"])
                 .agg(n_samples=("COSMIC_SAMPLE_ID", "nunique"),
                      fusion_types=("FUSION_TYPE",
                                    lambda x: "; ".join(sorted(set(x.dropna())))))
                 .reset_index()
                 .rename(columns={"FIVE_PRIME_GENE_SYMBOL": "gene_5prime",
                                   "THREE_PRIME_GENE_SYMBOL": "gene_3prime"})
                 .sort_values("n_samples", ascending=False))
    summary.to_parquet(out, index=False)
    print(f"  Fusions: {len(summary):,} unique fusion pairs → {out.name}")
    return True


def process_resistance(force: bool = False) -> bool:
    out = COSMIC_DIR / "resistance_mutations.parquet"
    if out.exists() and not force:
        print(f"  [skip] {out.name}")
        return True
    src = _ensure_extracted("Cosmic_ResistanceMutations_Tsv_*.tar",
                            "Cosmic_ResistanceMutations_v*.tsv.gz")
    if src is None:
        print("  [skip] Resistance mutations tar not found")
        return False
    df = pd.read_csv(src, sep="\t",
                     usecols=["GENE_SYMBOL", "DRUG_NAME", "DRUG_RESPONSE",
                               "MUTATION_AA", "COSMIC_PHENOTYPE_ID"])
    df = df.dropna(subset=["GENE_SYMBOL", "DRUG_NAME"])
    df = df.rename(columns={
        "GENE_SYMBOL": "gene",
        "DRUG_NAME": "drug_name",
        "DRUG_RESPONSE": "drug_response",
        "MUTATION_AA": "mutation_aa",
        "COSMIC_PHENOTYPE_ID": "phenotype_id",
    })
    df.to_parquet(out, index=False)
    print(f"  Resistance: {len(df):,} records → {out.name}")
    return True


def process_mutant_census(force: bool = False) -> bool:
    out = COSMIC_DIR / "mutation_freq.parquet"
    if out.exists() and not force:
        print(f"  [skip] {out.name}")
        return True
    src = _ensure_extracted("Cosmic_MutantCensus_Tsv_*.tar",
                            "Cosmic_MutantCensus_v*.tsv.gz")
    if src is None:
        print("  [skip] Mutant Census tar not found")
        return False

    print("  Summarizing Mutant Census (chunked read) ...", flush=True)
    gene_samples: dict[str, set] = {}
    chunksize = 500_000
    for chunk in pd.read_csv(src, sep="\t", usecols=["GENE_SYMBOL", "COSMIC_SAMPLE_ID"],
                              chunksize=chunksize):
        chunk = chunk.dropna(subset=["GENE_SYMBOL"])
        for gene, grp in chunk.groupby("GENE_SYMBOL"):
            if gene not in gene_samples:
                gene_samples[gene] = set()
            gene_samples[gene].update(grp["COSMIC_SAMPLE_ID"].tolist())

    freq = pd.DataFrame(
        {"gene": list(gene_samples.keys()),
         "n_mutated_samples": [len(v) for v in gene_samples.values()]}
    ).sort_values("n_mutated_samples", ascending=False).set_index("gene")
    freq.to_parquet(out)
    print(f"  Mutation freq: {len(freq):,} genes → {out.name}")
    return True


# ------------------------------------------------------------------
# Main
# ------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true",
                        help="Rebuild parquets even if they already exist")
    args = parser.parse_args()

    COSMIC_DIR.mkdir(parents=True, exist_ok=True)

    steps = [
        ("Cancer Gene Census",     process_cgc),
        ("Hallmarks",              process_hallmarks),
        ("Fusion genes",           process_fusions),
        ("Resistance mutations",   process_resistance),
        ("Mutant Census (summary)",process_mutant_census),
    ]

    any_missing = False
    for label, fn in steps:
        print(f"\n--- {label} ---")
        ok = fn(force=args.force)
        if not ok:
            any_missing = True

    if any_missing:
        print("\nNote: some files were missing. Place the .tar files in data/cosmic/ and re-run.")
    else:
        print("\nAll COSMIC datasets processed.")


if __name__ == "__main__":
    main()
