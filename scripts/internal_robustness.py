#!/usr/bin/env python3
"""Does INTERNAL robustness predict EXTERNAL replication?

THE QUESTION. The OS track's Phase 3 (TARGET-OS replication) is at the floor for nearly every
episode: signatures discovered in SGH-OS (n=91) do not carry prognostic information into
TARGET-OS. The proposed fix is an internal-robustness loop — have the agent iterate with
cross-validation and bootstrap stability on SGH-OS until its signature is internally stable,
then score TARGET once. That is only worth building if internal robustness actually PREDICTS
external replication. This script tests that on the episodes already on disk, before any new
episodes are run.

WHY IT MUST BE RETROSPECTIVE FIRST. If internal robustness does not correlate with external
replication in existing episodes, then an internal loop cannot rescue Phase 3 no matter how many
iterations the agent runs — it would just be selecting harder on a signal that does not transfer.
That is a cheap, decisive check.

WHAT IS COMPUTED, per episode:
  INTERNAL (SGH-OS only — what an agent could see while iterating)
    boot_sign_stability : bootstrap patients B times, refit univariate Cox per gene, fraction of
                          resamples where the gene keeps its full-data coefficient sign, averaged
                          over the signature's genes. "Would this direction call survive resampling?"
    cv_hr / cv_p        : K-fold cross-validated signature. Directions are inferred on the training
                          folds ONLY and the signature is evaluated on held-out patients, so this is
                          an honest internal estimate rather than the in-sample HR the agent reports.
    ldo_hr_sd           : leave-deciles-out stability — drop 10% of patients repeatedly, recompute
                          the in-sample signature HR, report its SD. Low SD = insensitive to which
                          patients are included.
  EXTERNAL (TARGET-OS — hidden from the agent)
    rho                 : signed Spearman of the signature vs OS time (from the existing
                          signed_correlation.tsv, the same convention Phase 3 uses)
    target_hr / target_p: univariate Cox of the signature in TARGET-OS

Then it correlates each internal metric against the external ones ACROSS episodes. A positive,
significant correlation means internal discipline buys external replication and the loop is worth
building; a null means it cannot.

Usage:
  python scripts/internal_robustness.py                      # both runs, B=200, K=5
  python scripts/internal_robustness.py --bootstrap 500
  python scripts/internal_robustness.py --out analysis/internal_robustness/metrics.tsv
"""
from __future__ import annotations

import argparse
import json
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

# Bootstrap resamples routinely produce separable / non-converging Cox fits; those are handled
# (the fit is skipped) and the warning would otherwise drown the per-episode progress lines.
warnings.filterwarnings("ignore", module="lifelines")

sys.path.insert(0, str(Path(__file__).parent.parent))

from biodiscoverygym.scoring.components_os import (  # noqa: E402
    _build_survival_df,
    _cox_univariate,
    _infer_sgh_directions,
    _load_target,
    _load_target_os_survival,
    _zmean,
)
from biodiscoverygym.utils.data_loader import DataLoader  # noqa: E402

RUN_DIRS = [Path("results/external/run9_marker"), Path("results/external/run10_withval")]
EXT_TSVS = [Path("analysis/run9_target_validation/signed_correlation.tsv"),
            Path("analysis/run10_target_validation/signed_correlation.tsv")]
OS_DATA_DIR = Path("data/external/os_jia2022")
TARGET_DIR = Path("data/external/TARGET")
DEFAULT_OUT = Path("analysis/internal_robustness/metrics.tsv")


# ---------------------------------------------------------------- episode loading
def iter_episodes(run_dirs: list[Path]) -> list[tuple[str, list[str]]]:
    """(episode_label, top_genes) for every episode with a submitted discovery."""
    out = []
    for rd in run_dirs:
        for ep_path in sorted(rd.glob("*/*.json")):
            if any(x in ep_path.name for x in ("scores", "trace", "summary", "codebook",
                                               "gene_map", "grouping", "report")):
                continue
            try:
                ep = json.loads(ep_path.read_text())
            except Exception:
                continue
            genes = (ep.get("discovery") or {}).get("top_genes", []) or []
            if genes:
                out.append((ep_path.stem, list(genes)))
    return out


