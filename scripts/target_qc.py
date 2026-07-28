#!/usr/bin/env python3
"""Is TARGET-OS a sound validation cohort, or is it the problem?

Before concluding "SGH-OS signatures do not replicate", the validation cohort itself has to be
cleared. A cohort can fail to confirm a real signature for reasons that have nothing to do with
the signature: wrong normalization scale, missing/flat genes, too few events, broken survival
data, or simply carrying no prognostic signal at all. This runs the checks that separate
"the signature is not real" from "the cohort cannot see it".

TESTS
  1. STRUCTURE     scale, gene overlap, per-gene variance, survival distribution.
                   Catches normalization mismatch and variance collapse — if TARGET genes are
                   flat, cross-cohort z-scoring produces noise no matter how good the signature.
  2. POS CONTROLS  known OS-prognostic gene sets. If literature axes validate here, the cohort
                   demonstrably carries prognostic signal.
  3. SELF-CAPACITY cross-validated signature built IN TARGET, scored on held-out TARGET patients
                   (selection inside the folds, so it is honest). This is the ceiling: the best
                   any signature could do here. If TARGET cannot predict its OWN survival under
                   CV, it cannot confirm anyone else's signature and Phase 3 is unwinnable by
                   construction. Run identically on SGH-OS for comparison.
  4. SYMMETRY      derive top-Cox in SGH -> validate in TARGET, AND derive in TARGET -> validate
                   in SGH. The diagnostic that matters:
                     both fail        -> symmetric non-transfer; the two cohorts encode different
                                         biology (age, treatment, platform). Not a TARGET defect.
                     TARGET->SGH works-> asymmetry; suspect TARGET as the validation end.
                     both work        -> the agent's signatures specifically are the problem.

Usage:
  python scripts/target_qc.py                 # full battery
  python scripts/target_qc.py --topk 25 --folds 5
"""
from __future__ import annotations

import argparse
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
sys.path.insert(0, str(Path(__file__).parent.parent))

from biodiscoverygym.scoring.components_os import (  # noqa: E402
    _build_survival_df,
    _cox_univariate,
    _load_target,
    _load_target_os_survival,
    _zmean,
)
from biodiscoverygym.utils.data_loader import DataLoader  # noqa: E402

OS_DATA_DIR = Path("data/external/os_jia2022")
TARGET_DIR = Path("data/external/TARGET")

# Literature OS-prognostic axes (same sets Phase 3 uses as controls)
POS_CONTROLS = {
    "cytolytic": (["GZMA", "PRF1"], "prot"),
    "hypoxia": (["VEGFA", "SLC2A1", "CA9", "LDHA", "PGK1"], "adv"),
    "proliferation": (["MKI67", "TOP2A", "CCNB1", "BUB1", "PLK1"], "adv"),
    "ifn_gamma": (["IFNG", "STAT1", "CXCL9", "CXCL10", "IDO1"], "prot"),
}


def rank_genes(expr: pd.DataFrame, surv: pd.DataFrame, pool: list[str]) -> list[tuple[float, int, str]]:
    """(p, direction, gene) by univariate Cox. direction +1 protective (HR<1), -1 risk."""
    out = []
    for g in pool:
        r = _cox_univariate(surv, expr[g])
        if r:
            out.append((r["p"], 1 if r["hr"] < 1 else -1, g))
    out.sort()
    return out


def build_sig(expr: pd.DataFrame, picks: list[tuple[float, int, str]]) -> pd.Series:
    prot = [g for _, d, g in picks if d > 0 and g in expr.columns]
    risk = [g for _, d, g in picks if d < 0 and g in expr.columns]
    if not prot and not risk:
        return pd.Series(dtype=float)
    return _zmean(expr, prot) - (_zmean(expr, risk) if risk else 0.0)


