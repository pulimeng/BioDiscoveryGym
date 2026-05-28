"""
SP7 promoter methylation landscape — SGH-OS cohort (Jia et al. 2022)
Heatmap of the top CpGs anti-correlated with SP7 expression,
samples sorted by cluster (C1→C4), with per-CpG Spearman r annotation.

Run from repo root:
    conda run -n biodiscoverygym python analysis/sp7_promoter_landscape.py
"""

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
from matplotlib.colors import LinearSegmentedColormap
from scipy.stats import spearmanr

# ── paths ──────────────────────────────────────────────────────────────────
RAW_DIR = "data/external/os_jia2022"
OUT     = "analysis/sp7_promoter_landscape.png"
R_CUTOFF = -0.70          # keep only CpGs with r < this threshold

# ── load ───────────────────────────────────────────────────────────────────
meth = pd.read_parquet(f"{RAW_DIR}/methylation.parquet")
expr = pd.read_parquet(f"{RAW_DIR}/expression.parquet")
clin = pd.read_csv(f"{RAW_DIR}/OS_clinical.tsv", sep="\t", index_col=0)

common = meth.index.intersection(expr.index).intersection(clin.index)
meth, expr, clin = meth.loc[common], expr.loc[common], clin.loc[common]
sp7 = expr["SP7"].values

# ── find top SP7-correlated CpGs ───────────────────────────────────────────
corrs = {cpg: spearmanr(meth[cpg].values, sp7) for cpg in meth.columns}
cpg_df = pd.DataFrame(
    [(cpg, v.statistic, v.pvalue) for cpg, v in corrs.items()],
    columns=["cpg", "r", "p"]
).sort_values("r")

top_cpgs = cpg_df[cpg_df["r"] < R_CUTOFF]["cpg"].tolist()
print(f"CpGs with r < {R_CUTOFF}: {len(top_cpgs)}")

# ── sort samples: C1 → C4, within cluster by SP7 expression ───────────────
CLUSTER_ORDER = [1, 2, 3, 4]
CLUSTER_MAP   = {1: "C1 Proliferative", 2: "C2 Myeloid-Inflamed",
                 3: "C3 Vascular-Stromal", 4: "C4 Osteoblastic"}
COLOURS       = {1: "#3498db", 2: "#e74c3c", 3: "#9b59b6", 4: "#2ecc71"}

sample_order = []
for c in CLUSTER_ORDER:
    idx = clin[clin["mrna_cluster"] == c].index
    idx_sorted = idx[np.argsort(expr.loc[idx, "SP7"].values)]
    sample_order.extend(idx_sorted.tolist())

# ── build heatmap matrix ───────────────────────────────────────────────────
heatmap = meth.loc[sample_order, top_cpgs].T   # CpGs × samples

# ── per-CpG cluster means for annotation ──────────────────────────────────
cluster_means = {}
for c in CLUSTER_ORDER:
    idx = clin[clin["mrna_cluster"] == c].index
    cluster_means[c] = meth.loc[idx, top_cpgs].mean()

# ── plot ───────────────────────────────────────────────────────────────────
n_cpg = len(top_cpgs)
fig = plt.figure(figsize=(14, max(6, n_cpg * 0.28 + 2)))

gs = gridspec.GridSpec(
    3, 2,
    height_ratios=[0.35, n_cpg * 0.28, 0.8],
    width_ratios=[1, 0.18],
    hspace=0.04, wspace=0.03,
)

ax_bar   = fig.add_subplot(gs[0, 0])   # cluster colour bar
ax_heat  = fig.add_subplot(gs[1, 0])   # heatmap
ax_sp7   = fig.add_subplot(gs[2, 0])   # SP7 expression strip
ax_means = fig.add_subplot(gs[1, 1])   # per-cluster mean betas
ax_cbar  = fig.add_subplot(gs[2, 1])   # colorbar

# ── cluster colour bar ─────────────────────────────────────────────────────
bar_colours = [COLOURS[clin.loc[s, "mrna_cluster"]] for s in sample_order]
for xi, col in enumerate(bar_colours):
    ax_bar.add_patch(plt.Rectangle((xi, 0), 1, 1, color=col, lw=0))

# cluster labels centred
pos = 0
for c in CLUSTER_ORDER:
    n = (clin["mrna_cluster"] == c).sum()
    ax_bar.text(pos + n / 2, 1.35, CLUSTER_MAP[c],
                ha="center", va="bottom", fontsize=8.5,
                fontweight="bold", color=COLOURS[c])
    ax_bar.axvline(pos, color="white", lw=1.5)
    pos += n

