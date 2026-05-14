#!/usr/bin/env python3
"""
Build survival- and mutation-perturbed LIHC data files.

Defines groups from expression-based k-means clustering (k=2 on top PCs)
so that ALL 371 samples are assigned and the swap covers the full cohort.
This guarantees the survival direction flips regardless of which samples
have Xena subtype annotations.

Swaps canonical signals between the two expression-derived groups:
  - Survival: vital_status + days_to_death + days_to_last_follow_up
  - Mutations: TP53 and CTNNB1 columns

Expression and RPPA are unchanged. The agent will find the same clusters
but see inverted survival outcomes and inverted mutation enrichment.

Outputs:
  data/tcga/lihc/LIHC_clinical_perturbed.tsv
  data/tcga/lihc/mutations_perturbed.parquet

Usage:
    python scripts/perturb_lihc.py [--seed 42] [--no-survival] [--no-mutations]
"""
import argparse
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.decomposition import PCA
from sklearn.preprocessing import StandardScaler

DATA_DIR = Path("data/tcga/lihc")

SURVIVAL_COLS = ["vital_status", "days_to_death", "days_to_last_follow_up"]
MUTATION_GENES = ["TP53", "CTNNB1"]
N_TOP_GENES = 2000
N_PCS = 10


def derive_groups(seed: int) -> tuple[list[str], list[str]]:
    """
    Cluster expression into k=2 groups using top variable genes + PCA.
    Returns (group_a_ids, group_b_ids) as lists of TCGA case barcodes.
    Group A = higher PC1 (hepatocyte-like, better survival canonically).
    Group B = lower PC1 (proliferative, worse survival canonically).
    """
    expr = pd.read_parquet(DATA_DIR / "expression.parquet")

    # Top variable genes
    gene_var = expr.var()
    top_genes = gene_var.nlargest(N_TOP_GENES).index
    X = expr[top_genes]

    # Z-score + PCA
    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)
    pca = PCA(n_components=N_PCS, random_state=seed)
    X_pca = pca.fit_transform(X_scaled)

    # K-means k=2
    km = KMeans(n_clusters=2, random_state=seed, n_init=10)
    labels = km.fit_predict(X_pca)

    # Identify which cluster is hepatocyte-like (higher PC1 = more differentiated)
    pc1 = X_pca[:, 0]
    cluster_pc1 = {c: pc1[labels == c].mean() for c in [0, 1]}
    hepatocyte_cluster = max(cluster_pc1, key=cluster_pc1.get)
    proliferative_cluster = 1 - hepatocyte_cluster

    ids = expr.index.tolist()
    group_a = [ids[i] for i in range(len(ids)) if labels[i] == hepatocyte_cluster]
    group_b = [ids[i] for i in range(len(ids)) if labels[i] == proliferative_cluster]

    print(f"  Group A (hepatocyte-like, PC1 mean={cluster_pc1[hepatocyte_cluster]:.1f}): "
          f"{len(group_a)} samples")
    print(f"  Group B (proliferative,   PC1 mean={cluster_pc1[proliferative_cluster]:.1f}): "
          f"{len(group_b)} samples")
    return group_a, group_b


def swap_survival(clin: pd.DataFrame, group_a: list, group_b: list,
                  rng: np.random.Generator) -> pd.DataFrame:
    """
    Swap survival tuples between Group A and Group B.
    All samples are covered — no unannotated residual.
    """
    clin = clin.copy()

    a_idx = [i for i in group_a if i in clin.index]
    b_idx = [i for i in group_b if i in clin.index]

    a_tuples = clin.loc[a_idx, SURVIVAL_COLS].values.tolist()
    b_tuples = clin.loc[b_idx, SURVIVAL_COLS].values.tolist()

    rng.shuffle(a_tuples)
    rng.shuffle(b_tuples)

    n_a, n_b = len(a_idx), len(b_idx)
    b_assigned = [b_tuples[i % n_b] for i in range(n_a)]
    a_assigned = [a_tuples[i % n_a] for i in range(n_b)]

    for i, idx in enumerate(a_idx):
        clin.loc[idx, SURVIVAL_COLS] = b_assigned[i]
    for i, idx in enumerate(b_idx):
        clin.loc[idx, SURVIVAL_COLS] = a_assigned[i]

    return clin