def self_capacity(expr, surv, pool, topk, folds, rng, label):
    """CV signature built and selected INSIDE training folds, scored on held-out patients.
    Honest ceiling for what this cohort can support."""
    ids = np.array(list(expr.index.intersection(surv.index)))
    idx = rng.permutation(len(ids))
    chunks = np.array_split(idx, folds)
    held = {}
    for k in range(folds):
        te = ids[chunks[k]]
        tr = ids[np.concatenate([chunks[j] for j in range(folds) if j != k])]
        picks = rank_genes(expr.loc[tr], surv.loc[tr], pool)[:topk]
        if not picks:
            continue
        sig = build_sig(expr.loc[te], picks)
        held.update(sig.to_dict())
    if len(held) < 30:
        return None
    ser = pd.Series(held)
    r = _cox_univariate(surv.loc[ser.index], ser)
    if r:
        print(f"    {label:34} CV HR={r['hr']:.2f}  p={r['p']:.3g}  n={len(ser)}")
    return r


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--topk", type=int, default=25, help="genes per signature (default 25)")
    ap.add_argument("--folds", type=int, default=5)
    ap.add_argument("--pool", type=int, default=3000,
                    help="candidate genes screened (default 3000, most-variable)")
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()
    rng = np.random.default_rng(args.seed)

    ds = DataLoader(Path("data")).load_tcga("OS", tcga_dir=OS_DATA_DIR)
    sgh, sgh_meta = ds["expression"], ds["metadata"]
    sgh_surv = _build_survival_df(sgh_meta).rename(columns={"duration": "T", "event": "E"})
    tgt, _ = _load_target(TARGET_DIR)
    tgt_surv = _load_target_os_survival(TARGET_DIR)
    common_s = sgh.index.intersection(sgh_surv.index)
    common_t = tgt.index.intersection(tgt_surv.index)
    sgh, sgh_surv = sgh.loc[common_s], sgh_surv.loc[common_s]
    tgt, tgt_surv = tgt.loc[common_t], tgt_surv.loc[common_t]

    print("=" * 74)
    print("  1. STRUCTURE")
    print("=" * 74)
    ov = sorted(sgh.columns.intersection(tgt.columns))
    print(f"    SGH-OS     n={len(sgh):3}  events={int(sgh_surv['E'].sum()):3} "
          f"({sgh_surv['E'].mean():.0%})  median FU={sgh_surv['T'].median():.0f}d")
    print(f"    TARGET-OS  n={len(tgt):3}  events={int(tgt_surv['E'].sum()):3} "
          f"({tgt_surv['E'].mean():.0%})  median FU={tgt_surv['T'].median():.0f}d")
    print(f"    gene overlap {len(ov)}  |  value range SGH "
          f"[{sgh.values.min():.1f},{sgh.values.max():.1f}] TARGET "
          f"[{tgt.values.min():.1f},{tgt.values.max():.1f}]")
    print(f"    median per-gene SD  SGH {sgh[ov].std().median():.3f}   TARGET {tgt[ov].std().median():.3f}")

    print("\n" + "=" * 74)
    print("  2. POSITIVE CONTROLS in TARGET-OS")
    print("=" * 74)
    npass = 0
    for name, (genes, expect) in POS_CONTROLS.items():
        have = [g for g in genes if g in tgt.columns]
        if not have:
            print(f"    {name:16} genes absent"); continue
        r = _cox_univariate(tgt_surv, _zmean(tgt, have))
        if not r:
            print(f"    {name:16} fit failed"); continue
        ok = r["p"] < 0.05 and ((r["hr"] < 1) == (expect == "prot"))
        npass += ok
        print(f"    {name:16} HR={r['hr']:.2f}  p={r['p']:.3g}  expect={expect:4} "
              f"{'PASS' if ok else 'ns'}  ({len(have)}/{len(genes)} genes)")
    print(f"    -> {npass}/{len(POS_CONTROLS)} controls validate: "
          f"{'cohort carries prognostic signal' if npass else 'NO detectable signal — cohort suspect'}")

    # most-variable candidate pool, shared so the two cohorts are screened identically
    pool = [g for g in ov if tgt[g].std() > 0.1 and sgh[g].std() > 0.1]
    pool = sorted(pool, key=lambda g: -(tgt[g].std() + sgh[g].std()))[:args.pool]

    print("\n" + "=" * 74)
    print(f"  3. SELF-CAPACITY — CV signature built inside folds (top{args.topk}, {args.folds}-fold)")
    print("=" * 74)
    print("    Ceiling for what each cohort can support on its OWN survival:")
    cap_t = self_capacity(tgt, tgt_surv, pool, args.topk, args.folds, rng, "TARGET-OS -> TARGET-OS (CV)")
    cap_s = self_capacity(sgh, sgh_surv, pool, args.topk, args.folds, rng, "SGH-OS    -> SGH-OS    (CV)")

    print("\n" + "=" * 74)
    print("  4. SYMMETRY — derive in one cohort, validate in the other")
    print("=" * 74)
    s_picks = rank_genes(sgh, sgh_surv, pool)[:args.topk]
    t_picks = rank_genes(tgt, tgt_surv, pool)[:args.topk]
    fwd = _cox_univariate(tgt_surv, build_sig(tgt, s_picks))
    rev = _cox_univariate(sgh_surv, build_sig(sgh, t_picks))
    for lbl, r, base in (("SGH -> TARGET", fwd, "in-SGH selected"),
                         ("TARGET -> SGH", rev, "in-TARGET selected")):
        if r:
            good = r["p"] < 0.05 and r["hr"] < 1
            print(f"    {lbl:16} HR={r['hr']:.2f}  p={r['p']:.3g}   "
                  f"{'REPLICATES' if good else 'fails'}   ({base})")

    print("\n" + "-" * 74)
    print("  VERDICT")
    if npass == 0:
        print("    TARGET-OS shows no detectable prognostic signal even for literature axes.")
        print("    The cohort is the problem — do not draw conclusions about the agent from it.")
    elif cap_t is None or cap_t["p"] > 0.05:
        print("    Positive controls pass, but TARGET cannot predict its OWN survival under CV.")
        print("    Its usable prognostic capacity is near the floor: Phase 3 is close to")
        print("    unwinnable regardless of signature quality. Prefer pooling cohorts.")
    else:
        both_fail = (fwd and fwd["p"] > 0.05) and (rev and rev["p"] > 0.05)
        if both_fail:
            print("    TARGET is sound (controls pass, self-capacity OK) and transfer fails in")
            print("    BOTH directions -> symmetric non-transfer. The two cohorts encode different")
            print("    prognostic biology (pediatric vs adult, treatment era, platform).")
            print("    This is a real scientific result, not a TARGET defect and not an agent bug.")
        else:
            print("    Transfer is asymmetric — inspect the direction that fails.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
