"""
CTA marker expression heatmap — G2 s0 cluster assignments (run 47941195)

Shows expression of cancer-testis antigen genes across all 4 clusters.
Run from project root:
    conda run -n biodiscoverygym python analysis/cta_heatmap.py
"""

import json
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
import seaborn as sns
from pathlib import Path
from scipy.stats import mannwhitneyu
from statannotations.Annotator import Annotator

ROOT = Path(__file__).parent.parent
RUN_DIR = ROOT / "results/cohort/external/47941195"
DATA_DIR = ROOT / "data/external/os_jia2022"
OUT_HEATMAP = RUN_DIR / "cta_heatmap.png"
OUT_STRIPS  = RUN_DIR / "cta_strips.png"

CTA_GENES = [
    "SPATA31A6", "PRAMEF25", "GOLGA6A", "GOLGA6B",
    "TRIM49B", "TRIM51", "TRIM64B",
    "CFAP65",      # also C1-specific in the run (ciliary/testis)
]
# Separate: RCOR2 is a ubiquitous chromatin regulator (highest in C4), not C1-specific.
# Plotting it alongside near-zero CTAs on the same color scale crushes the signal.
CONTEXT_GENES = ["RCOR2"]

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
    "C1_highHRD_poorSurv":           "#7e22ce",
    "C2_highMortality_Fibroblastic":  "#c2410c",
    "C3_lowHRD_goodSurv":            "#0d7377",
    "C4_highHRD_bestSurv_Osteoblastic": "#15803d",
}


def load_data():
    expr = pd.read_parquet(DATA_DIR / "expression.parquet")

    # Reconstruct sample anonymization (seed=0, same as episode run)
    rng = np.random.default_rng(0)
    shuffled = rng.permutation(expr.index.tolist()).tolist()
    anon_ids = [f"SAMPLE_{i:04d}" for i in range(len(shuffled))]
    sample_map = dict(zip(anon_ids, shuffled))  # SAMPLE_XXXX → SGH-OS-XXX

    grouping = json.load(open(RUN_DIR / "grouping.json"))
    orig_grouping = {sample_map[s]: label for s, label in grouping.items()}

    cluster_series = pd.Series(orig_grouping, name="cluster")
    return expr, cluster_series


def main():
    expr, cluster_series = load_data()

    available_cta = [g for g in CTA_GENES if g in expr.columns]
    available_ctx = [g for g in CONTEXT_GENES if g in expr.columns]
    missing = [g for g in CTA_GENES + CONTEXT_GENES if g not in expr.columns]
    if missing:
        print(f"Not in expression matrix: {missing}")

    all_genes = available_cta + available_ctx
    plot_data = expr[all_genes].copy().join(cluster_series)

    # --- Cluster-level means (4 rows × N genes) ---
    raw_means = (
        plot_data.groupby("cluster")[all_genes]
        .mean()
        .reindex(CLUSTER_ORDER)
    )
    # Z-score across clusters per gene (highlights which cluster is high)
    def zscore_rows(df):
        return df.apply(lambda col: (col - col.mean()) / max(col.std(), 1e-6), axis=0)

    cta_z = zscore_rows(raw_means[available_cta])
    ctx_raw = raw_means[available_ctx]

    row_labels = [CLUSTER_LABELS[c] for c in CLUSTER_ORDER]
    row_colors = [CLUSTER_COLORS[c] for c in CLUSTER_ORDER]

    # --- Figure ---
    fig = plt.figure(figsize=(15, 5))
    fig.suptitle(
        "CTA marker expression by cluster — G2 s0 (run 47941195)\n"
        "Values are cluster-mean log2(CPM+1), colored by z-score across clusters",
        fontsize=11, y=1.02,
    )

    # Layout: CTA heatmap | gap | RCOR2 heatmap
    gs = gridspec.GridSpec(1, 3, width_ratios=[1, 0.03, 0.18], wspace=0.04)
    ax_cta = fig.add_subplot(gs[0])
    ax_gap = fig.add_subplot(gs[1])
    ax_ctx = fig.add_subplot(gs[2])
    ax_gap.axis("off")

    # CTA z-score heatmap
    sns.heatmap(
        cta_z,
        ax=ax_cta,
        cmap="RdBu_r",
        center=0,
        vmin=-1.8, vmax=1.8,
        annot=raw_means[available_cta].round(2),
        fmt=".2f",
        annot_kws={"size": 8},
        linewidths=0.5,
        linecolor="#e0e0e0",
        yticklabels=row_labels,
        xticklabels=available_cta,
        cbar_kws={"label": "z-score (across clusters)", "shrink": 0.7},
    )
    ax_cta.set_xlabel("")
    ax_cta.set_ylabel("")
    ax_cta.tick_params(axis="x", labelsize=9, rotation=40)
    plt.setp(ax_cta.get_xticklabels(), ha="right")
    ax_cta.tick_params(axis="y", labelsize=9, rotation=0)
    for tick, color in zip(ax_cta.get_yticklabels(), row_colors):
        tick.set_color(color)
        tick.set_fontweight("bold")
    ax_cta.set_title("CTA genes  (annotated = cluster-mean log2 CPM+1)", fontsize=9, pad=8)

    # RCOR2 — raw means, separate scale
    sns.heatmap(
        ctx_raw,
        ax=ax_ctx,
        cmap="YlOrRd",
        annot=ctx_raw.round(1),
        fmt=".1f",
        annot_kws={"size": 9},
        linewidths=0.5,
        linecolor="#e0e0e0",
        yticklabels=False,
        xticklabels=available_ctx,
        cbar_kws={"label": "log2(CPM+1)", "shrink": 0.7},
    )
    ax_ctx.set_xlabel("")
    ax_ctx.set_ylabel("")
    ax_ctx.tick_params(axis="x", labelsize=9, rotation=0)
    ax_ctx.set_title("RCOR2\n(pan-cluster)", fontsize=9, pad=8)

    plt.savefig(OUT_HEATMAP, dpi=130, bbox_inches="tight")
    print(f"Saved: {OUT_HEATMAP}")

    # Console summary
    print("\n=== Mean raw expression by cluster ===")
    print(raw_means.round(3).to_string())
    print("\n=== Z-score across clusters (CTA genes) ===")
    print(cta_z.round(2).to_string())

    # --- Strip plot: all 91 samples ---
    plot_strips(plot_data, available_cta, cluster_series)


