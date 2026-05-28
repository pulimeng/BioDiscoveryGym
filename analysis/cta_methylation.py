"""
Local analysis: CTA promoter methylation by cluster — G2 s0 (run 47941195)

Tests whether C1 (CTA cluster) is hypomethylated at CTA gene promoters vs C2/C3/C4.

Run from project root after transferring parquet files from HPC:
    conda run -n biodiscoverygym python analysis/cta_methylation.py

Expects (transfer from HPC):
    analysis/data/cta_probes_beta.parquet
    analysis/data/cta_probes_mval.parquet   (optional)
"""

import json
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
import seaborn as sns
from pathlib import Path
from scipy.stats import mannwhitneyu

ROOT    = Path(__file__).parent.parent
RUN_DIR = ROOT / "results/cohort/external/47941195"
DATA_DIR = ROOT / "data/external/os_jia2022"
METH_DIR = Path(__file__).parent / "data"   # drop HPC parquets here
OUT_HEAT   = RUN_DIR / "cta_methylation_heatmap.png"
OUT_STRIPS = RUN_DIR / "cta_methylation_strips.png"
OUT_SCATTER = RUN_DIR / "cta_expr_vs_meth.png"

CTA_GENES = [
    "SPATA31A6", "PRAMEF25", "GOLGA6A", "GOLGA6B",
    "TRIM49B", "TRIM51", "TRIM64B", "CFAP65", "RCOR2",
]

CLUSTER_ORDER = [
    "C1_highHRD_poorSurv",
    "C2_highMortality_Fibroblastic",
    "C3_lowHRD_goodSurv",
    "C4_highHRD_bestSurv_Osteoblastic",
]
CLUSTER_LABELS = {
    "C1_highHRD_poorSurv":              "C1 — CTA, poor\n(n=25)",
    "C2_highMortality_Fibroblastic":    "C2 — Immune, worst\n(n=20)",
    "C3_lowHRD_goodSurv":              "C3 — Stromal, good\n(n=25)",
    "C4_highHRD_bestSurv_Osteoblastic": "C4 — Osteoblastic, best\n(n=21)",
}
CLUSTER_COLORS = {
    "C1_highHRD_poorSurv":              "#7e22ce",
    "C2_highMortality_Fibroblastic":    "#c2410c",
    "C3_lowHRD_goodSurv":              "#0d7377",
    "C4_highHRD_bestSurv_Osteoblastic": "#15803d",
}

SHORT_LABELS = {
    "C1_highHRD_poorSurv":              "C1\nCTA",
    "C2_highMortality_Fibroblastic":    "C2\nImmune",
    "C3_lowHRD_goodSurv":              "C3\nStromal",
    "C4_highHRD_bestSurv_Osteoblastic": "C4\nOsteoblastic",
}


# ── Data loading ──────────────────────────────────────────────────────────────

def load_cluster_assignments() -> pd.Series:
    """Reconstruct original sample IDs from G2 s0 grouping (seed=0)."""
    expr = pd.read_parquet(DATA_DIR / "expression.parquet")
    rng = np.random.default_rng(0)
    shuffled = rng.permutation(expr.index.tolist()).tolist()
    anon_ids = [f"SAMPLE_{i:04d}" for i in range(len(shuffled))]
    sample_map = dict(zip(anon_ids, shuffled))
    grouping = json.load(open(RUN_DIR / "grouping.json"))
    return pd.Series({sample_map[s]: label for s, label in grouping.items()}, name="cluster")


def load_methylation() -> pd.DataFrame:
    """
    Load beta matrix from HPC parquet.
    Rows = CpG probes (index = cpg_id, columns include 'gene', 'region', then sample IDs).
    """
    path = METH_DIR / "cta_probes_beta.parquet"
    if not path.exists():
        raise FileNotFoundError(
            f"{path} not found.\n"
            "Run analysis/methylation_prep_hpc.py on HPC and transfer the output here."
        )
    return pd.read_parquet(path)


def load_expression() -> pd.DataFrame:
    return pd.read_parquet(DATA_DIR / "expression.parquet")


# ── Analysis ──────────────────────────────────────────────────────────────────

def per_gene_mean_beta(beta_df: pd.DataFrame, cluster_series: pd.Series) -> pd.DataFrame:
    """Average beta across all promoter probes per gene × sample, then group by cluster."""
    sample_cols = [c for c in beta_df.columns if c not in {"gene", "region"}]
    # Restrict to samples with cluster assignments
    common = [s for s in sample_cols if s in cluster_series.index]

    gene_beta = (
        beta_df.groupby("gene")[common]
        .mean()
        .T  # samples × genes
    )
    gene_beta = gene_beta.join(cluster_series)
    return gene_beta


