"""
SP7 / cg15311685 scatter plots — run3_methy deep dive
Uses raw (non-anonymized) OS Jia 2022 data.

Produces a 3-panel figure:
  Panel A: cg15311685 beta vs SP7 expression, points coloured by cluster
  Panel B: cg15311685 beta distribution per cluster (box + strip)
  Panel C: SP7 expression distribution per cluster (box + strip)

Run from repo root:
    conda run -n biodiscoverygym python analysis/sp7_cg15311685_scatter.py
"""

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.patches import Ellipse
import matplotlib.transforms as transforms
from scipy.stats import spearmanr, chi2

# ── paths ──────────────────────────────────────────────────────────────────
RAW_DIR = "data/external/os_jia2022"
OUT     = "analysis/sp7_cg15311685_scatter.png"
CPG     = "cg15311685"
ADJ_CPG = "cg04248332"   # adjacent SP7 probe found by G0 s7

# ── load raw data ──────────────────────────────────────────────────────────
meth = pd.read_parquet(f"{RAW_DIR}/methylation.parquet")
expr = pd.read_parquet(f"{RAW_DIR}/expression.parquet")
clin = pd.read_csv(f"{RAW_DIR}/OS_clinical.tsv", sep="\t", index_col=0)

common = meth.index.intersection(expr.index).intersection(clin.index)
meth, expr, clin = meth.loc[common], expr.loc[common], clin.loc[common]

# ── cluster mapping ────────────────────────────────────────────────────────
# mrna_cluster numbers match the agent's partition (confirmed by beta/expression values)
CLUSTER_MAP = {
    4: "C4 Osteoblastic",       # best prognosis, low methylation
    1: "C1 Proliferative",
    3: "C3 Vascular-Stromal",
    2: "C2 Myeloid-Inflamed",   # worst prognosis, high methylation
}
CLUSTER_ORDER = [4, 1, 3, 2]   # best → worst prognosis (used in scatter)
BOX_ORDER     = [1, 2, 3, 4]   # numeric order for box plots
COLOURS = {
    4: "#2ecc71",   # green  – best prognosis
    1: "#3498db",   # blue
    3: "#9b59b6",   # purple
    2: "#e74c3c",   # red    – worst prognosis
}

surv_time = np.where(clin["vital_status"] == "Dead",
                     clin["days_to_death"],
                     clin["days_to_last_follow_up"]).astype(float)
event = (clin["vital_status"] == "Dead").astype(int)

# ── composite SP7-promoter methylation score ───────────────────────────────
# Use all CpGs with Spearman r < -0.70 vs SP7 expression (same threshold as
# the landscape figure) to build a robust multi-CpG score
sp7_vals_all = expr["SP7"].values
_corrs = {cpg: spearmanr(meth[cpg].values, sp7_vals_all).statistic
          for cpg in meth.columns}
LANDSCAPE_CPGS = [cpg for cpg, r in _corrs.items() if r < -0.70]
print(f"Composite score CpGs (r < -0.70): {len(LANDSCAPE_CPGS)}")
composite_score = meth[LANDSCAPE_CPGS].mean(axis=1)   # mean beta across landscape

df = pd.DataFrame({
    "cluster":   clin["mrna_cluster"],
    "meth_cg15": meth[CPG],
    "meth_cg04": meth[ADJ_CPG],
    "sp7_expr":  expr["SP7"],
    "composite": composite_score,
    "surv_time": surv_time,
    "event":     event,
}, index=common)

# ── statistics ─────────────────────────────────────────────────────────────
r_cg15, p_cg15 = spearmanr(df["meth_cg15"], df["sp7_expr"])
r_cg04, p_cg04 = spearmanr(df["meth_cg04"], df["sp7_expr"])

print("Per-cluster statistics:")
print(f"{'Cluster':<22} {'n':>3}  {'beta mean':>9}  {'beta SD':>7}  {'SP7 mean':>8}  {'SP7 SD':>6}")
for c in CLUSTER_ORDER:
    sub = df[df["cluster"] == c]
    print(f"{CLUSTER_MAP[c]:<22} {len(sub):>3}  "
          f"{sub['meth_cg15'].mean():>9.3f}  {sub['meth_cg15'].std():>7.3f}  "
          f"{sub['sp7_expr'].mean():>8.2f}  {sub['sp7_expr'].std():>6.2f}")