def swap_mutations(mut: pd.DataFrame, group_a: list, group_b: list,
                   rng: np.random.Generator) -> pd.DataFrame:
    """
    Swap TP53 and CTNNB1 mutation values between Group A and Group B.
    """
    mut = mut.copy()

    a_idx = [i for i in group_a if i in mut.index]
    b_idx = [i for i in group_b if i in mut.index]

    for gene in MUTATION_GENES:
        if gene not in mut.columns:
            print(f"  WARNING: {gene} not in mutations — skipping")
            continue

        a_vals = mut.loc[a_idx, gene].values.copy()
        b_vals = mut.loc[b_idx, gene].values.copy()

        rng.shuffle(a_vals)
        rng.shuffle(b_vals)

        n_a, n_b = len(a_idx), len(b_idx)
        b_assigned = [b_vals[i % n_b] for i in range(n_a)]
        a_assigned = [a_vals[i % n_a] for i in range(n_b)]

        for i, idx in enumerate(a_idx):
            mut.loc[idx, gene] = b_assigned[i]
        for i, idx in enumerate(b_idx):
            mut.loc[idx, gene] = a_assigned[i]

    return mut


def verify(clin_orig: pd.DataFrame, clin_pert: pd.DataFrame,
           mut_orig: pd.DataFrame, mut_pert: pd.DataFrame,
           group_a: list, group_b: list) -> None:
    """Print before/after summary to confirm perturbation direction flipped."""
    print("\n── Survival verification ──")
    for label, ids in [("Group A (hepatocyte)", group_a), ("Group B (proliferative)", group_b)]:
        for df, tag in [(clin_orig, "original"), (clin_pert, "perturbed")]:
            idx = [i for i in ids if i in df.index]
            alive = (df.loc[idx, "vital_status"] == "Alive").sum()
            dead = (df.loc[idx, "vital_status"] == "Dead").sum()
            med = df.loc[idx, "days_to_death"].median()
            med_str = f"{med:.0f}d" if not pd.isna(med) else "NaN"
            print(f"  {label:30s} {tag:10s}: Alive={alive}, Dead={dead}, "
                  f"median_days_to_death={med_str}")

    print("\n── Mutation verification ──")
    for gene in MUTATION_GENES:
        if gene not in mut_orig.columns:
            continue
        for label, ids in [("Group A (hepatocyte)", group_a), ("Group B (proliferative)", group_b)]:
            for df, tag in [(mut_orig, "original"), (mut_pert, "perturbed")]:
                idx = [i for i in ids if i in df.index]
                rate = df.loc[idx, gene].mean()
                print(f"  {gene:8s} {label:30s} {tag:10s}: {rate:.2%} mutated")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--no-survival", action="store_true")
    parser.add_argument("--no-mutations", action="store_true")
    args = parser.parse_args()

    rng = np.random.default_rng(args.seed)

    print("Deriving expression-based clusters (k=2)...")
    group_a, group_b = derive_groups(args.seed)

    # Survival
    clin_path = DATA_DIR / "LIHC_clinical.tsv"
    clin = pd.read_csv(clin_path, sep="\t", index_col=0)
    clin_pert = clin.copy()

    if not args.no_survival:
        print("\nSwapping survival columns...")
        clin_pert = swap_survival(clin, group_a, group_b, rng)
        out_clin = DATA_DIR / "LIHC_clinical_perturbed.tsv"
        clin_pert.to_csv(out_clin, sep="\t")
        print(f"  Written: {out_clin}")

    # Mutations
    mut_path = DATA_DIR / "mutations.parquet"
    mut = pd.read_parquet(mut_path)
    mut_pert = mut.copy()

    if not args.no_mutations:
        print("\nSwapping mutation columns (TP53, CTNNB1)...")
        mut_pert = swap_mutations(mut, group_a, group_b, rng)
        out_mut = DATA_DIR / "mutations_perturbed.parquet"
        mut_pert.to_parquet(out_mut)
        print(f"  Written: {out_mut}")

    verify(clin, clin_pert, mut, mut_pert, group_a, group_b)
    print("\nDone.")


if __name__ == "__main__":
    main()