def signature(expr: pd.DataFrame, directions: dict[str, int]) -> pd.Series:
    """Signature score: high = better survival expected. Mirrors the Phase 3 convention."""
    prot = [g for g, d in directions.items() if d > 0 and g in expr.columns]
    risk = [g for g, d in directions.items() if d < 0 and g in expr.columns]
    if not prot and not risk:
        return pd.Series(dtype=float)
    return _zmean(expr, prot) - (_zmean(expr, risk) if risk else 0.0)


# ---------------------------------------------------------------- internal metrics
def boot_sign_stability(genes, expr, surv, B, rng) -> float | None:
    """Fraction of bootstrap resamples in which each gene keeps its full-data Cox sign."""
    full = _infer_sgh_directions(genes, expr, surv)
    if not full:
        return None
    common = list(expr.index.intersection(surv.index))
    if len(common) < 20:
        return None
    keep = {g: 0 for g in full}
    done = 0
    for _ in range(B):
        samp = list(rng.choice(common, size=len(common), replace=True))
        # a bootstrap resample can drop all events; _infer_sgh_directions returns {} then
        d = _infer_sgh_directions(list(full), expr.loc[samp], surv.loc[samp])
        if not d:
            continue
        done += 1
        for g, s in full.items():
            if d.get(g) == s:
                keep[g] += 1
    if done == 0:
        return None
    return float(np.mean([keep[g] / done for g in full]))


def cv_signature(genes, expr, surv, K, rng) -> tuple[float | None, float | None]:
    """K-fold CV: infer directions on TRAIN folds only, score held-out patients.
    Honest internal estimate — the in-sample HR the agent sees is selection-inflated."""
    common = np.array(list(expr.index.intersection(surv.index)))
    if len(common) < 30:
        return None, None
    idx = rng.permutation(len(common))
    folds = np.array_split(idx, K)
    held = {}
    for k in range(K):
        te = common[folds[k]]
        tr = common[np.concatenate([folds[j] for j in range(K) if j != k])]
        d = _infer_sgh_directions(genes, expr.loc[tr], surv.loc[tr])
        if not d:
            continue
        sig = signature(expr.loc[te], d)
        for s, v in sig.items():
            held[s] = v
    if len(held) < 30:
        return None, None
    ser = pd.Series(held)
    res = _cox_univariate(surv.loc[ser.index].rename(columns={"duration": "T", "event": "E"}), ser)
    if res is None:
        return None, None
    return float(res["hr"]), float(res["p"])