print(f"\ncg15311685 × SP7:  r = {r_cg15:.3f},  p = {p_cg15:.2e}")
print(f"cg04248332 × SP7:  r = {r_cg04:.3f},  p = {p_cg04:.2e}")

# ── figure ─────────────────────────────────────────────────────────────────
# ── KM helpers ────────────────────────────────────────────────────────────
def kaplan_meier(time, event):
    time, event = np.array(time), np.array(event)
    event_times = np.sort(np.unique(time[event == 1]))
    t_pts, S = [0], [1.0]
    for t in event_times:
        at_risk = np.sum(time >= t)
        deaths  = np.sum((time == t) & (event == 1))
        S.append(S[-1] * (1 - deaths / at_risk))
        t_pts.append(t)
    # extend to max follow-up for step plot
    t_pts.append(time.max()); S.append(S[-1])
    return np.array(t_pts), np.array(S)

def logrank_p(t1, e1, t2, e2):
    t1, e1, t2, e2 = map(np.array, (t1, e1, t2, e2))
    event_times = np.sort(np.unique(np.concatenate([t1[e1==1], t2[e2==1]])))
    O1 = E1 = V = 0.0
    for t in event_times:
        n1 = np.sum(t1 >= t); n2 = np.sum(t2 >= t); n = n1 + n2
        d1 = np.sum((t1 == t) & (e1 == 1))
        d2 = np.sum((t2 == t) & (e2 == 1)); d = d1 + d2
        if n < 2: continue
        O1 += d1;  E1 += n1 * d / n
        if n > 1 and d < n:
            V += n1 * n2 * d * (n - d) / (n**2 * (n - 1))
    stat = (O1 - E1)**2 / V if V > 0 else 0
    return float(1 - chi2.cdf(stat, df=1))

fig, axes = plt.subplots(2, 2, figsize=(13, 10))
fig.suptitle(
    "SP7 promoter methylation (cg15311685) — SGH-OS cohort (Jia et al. 2022, n=91)",
    fontsize=12, fontweight="bold",
)
axes = axes.flatten()

# ── Panel A: scatter with confidence ellipses + per-cluster stats ──────────
ax = axes[0]

MARKERS = {4: "o", 1: "s", 3: "^", 2: "D"}   # distinct shape per cluster

def confidence_ellipse(x, y, ax, n_std=1.5, **kwargs):
    """Draw a covariance-based confidence ellipse for points (x, y)."""
    if len(x) < 3:
        return
    cov = np.cov(x, y)
    pearson = cov[0, 1] / (np.sqrt(cov[0, 0]) * np.sqrt(cov[1, 1]) + 1e-9)
    rx = np.sqrt(1 + pearson)
    ry = np.sqrt(1 - pearson)
    ellipse = Ellipse((0, 0), width=rx * 2, height=ry * 2, **kwargs)
    scale_x = np.sqrt(cov[0, 0]) * n_std
    scale_y = np.sqrt(cov[1, 1]) * n_std
    t = transforms.Affine2D() \
        .rotate_deg(45) \
        .scale(scale_x, scale_y) \
        .translate(np.mean(x), np.mean(y))
    ellipse.set_transform(t + ax.transData)
    ax.add_patch(ellipse)

for c in CLUSTER_ORDER:
    sub = df[df["cluster"] == c]
    x_c, y_c = sub["meth_cg15"].values, sub["sp7_expr"].values
    r_c, p_c = spearmanr(x_c, y_c)
    label = f"{CLUSTER_MAP[c]}  (r={r_c:.2f})"

    # confidence ellipse (1.5 SD)
    confidence_ellipse(x_c, y_c, ax,
                       facecolor=COLOURS[c], alpha=0.12,
                       edgecolor=COLOURS[c], linewidth=1.4, linestyle="--", zorder=2)

    # scatter points
    ax.scatter(x_c, y_c, c=COLOURS[c], marker=MARKERS[c],
               s=60, alpha=0.85, edgecolors="white", linewidths=0.5,
               zorder=4, label=label)

    # centroid label
    ax.annotate(
        CLUSTER_MAP[c].split()[0] + " " + CLUSTER_MAP[c].split()[1],
        xy=(np.mean(x_c), np.mean(y_c)),
        fontsize=7.5, fontweight="bold", color=COLOURS[c],
        ha="center", va="center",
        bbox=dict(boxstyle="round,pad=0.2", fc="white", ec=COLOURS[c],
                  alpha=0.75, linewidth=0.8),
        zorder=5,
    )

