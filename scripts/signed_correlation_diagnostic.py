"""
Signed-correlation diagnostic — does the agent's signature direction flip in TARGET-OS?

For each run9 episode:
  1. Extract submitted top_genes.
  2. Infer protective/risk direction from SGH-OS univariate Cox (the same way
     target_survival_replication does it).
  3. Build signature score in TARGET-OS = mean(z protective) − mean(z risk).
     Sign convention: high signature = better survival expected.
  4. Spearman-correlate the signature against TARGET-OS OS time (longer = better).
     Positive ρ → signature direction replicates (high score → longer survival).
     Negative ρ → signature direction FLIPS in TARGET-OS (overfitting hypothesis).
     ρ ≈ 0 → noise (narrow-variance / biology-differs hypotheses).

Decision rule (from reviewer):
  Across run9 episodes, is the mean ρ centered at <0, =0, or >0?
    <0  → hypothesis (1) overfitting SGH-OS directionality confirmed.
          Prompt edit (leave-deciles-out robustness check in Stage 3) worth adding.
    ~0  → narrow signal / no replication; leave-deciles-out won't help.
    >0  → signatures actually do replicate at the signed-correlation level —
          target_survival_replication's gate is hiding partial signal.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

sys.path.insert(0, str(Path(__file__).parent.parent))

from biodiscoverygym.scoring.components_os import (
    _build_survival_df,
    _infer_sgh_directions,
    _load_target,
    _load_target_os_survival,
)
from biodiscoverygym.utils.data_loader import DataLoader
from biodiscoverygym.utils.hidden_context import DataAnonymizer


RUN_DIR = Path("results/external/run9_marker")  # override via --run-dir
OS_DATA_DIR = Path("data/external/os_jia2022")
TARGET_DIR = Path("data/external/TARGET")
DEFAULT_OUT = Path("analysis/run9_target_validation/signed_correlation.tsv")


def _zmean(df: pd.DataFrame, genes: list[str]) -> pd.Series:
    present = [g for g in genes if g in df.columns]
    if not present:
        return pd.Series(0.0, index=df.index)
    z = (df[present] - df[present].mean()) / df[present].std(ddof=0).replace(0, 1)
    return z.mean(axis=1)


def load_sgh():
    loader = DataLoader(Path("data"))
    ds = loader.load_tcga("OS", tcga_dir=OS_DATA_DIR)
    ds = DataAnonymizer.mask(ds)
    return ds["expression"], ds["metadata"]


def iter_episode_files() -> list[Path]:
    """Find all run9 episode JSONs."""
    out = []
    for p in RUN_DIR.glob("*/*.json"):
        if any(skip in p.name for skip in
               ("scores", "trace", "grouping", "codebook", "gene_map", "sample_codebook")):
            continue
        out.append(p)
    return sorted(out)


def parse_args():
    import argparse
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--run-dir", default=str(RUN_DIR),
                   help="Directory containing episode JSONs (default: results/external/run9_marker)")
    p.add_argument("--out", default=str(DEFAULT_OUT),
                   help="Output TSV path (default: analysis/run9_target_validation/signed_correlation.tsv)")
    return p.parse_args()


def main():
    args = parse_args()
    global RUN_DIR
    RUN_DIR = Path(args.run_dir)
    out_path = Path(args.out)
    print("Loading SGH-OS + TARGET-OS...")
    sgh_expr, sgh_meta = load_sgh()
    target = _load_target(TARGET_DIR)
    if target is None:
        print("ERROR: TARGET data not loadable", file=sys.stderr); sys.exit(1)
    target_os, _ = target
    surv = _load_target_os_survival(TARGET_DIR)
    if surv is None:
        print("ERROR: TARGET-OS survival not loadable", file=sys.stderr); sys.exit(1)
    common = target_os.index.intersection(surv.index)
    target_os = target_os.loc[common]
    target_surv = surv.loc[common]
    print(f"  SGH-OS: {len(sgh_expr)}, TARGET-OS w/ survival: {len(common)}")

    sgh_surv_df = _build_survival_df(sgh_meta)

    rows = []
    for ep_path in iter_episode_files():
        try:
            ep = json.loads(ep_path.read_text())
        except Exception as e:
            print(f"  skip {ep_path.name}: {e}", file=sys.stderr); continue
        top_genes = (ep.get("discovery") or {}).get("top_genes", []) or []
        if not top_genes:
            continue
        # 1+2. Infer directions in SGH-OS
        directions = _infer_sgh_directions(top_genes, sgh_expr, sgh_surv_df)
        valid = [g for g in directions if g in target_os.columns]
        if len(valid) < 2:
            rows.append({
                "episode": ep_path.stem, "n_top_genes": len(top_genes),
                "n_with_direction_and_target_expr": len(valid),
                "rho_signature_vs_OS_time": np.nan,
                "rho_p": np.nan, "n_protective": 0, "n_risk": 0,
                "note": "too few genes with direction + TARGET expression",
            })
            continue
        prot = [g for g in valid if directions[g] > 0]
        risk = [g for g in valid if directions[g] < 0]

        # 3. Signature score in TARGET-OS: high = good survival expected
        sig = _zmean(target_os, prot) - (_zmean(target_os, risk) if risk else 0.0)

        # 4. Spearman with OS time (longer T = better survival)
        rho, p = spearmanr(sig.values, target_surv["T"].values)
        rows.append({
            "episode": ep_path.stem,
            "n_top_genes": len(top_genes),
            "n_with_direction_and_target_expr": len(valid),
            "n_protective": len(prot), "n_risk": len(risk),
            "rho_signature_vs_OS_time": float(rho),
            "rho_p": float(p),
            "interpretation": (
                "replicates"     if rho > 0.15 else
                "flips"          if rho < -0.15 else
                "near-zero"
            ),
        })

    df = pd.DataFrame(rows)
    print(f"\nLoaded {len(df)} episodes\n")
    print("Per-episode signed correlation of signature ↔ OS_time (positive = replicates):")
    cols = ["episode", "n_top_genes", "n_protective", "n_risk",
            "rho_signature_vs_OS_time", "rho_p", "interpretation"]
    print(df[cols].to_string(index=False))

    valid = df["rho_signature_vs_OS_time"].dropna()
    print(f"\n{'='*64}")
    print(f"  Distribution of signed ρ across {len(valid)} episodes")
    print(f"{'='*64}")
    print(f"  mean   ρ = {valid.mean():+.4f}")
    print(f"  median ρ = {valid.median():+.4f}")
    print(f"  SD       = {valid.std():.4f}")
    print(f"  range    = [{valid.min():+.3f}, {valid.max():+.3f}]")

    # One-sample test against ρ=0
    from scipy.stats import wilcoxon
    try:
        w_stat, w_p = wilcoxon(valid.values)
        print(f"  Wilcoxon signed-rank vs 0: stat={w_stat:.2f}, p={w_p:.4f}")
    except Exception:
        pass

    # Verdict per reviewer's decision rule
    print(f"\n{'='*64}")
    print(f"  Verdict")
    print(f"{'='*64}")
    mean_rho = valid.mean()
    if mean_rho < -0.10:
        print(f"  ρ centered at {mean_rho:+.3f} (< -0.10):")
        print("  → Hypothesis (1) CONFIRMED: signatures systematically flip direction")
        print("    in TARGET-OS. The agent's gene picks are anti-correlated with")
        print("    the held-out truth. This is direction overfitting to SGH-OS.")
        print("  → Reviewer's Read B (leave-deciles-out robustness check) WORTH ADDING.")
    elif mean_rho > 0.10:
        print(f"  ρ centered at {mean_rho:+.3f} (> +0.10):")
        print("  → Signatures actually replicate at the signed-correlation level.")
        print("    target_survival_replication's direction-as-gate may be hiding")
        print("    partial signal in low-magnitude cases.")
    else:
        print(f"  ρ centered at {mean_rho:+.3f} (within [-0.10, +0.10]):")
        print("  → No directional replication AND no systematic flip — signatures")
        print("    are just noise in TARGET-OS. Hypothesis (2) narrow variance or")
        print("    (3) biology differs.")
        print("  → Reviewer's Read A (accept and ship). A robustness filter can't")
        print("    rescue what is fundamentally weak signal.")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out_path, sep="\t", index=False)
    print(f"\nSaved per-episode table → {out_path}")


if __name__ == "__main__":
    main()