def ldo_stability(genes, expr, surv, reps, rng) -> float | None:
    """Leave-deciles-out: SD of the in-sample signature HR when 10% of patients are dropped."""
    common = np.array(list(expr.index.intersection(surv.index)))
    if len(common) < 30:
        return None
    hrs = []
    for _ in range(reps):
        keep = rng.choice(common, size=int(round(len(common) * 0.9)), replace=False)
        d = _infer_sgh_directions(genes, expr.loc[keep], surv.loc[keep])
        if not d:
            continue
        sig = signature(expr.loc[keep], d)
        res = _cox_univariate(surv.loc[keep].rename(columns={"duration": "T", "event": "E"}), sig)
        if res is not None:
            hrs.append(np.log(res["hr"]))
    if len(hrs) < 5:
        return None
    return float(np.std(hrs, ddof=1))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--bootstrap", type=int, default=200, help="bootstrap resamples (default 200)")
    ap.add_argument("--folds", type=int, default=5, help="CV folds (default 5)")
    ap.add_argument("--ldo-reps", type=int, default=50, help="leave-deciles-out reps (default 50)")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--baselines", type=int, default=0, metavar="N",
                    help="also score N random-gene and N top-Cox baseline 'episodes'. The key "
                         "control: if a naive top-univariate-Cox pick looks as internally robust "
                         "as the agent's signature and fails externally the same way, then "
                         "internal robustness is measuring SELECTION, not truth.")
    args = ap.parse_args()
    rng = np.random.default_rng(args.seed)

    print("Loading SGH-OS …")
    # same entry point signed_correlation_diagnostic uses — SGH is loaded through the TCGA
    # reader with an explicit dir, not a bespoke loader
    ds = DataLoader(Path("data")).load_tcga("OS", tcga_dir=OS_DATA_DIR)
    expr, meta = ds["expression"], ds["metadata"]
    surv = _build_survival_df(meta)
    print(f"  expression {expr.shape}, survival n={len(surv)}, events={int(surv['event'].sum())}")

    print("Loading TARGET-OS …")
    tgt = _load_target(TARGET_DIR)
    tsurv = _load_target_os_survival(TARGET_DIR)
    if tgt is None or tsurv is None:
        print("  !! TARGET not loadable — external columns will be blank", file=sys.stderr)
        target_os = None
    else:
        target_os = tgt[0]
        common = target_os.index.intersection(tsurv.index)
        target_os, tsurv = target_os.loc[common], tsurv.loc[common]
        print(f"  TARGET-OS n={len(common)}, events={int(tsurv['E'].sum())}")

    # external rho from the existing diagnostic, keyed by episode stem
    ext = {}
    for p in EXT_TSVS:
        if p.exists():
            df = pd.read_csv(p, sep="\t")
            for _, r in df.iterrows():
                ext[str(r["episode"])] = float(r["rho_signature_vs_OS_time"])
    print(f"  external rho available for {len(ext)} episodes")

    eps = iter_episodes(RUN_DIRS)
    median_n = int(np.median([len(g) for _, g in eps])) if eps else 15

    # ---- baseline arms -------------------------------------------------------------------
    # Two naive pickers, sized like a real signature. If these match the agent's INTERNAL
    # robustness, that robustness is a property of survival-selection on n=91, not of the
    # agent's reasoning — and no amount of internal iterating can distinguish them.
    if args.baselines:
        genes_all = [g for g in expr.columns if expr[g].std() > 0]
        # (a) random genes — no survival information used at all
        for i in range(args.baselines):
            pick = list(rng.choice(genes_all, size=median_n, replace=False))
            eps.append((f"BASELINE_random_{i}", pick))
        # (b) top-N by univariate Cox p in SGH — the dumbest possible "discovery",
        #     the thing any agent should have to beat
        surv_r = surv.rename(columns={"duration": "T", "event": "E"})
        scored = []
        sub = rng.choice(genes_all, size=min(4000, len(genes_all)), replace=False)  # keep it tractable
        for g in sub:
            r = _cox_univariate(surv_r, expr[g])
            if r:
                scored.append((r["p"], g))
        scored.sort()
        for i in range(args.baselines):
            pick = [g for _, g in scored[i * median_n:(i + 1) * median_n]]
            if len(pick) == median_n:
                eps.append((f"BASELINE_topcox_{i}", pick))

    print(f"\nScoring {len(eps)} episodes "
          f"(bootstrap={args.bootstrap}, folds={args.folds}, ldo={args.ldo_reps}) …\n")

    rows = []
    for i, (label, genes) in enumerate(eps, 1):
        d_full = _infer_sgh_directions(genes, expr, surv)
        sig_full = signature(expr, d_full)
        insample = _cox_univariate(surv.rename(columns={"duration": "T", "event": "E"}), sig_full)

        bss = boot_sign_stability(genes, expr, surv, args.bootstrap, rng)
        cv_hr, cv_p = cv_signature(genes, expr, surv, args.folds, rng)
        ldo = ldo_stability(genes, expr, surv, args.ldo_reps, rng)

        t_hr = t_p = None
        if target_os is not None and d_full:
            tsig = signature(target_os, d_full)
            if len(tsig):
                r = _cox_univariate(tsurv, tsig)
                if r:
                    t_hr, t_p = float(r["hr"]), float(r["p"])

        rows.append({
            "episode": label, "n_genes": len(genes), "n_directions": len(d_full),
            "insample_hr": insample["hr"] if insample else None,
            "insample_p": insample["p"] if insample else None,
            "boot_sign_stability": bss,
            "cv_hr": cv_hr, "cv_p": cv_p,
            "ldo_hr_sd": ldo,
            "target_rho": ext.get(label),
            "target_hr": t_hr, "target_p": t_p,
        })
        print(f"  [{i:2}/{len(eps)}] {label:34} boot={bss if bss is None else round(bss,3)}  "
              f"cv_hr={cv_hr if cv_hr is None else round(cv_hr,2)}  "
              f"rho={ext.get(label) if ext.get(label) is None else round(ext[label],3)}")

    df = pd.DataFrame(rows)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(args.out, sep="\t", index=False)
    print(f"\nwrote {args.out}  ({len(df)} episodes)")

    # ---- the actual test: does internal predict external? ----
    print("\n" + "=" * 74)
    print("  DOES INTERNAL ROBUSTNESS PREDICT EXTERNAL REPLICATION?")
    print("=" * 74)
    print("  Spearman across episodes. Expected sign if the loop works:")
    print("    boot_sign_stability vs target_rho  : POSITIVE (stabler -> replicates)")
    print("    cv_hr               vs target_rho  : NEGATIVE (lower CV HR = better internally,")
    print("                                         and should mean higher external rho)")
    print("    ldo_hr_sd           vs target_rho  : NEGATIVE (less wobble -> replicates)\n")
    tests = [("boot_sign_stability", "target_rho", "+"),
             ("cv_hr", "target_rho", "-"),
             ("ldo_hr_sd", "target_rho", "-"),
             ("insample_hr", "target_rho", "-"),
             ("boot_sign_stability", "target_hr", "-"),
             ("cv_hr", "target_hr", "+")]
    any_sig = False
    for a, b, expect in tests:
        sub = df[[a, b]].dropna()
        if len(sub) < 6:
            print(f"  {a:22} vs {b:11} n={len(sub):2}  too few")
            continue
        rho, p = spearmanr(sub[a], sub[b])
        ok = "SIGNIFICANT" if p < 0.05 else "ns"
        if p < 0.05:
            any_sig = True
        got = "+" if rho > 0 else "-"
        match = "matches" if got == expect else "WRONG SIGN"
        print(f"  {a:22} vs {b:11} n={len(sub):2}  rho={rho:+.3f}  p={p:.3f}  {ok:11} ({match})")

    # ---- agent vs naive baselines --------------------------------------------------------
    if df["episode"].str.startswith("BASELINE_").any():
        print("\n" + "=" * 74)
        print("  AGENT SIGNATURES vs NAIVE BASELINES")
        print("=" * 74)
        arms = {"agent": ~df["episode"].str.startswith("BASELINE_"),
                "random genes": df["episode"].str.startswith("BASELINE_random"),
                "top-Cox pick": df["episode"].str.startswith("BASELINE_topcox")}
        cols = ["boot_sign_stability", "insample_hr", "cv_hr", "target_hr", "target_rho"]
        print(f"  {'arm':14} {'n':>3} " + " ".join(f"{c:>19}" for c in cols))
        for name, mask in arms.items():
            sub = df[mask]
            if not len(sub):
                continue
            cells = []
            for c in cols:
                v = sub[c].dropna()
                cells.append(f"{v.median():.3f} [{v.min():.2f},{v.max():.2f}]" if len(v) else "—")
            print(f"  {name:14} {len(sub):>3} " + " ".join(f"{x:>19}" for x in cells))
        print("\n  Read the INTERNAL columns (boot_sign_stability, insample_hr, cv_hr) first:")
        print("  if the agent's arm is indistinguishable from top-Cox, then 'internally robust'")
        print("  is what survival-selection on n=91 looks like for ANY gene set — the agent's")
        print("  process is not what makes it look good, and an internal loop cannot separate")
        print("  a real signature from a selected-on-noise one. Random genes are the floor: they")
        print("  show what NO survival selection looks like.")

    print("\n" + "-" * 74)
    if not any_sig:
        print("  READ: no internal metric predicts external replication in these episodes.")
        print("  An internal-robustness LOOP therefore cannot rescue Phase 3 — iterating would")
        print("  select harder on a signal that does not transfer. This is itself the finding:")
        print("  the agent cannot self-certify which of its results will generalize.")
    else:
        print("  READ: at least one internal metric tracks external replication. The loop is")
        print("  worth building — use the significant metric as the agent's stopping rule.")
    print("  CAVEAT: n is the number of EPISODES, not patients; this is a low-power screen.")
    print("  A null here is suggestive, not proof of no relationship.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