def run_stats(gene_beta: pd.DataFrame, genes: list) -> pd.DataFrame:
    """Mann-Whitney U: C1 vs rest for each gene. Returns tidy results DataFrame."""
    c1 = gene_beta[gene_beta["cluster"] == "C1_highHRD_poorSurv"]
    rest = gene_beta[gene_beta["cluster"] != "C1_highHRD_poorSurv"]
    rows = []
    for g in genes:
        if g not in gene_beta.columns:
            continue
        u, p = mannwhitneyu(c1[g], rest[g], alternative="less")  # C1 < rest = hypomethylated
        rows.append({
            "gene":       g,
            "C1_median":  c1[g].median(),
            "rest_median": rest[g].median(),
            "delta":      c1[g].median() - rest[g].median(),
            "U":          u,
            "p_mw":       p,
        })
    return pd.DataFrame(rows).set_index("gene")


# ── Plotting ──────────────────────────────────────────────────────────────────

def plot_heatmap(gene_beta: pd.DataFrame, genes: list, stats: pd.DataFrame):
    """4-cluster × N-gene heatmap of mean beta, mirroring the expression heatmap."""
    available = [g for g in genes if g in gene_beta.columns]
    cluster_means = (
        gene_beta.groupby("cluster")[available]
        .mean()
        .reindex(CLUSTER_ORDER)
    )

    row_labels = [CLUSTER_LABELS[c] for c in CLUSTER_ORDER]
    row_colors = [CLUSTER_COLORS[c] for c in CLUSTER_ORDER]

    fig, ax = plt.subplots(figsize=(13, 4))
    fig.suptitle(
        "CTA promoter methylation (mean beta) by cluster — G2 s0 (run 47941195)\n"
        "Beta = 0 (unmethylated) → 1 (fully methylated)  |  * p<0.05 C1 vs rest (Mann-Whitney)",
        fontsize=10, y=1.02,
    )

    # Annotate with mean beta + significance star
    annot = cluster_means.copy().round(2).astype(str)
    for g in available:
        if g in stats.index and stats.loc[g, "p_mw"] < 0.05:
            annot.loc["C1_highHRD_poorSurv", g] += " *"

    sns.heatmap(
        cluster_means,
        ax=ax,
        cmap="RdBu_r",          # blue = hypomethylated (low beta), red = hypermethylated
        vmin=0, vmax=1,
        center=0.5,
        annot=annot,
        fmt="",
        annot_kws={"size": 8},
        linewidths=0.5,
        linecolor="#e0e0e0",
        yticklabels=row_labels,
        xticklabels=available,
        cbar_kws={"label": "mean beta", "shrink": 0.7},
    )
    ax.set_xlabel("")
    ax.set_ylabel("")
    ax.tick_params(axis="x", labelsize=9, rotation=40)
    plt.setp(ax.get_xticklabels(), ha="right")
    ax.tick_params(axis="y", labelsize=9, rotation=0)
    for tick, color in zip(ax.get_yticklabels(), row_colors):
        tick.set_color(color)
        tick.set_fontweight("bold")

    plt.savefig(OUT_HEAT, dpi=130, bbox_inches="tight")
    print(f"Saved: {OUT_HEAT}")
    plt.close()


def plot_strips(gene_beta: pd.DataFrame, genes: list, stats: pd.DataFrame):
    """2×N strip plot: all samples per gene per cluster, mirroring expression strips."""
    available = [g for g in genes if g in gene_beta.columns]
    long = (
        gene_beta[available + ["cluster"]]
        .melt(id_vars=["cluster"], var_name="gene", value_name="beta", ignore_index=False)
        .reset_index(drop=True)
    )
    long["cluster_label"] = long["cluster"].map(SHORT_LABELS)
    cl_label_order = [SHORT_LABELS[c] for c in CLUSTER_ORDER]
    palette = {SHORT_LABELS[k]: v for k, v in CLUSTER_COLORS.items()}

    ncols = 4
    nrows = int(np.ceil(len(available) / ncols))
    fig, axes = plt.subplots(nrows, ncols, figsize=(13, 3.5 * nrows), sharey=False)
    fig.suptitle(
        "CTA promoter methylation — all samples  (G2 s0, run 47941195)\n"
        "Each dot = one patient (mean beta across promoter probes); bar = cluster median",
        fontsize=11,
    )

    for ax, gene in zip(axes.flat, available):
        sub = long[long["gene"] == gene]
        sns.stripplot(
            data=sub, x="cluster_label", y="beta",
            order=cl_label_order, hue="cluster_label",
            hue_order=cl_label_order, palette=palette,
            size=4, jitter=True, alpha=0.75, legend=False, ax=ax,
        )
        medians = sub.groupby("cluster_label")["beta"].median()
        for i, cl_label in enumerate(cl_label_order):
            med = medians.get(cl_label, np.nan)
            if not np.isnan(med):
                ax.plot([i - 0.3, i + 0.3], [med, med],
                        color="black", linewidth=1.5, solid_capstyle="round")

        sig = ""
        if gene in stats.index and stats.loc[gene, "p_mw"] < 0.05:
            sig = f"  p={stats.loc[gene, 'p_mw']:.3f} *"
        ax.set_title(gene + sig, fontsize=10, fontweight="bold")
        ax.set_xlabel("")
        ax.set_ylabel("mean beta" if ax in axes[:, 0] else "")
        ax.set_ylim(0, 1)
        ax.axhline(0.5, color="#aaa", linewidth=0.5, linestyle="--")
        ax.tick_params(axis="x", labelsize=7)
        ax.tick_params(axis="y", labelsize=8)
        ax.spines[["top", "right"]].set_visible(False)

    for ax in axes.flat[len(available):]:
        ax.set_visible(False)

    plt.tight_layout()
    plt.savefig(OUT_STRIPS, dpi=130, bbox_inches="tight")
    print(f"Saved: {OUT_STRIPS}")
    plt.close()