# overall regression line
x_all = df["meth_cg15"].values
y_all = df["sp7_expr"].values
m, b = np.polyfit(x_all, y_all, 1)
xline = np.linspace(x_all.min() - 0.02, x_all.max() + 0.02, 100)
ax.plot(xline, m * xline + b, color="black", lw=1.3, linestyle="-", alpha=0.35, zorder=1)

ax.set_xlabel("cg15311685 methylation (β)", fontsize=11)
ax.set_ylabel("SP7 expression (log₂ CPM+1)", fontsize=11)
ax.legend(fontsize=8, loc="upper right", framealpha=0.88,
          title="cluster (per-cluster r)", title_fontsize=7.5)
ax.spines[["top", "right"]].set_visible(False)
ax.text(-0.12, 1.05, "A", transform=ax.transAxes,
        fontsize=14, fontweight="bold", va="top", ha="left")

# ── Panel B: KM — composite SP7-promoter methylation score, median split ──
ax = axes[1]

# 2D absolute-value threshold: composite β < 0.60 AND SP7 > 7.0
# Both cutoffs are absolute measurements — apply to any new patient directly
BETA_CUT = 0.40
SP7_CUT  = 6.5
mask_low_meth  = (df["composite"] < BETA_CUT) & (df["sp7_expr"] > SP7_CUT)
mask_high_meth = (df["composite"] > BETA_CUT) & (df["sp7_expr"] < SP7_CUT)
# unclassified patients (neither condition) are excluded from KM

km_groups = [
    (mask_low_meth,  f"SP7 active  (β<{BETA_CUT}, SP7>{SP7_CUT})",    COLOURS[4]),
    (mask_high_meth, f"SP7 silenced (β>{BETA_CUT}, SP7<{SP7_CUT})", COLOURS[2]),
]

for mask, label, col in km_groups:
    t = df.loc[mask, "surv_time"].values
    e = df.loc[mask, "event"].values
    t_pts, S = kaplan_meier(t, e)
    n_dead  = int(e.sum())
    n_alive = len(t) - n_dead
    ax.step(t_pts / 365.25, S, where="post", color=col, lw=2.5,
            label=f"{label}\nn={len(t)}  ({n_dead} events)")
    cens_t = t[e == 0] / 365.25
    cens_S = [S[np.searchsorted(t_pts, ct * 365.25, side="right") - 1] for ct in cens_t]
    ax.scatter(cens_t, cens_S, marker="|", s=55, color=col, zorder=5, linewidth=1.5)
    med_idx = np.searchsorted(-np.array(S), -0.5)
    if med_idx < len(t_pts):
        med_yr = t_pts[med_idx] / 365.25
        ax.plot([0, med_yr], [0.5, 0.5], color=col, lw=0.8, linestyle=":", alpha=0.5)
        ax.plot([med_yr, med_yr], [0, 0.5], color=col, lw=0.8, linestyle=":", alpha=0.5)
        ax.text(med_yr, -0.03, f"{med_yr:.1f}yr", ha="center", va="top",
                fontsize=8, color=col, fontweight="bold")

p_val = logrank_p(df.loc[mask_low_meth,  "surv_time"].values, df.loc[mask_low_meth,  "event"].values,
                  df.loc[mask_high_meth, "surv_time"].values, df.loc[mask_high_meth, "event"].values)