def pval_to_stars(p: float) -> str:
    if p < 0.001:
        return "***"
    elif p < 0.01:
        return "**"
    elif p < 0.05:
        return "*"
    return "ns"


def plot_strips(plot_data, genes, cluster_series):
    """2×4 grid — boxplot + strip overlay, Mann-Whitney brackets C1 vs each cluster."""
    short_labels = {
        "C1_highHRD_poorSurv":              "C1\nCTA",
        "C2_highMortality_Fibroblastic":    "C2\nImmune",
        "C3_lowHRD_goodSurv":              "C3\nStromal",
        "C4_highHRD_bestSurv_Osteoblastic": "C4\nOsteo.",
    }
    long = (
        plot_data[genes + ["cluster"]]
        .melt(id_vars=["cluster"], var_name="gene", value_name="expr", ignore_index=False)
        .reset_index(drop=True)
    )
    long["cluster_label"] = long["cluster"].map(short_labels)
    cl_label_order = [short_labels[c] for c in CLUSTER_ORDER]
    palette = {short_labels[k]: v for k, v in CLUSTER_COLORS.items()}

    c1_label = short_labels["C1_highHRD_poorSurv"]
    other_labels = [short_labels[c] for c in CLUSTER_ORDER if c != "C1_highHRD_poorSurv"]
    pairs = [(c1_label, other) for other in other_labels]

    ncols, nrows = 4, 2
    fig, axes = plt.subplots(nrows, ncols, figsize=(15, 9), sharey=False)
    fig.suptitle(
        "CTA marker expression — all 91 samples  (G2 s0, run 47941195)\n"
        "Mann-Whitney U: C1 vs each cluster   ns / * p<0.05 / ** p<0.01 / *** p<0.001 / **** p<0.0001",
        fontsize=10, y=1.01,
    )

    for ax, gene in zip(axes.flat, genes):
        sub = long[long["gene"] == gene].copy()

        # Clip y display at 99th percentile so the bracket zone isn't squeezed.
        # Outliers above the clip still get drawn by stripplot — just sets the axis limit.
        p99 = sub["expr"].quantile(0.99)
        y_top_data = max(p99, sub["expr"].median() * 3, 0.05)

        # Thin boxplot (no fliers — strips show all points)
        sns.boxplot(
            data=sub, x="cluster_label", y="expr",
            order=cl_label_order,
            palette=palette,
            width=0.45,
            fliersize=0,
            linewidth=0.8,
            boxprops=dict(alpha=0.25),
            whiskerprops=dict(linewidth=0.8),
            medianprops=dict(color="black", linewidth=1.5),
            capprops=dict(linewidth=0.8),
            ax=ax,
        )
        # Strip overlay
        sns.stripplot(
            data=sub, x="cluster_label", y="expr",
            order=cl_label_order,
            palette=palette,
            size=3.5, jitter=True, alpha=0.7,
            ax=ax,
        )

        # Pre-expand y-axis so brackets stack cleanly above the data cloud
        ax.set_ylim(-y_top_data * 0.05, y_top_data * 2.8)

        # Significance brackets
        annotator = Annotator(
            ax, pairs,
            data=sub, x="cluster_label", y="expr",
            order=cl_label_order,
        )
        annotator.configure(
            test="Mann-Whitney",
            text_format="star",
            loc="outside",
            line_height=0.01,
            line_width=0.8,
            text_offset=1,
            fontsize=8,
            comparisons_correction=None,
            verbose=0,
        )
        annotator.apply_and_annotate()

        # Gene name inside the panel (top-left), clear of brackets
        ax.text(
            0.03, 0.97, gene,
            transform=ax.transAxes,
            fontsize=9, fontweight="bold",
            va="top", ha="left",
        )
        ax.set_title("")
        ax.set_xlabel("")
        ax.set_ylabel("log2(CPM+1)" if ax in axes[:, 0] else "")
        ax.tick_params(axis="x", labelsize=7)
        ax.tick_params(axis="y", labelsize=8)
        legend = ax.get_legend()
        if legend:
            legend.remove()
        ax.spines[["top", "right"]].set_visible(False)

    for ax in axes.flat[len(genes):]:
        ax.set_visible(False)

    plt.tight_layout()
    plt.savefig(OUT_STRIPS, dpi=130, bbox_inches="tight")
    print(f"Saved: {OUT_STRIPS}")


if __name__ == "__main__":
    main()