ax_bar.set_xlim(0, len(sample_order))
ax_bar.set_ylim(0, 1)
ax_bar.axis("off")

# ── heatmap ────────────────────────────────────────────────────────────────
cmap = LinearSegmentedColormap.from_list(
    "meth", ["#2166ac", "#f7f7f7", "#d6604d"], N=256
)
im = ax_heat.imshow(
    heatmap.values, aspect="auto", cmap=cmap,
    vmin=0, vmax=1, interpolation="nearest",
)

ax_heat.set_yticks(range(n_cpg))
# All 45 CpGs are used in Panel B composite — all get arrows
ax_heat.set_yticklabels(
    [f"→ {cpg}  (r={corrs[cpg].statistic:.2f})" for cpg in top_cpgs],
    fontsize=7.5, family="monospace",
)
# Colour labels by correlation strength:
#   r < -0.73  → dark red  (strongest)
#   -0.73–-0.71 → orange
#   r >= -0.71 → steel blue
TIER_COLOURS = {
    "strong":   "#c0392b",   # dark red
    "moderate": "#e67e22",   # orange
    "weak":     "#2980b9",   # steel blue
}
labels = ax_heat.get_yticklabels()
for i, cpg in enumerate(top_cpgs):
    r_val = corrs[cpg].statistic
    if r_val < -0.73:
        col = TIER_COLOURS["strong"]
    elif r_val < -0.71:
        col = TIER_COLOURS["moderate"]
    else:
        col = TIER_COLOURS["weak"]
    labels[i].set_color(col)
    if cpg == "cg15311685":
        labels[i].set_fontweight("bold")
        labels[i].set_color(TIER_COLOURS["strong"])

ax_heat.set_xticks([])
ax_heat.set_xlabel("")

# tier legend (top-right corner of heatmap)
import matplotlib.patches as mpatches
tier_patches = [
    mpatches.Patch(color=TIER_COLOURS["strong"],   label="r < −0.73"),
    mpatches.Patch(color=TIER_COLOURS["moderate"], label="−0.73 ≤ r < −0.71"),
    mpatches.Patch(color=TIER_COLOURS["weak"],     label="−0.71 ≤ r < −0.70"),
]
ax_heat.legend(handles=tier_patches, title="→ chosen for Panel B composite",
               title_fontsize=6.5, fontsize=6.5, loc="lower right",
               framealpha=0.85, borderpad=0.5, handlelength=1.0)

# cluster dividers
pos = 0
for c in CLUSTER_ORDER[:-1]:
    pos += (clin["mrna_cluster"] == c).sum()
    ax_heat.axvline(pos - 0.5, color="white", lw=1.5)

# colorbar — placed in bottom-right cell
cbar = fig.colorbar(im, cax=ax_cbar, orientation="vertical")
cbar.set_label("Methylation β", fontsize=8)
cbar.ax.tick_params(labelsize=7)

# ── SP7 expression strip ───────────────────────────────────────────────────
sp7_vals = expr.loc[sample_order, "SP7"].values
ax_sp7.bar(range(len(sample_order)), sp7_vals,
           color=bar_colours, width=1.0, linewidth=0)
pos = 0
for c in CLUSTER_ORDER[:-1]:
    pos += (clin["mrna_cluster"] == c).sum()
    ax_sp7.axvline(pos - 0.5, color="white", lw=1.5)
ax_sp7.set_xlim(0, len(sample_order))
ax_sp7.set_ylabel("SP7 expr\n(log₂ CPM+1)", fontsize=8)
ax_sp7.set_xticks([])
ax_sp7.spines[["top", "right", "bottom"]].set_visible(False)

# ── per-cluster mean betas (dot plot) ─────────────────────────────────────
mean_mat = np.array([[cluster_means[c][cpg] for c in CLUSTER_ORDER]
                     for cpg in top_cpgs])

ax_means.imshow(mean_mat, aspect="auto", cmap=cmap, vmin=0, vmax=1,
                interpolation="nearest")
ax_means.set_xticks(range(len(CLUSTER_ORDER)))
ax_means.set_xticklabels([f"C{c}" for c in CLUSTER_ORDER],
                          fontsize=8, rotation=45, ha="right")
ax_means.set_yticks([])
ax_means.set_title("")

# annotate mean values
for ri in range(n_cpg):
    for ci, c in enumerate(CLUSTER_ORDER):
        val = mean_mat[ri, ci]
        ax_means.text(ci, ri, f"{val:.2f}", ha="center", va="center",
                      fontsize=6.5,
                      color="white" if (val < 0.25 or val > 0.75) else "black")

plt.savefig(OUT, dpi=150, bbox_inches="tight")
print(f"Saved → {OUT}")