p_str = f"p = {p_val:.3f}" if p_val >= 0.001 else f"p = {p_val:.2e}"
n_lo = mask_low_meth.sum(); n_hi = mask_high_meth.sum()
n_excl = (~mask_low_meth & ~mask_high_meth).sum()
ax.text(0.97, 0.97,
        f"Log-rank  {p_str}\nComposite β / SP7 expression threshold\n(n={n_lo} vs n={n_hi}, {n_excl} unclassified excluded)",
        transform=ax.transAxes, ha="right", va="top", fontsize=8.5,
        bbox=dict(boxstyle="round,pad=0.35", fc="white", ec="#bbb", alpha=0.9))

ax.axhline(0.5, color="#ccc", lw=0.8, linestyle="--", zorder=0)
ax.set_xlabel("Time (years)", fontsize=11)
ax.set_ylabel("Overall survival probability", fontsize=11)
ax.set_ylim(-0.04, 1.06)
ax.legend(fontsize=8.5, loc="lower left", framealpha=0.88)
ax.spines[["top", "right"]].set_visible(False)
ax.text(-0.12, 1.05, "B", transform=ax.transAxes,
        fontsize=14, fontweight="bold", va="top", ha="left")

# ── Panel C: cg15311685 beta by cluster (C1→C4) ───────────────────────────
ax = axes[2]
rng = np.random.default_rng(42)
for i, c in enumerate(BOX_ORDER):
    sub = df[df["cluster"] == c]["meth_cg15"].values
    ax.boxplot(
        sub, positions=[i], widths=0.52,
        patch_artist=True,
        boxprops=dict(facecolor=COLOURS[c], alpha=0.40),
        medianprops=dict(color="black", linewidth=2.0),
        whiskerprops=dict(color="#555", linewidth=1.0),
        capprops=dict(color="#555", linewidth=1.0),
        showfliers=False,
    )
    jitter = rng.uniform(-0.18, 0.18, len(sub))
    ax.scatter(np.full(len(sub), i) + jitter, sub,
               c=COLOURS[c], s=24, alpha=0.75, zorder=4,
               edgecolors="white", linewidths=0.35)

ax.axhline(0.5, color="#aaa", lw=1.0, linestyle=":", zorder=1)
ax.text(len(BOX_ORDER) - 0.05, 0.505, "β = 0.5", color="#aaa",
        fontsize=7.5, va="bottom", ha="right")
ax.set_xticks(range(len(BOX_ORDER)))
ax.set_xticklabels([CLUSTER_MAP[c] for c in BOX_ORDER], rotation=18, ha="right", fontsize=9)
ax.set_ylabel("cg15311685 methylation (β)", fontsize=11)
ax.spines[["top", "right"]].set_visible(False)
ax.text(-0.12, 1.05, "C", transform=ax.transAxes,
        fontsize=14, fontweight="bold", va="top", ha="left")

# ── Panel D: SP7 expression by cluster (C1→C4) ────────────────────────────
ax = axes[3]
rng = np.random.default_rng(42)
for i, c in enumerate(BOX_ORDER):
    sub = df[df["cluster"] == c]["sp7_expr"].values
    ax.boxplot(
        sub, positions=[i], widths=0.52,
        patch_artist=True,
        boxprops=dict(facecolor=COLOURS[c], alpha=0.40),
        medianprops=dict(color="black", linewidth=2.0),
        whiskerprops=dict(color="#555", linewidth=1.0),
        capprops=dict(color="#555", linewidth=1.0),
        showfliers=False,
    )
    jitter = rng.uniform(-0.18, 0.18, len(sub))
    ax.scatter(np.full(len(sub), i) + jitter, sub,
               c=COLOURS[c], s=24, alpha=0.75, zorder=4,
               edgecolors="white", linewidths=0.35)

ax.set_xticks(range(len(BOX_ORDER)))
ax.set_xticklabels([CLUSTER_MAP[c] for c in BOX_ORDER], rotation=18, ha="right", fontsize=9)
ax.set_ylabel("SP7 expression (log₂ CPM+1)", fontsize=11)
ax.spines[["top", "right"]].set_visible(False)
ax.text(-0.12, 1.05, "D", transform=ax.transAxes,
        fontsize=14, fontweight="bold", va="top", ha="left")

plt.tight_layout()
plt.savefig(OUT, dpi=150, bbox_inches="tight")
print(f"\nSaved → {OUT}")