def plot_expr_vs_meth(gene_beta: pd.DataFrame, cluster_series: pd.Series, genes: list):
    """
    Scatter: per-sample expression vs methylation for each CTA gene.
    The key test: in C1 samples, do high-expressors have low beta?
    """
    expr = load_expression()
    available = [g for g in genes if g in gene_beta.columns and g in expr.columns]

    ncols = 4
    nrows = int(np.ceil(len(available) / ncols))
    fig, axes = plt.subplots(nrows, ncols, figsize=(13, 3.5 * nrows), sharey=False)
    fig.suptitle(
        "Expression vs promoter methylation per sample  (G2 s0)\n"
        "C1 samples highlighted — inverse correlation supports epigenetic derepression",
        fontsize=11,
    )

    sample_colors = cluster_series.map(CLUSTER_COLORS)

    for ax, gene in zip(axes.flat, available):
        meth_col = gene_beta[["cluster", gene]].rename(columns={gene: "beta"})
        e = expr[[gene]].rename(columns={gene: "expr"})
        merged = meth_col.join(e, how="inner")
        merged["color"] = merged["cluster"].map(CLUSTER_COLORS)

        # All non-C1 samples grey, C1 purple
        non_c1 = merged[merged["cluster"] != "C1_highHRD_poorSurv"]
        c1     = merged[merged["cluster"] == "C1_highHRD_poorSurv"]

        ax.scatter(non_c1["beta"], non_c1["expr"], c="#cccccc", s=20, alpha=0.5, zorder=1)
        ax.scatter(c1["beta"], c1["expr"],
                   c=CLUSTER_COLORS["C1_highHRD_poorSurv"],
                   s=30, alpha=0.85, zorder=2, label="C1")

        # Pearson r for C1 only
        if len(c1) > 3 and c1["beta"].std() > 0 and c1["expr"].std() > 0:
            r = c1["beta"].corr(c1["expr"])
            ax.text(0.97, 0.97, f"C1 r={r:.2f}",
                    transform=ax.transAxes, ha="right", va="top",
                    fontsize=8, color=CLUSTER_COLORS["C1_highHRD_poorSurv"])

        ax.set_title(gene, fontsize=10, fontweight="bold")
        ax.set_xlabel("mean beta (promoter)" if ax in axes[-1, :] else "")
        ax.set_ylabel("log2(CPM+1)" if ax in axes[:, 0] else "")
        ax.set_xlim(0, 1)
        ax.spines[["top", "right"]].set_visible(False)

    for ax in axes.flat[len(available):]:
        ax.set_visible(False)

    plt.tight_layout()
    plt.savefig(OUT_SCATTER, dpi=130, bbox_inches="tight")
    print(f"Saved: {OUT_SCATTER}")
    plt.close()


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    cluster_series = load_cluster_assignments()
    beta_df = load_methylation()

    print(f"Beta matrix: {beta_df.shape[0]} probes, {beta_df.shape[1]-2} samples")
    print(f"Probes per gene:\n{beta_df.groupby('gene').size().to_string()}\n")

    gene_beta = per_gene_mean_beta(beta_df, cluster_series)
    available = [g for g in CTA_GENES if g in gene_beta.columns]

    stats = run_stats(gene_beta, available)
    print("=== C1 vs rest (Mann-Whitney, H1: C1 hypomethylated) ===")
    print(stats[["C1_median", "rest_median", "delta", "p_mw"]].round(3).to_string())

    plot_heatmap(gene_beta, available, stats)
    plot_strips(gene_beta, available, stats)
    plot_expr_vs_meth(gene_beta, cluster_series, available)


if __name__ == "__main__":
    main()
