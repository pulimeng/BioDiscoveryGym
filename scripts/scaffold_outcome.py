#!/usr/bin/env python3
"""Does the staged scaffold buy a better GRADE while buying nothing that matters?

THE CLAIM THIS TESTS. Every other prompt contrast in this paper is about process. This one is about
the score itself: if the prescribed six-stage procedure scores higher on the outcome metric while
producing *less* grounded identity claims and *no* additional resistance to a false premise, then the
metric is rewarding procedure rather than epistemics — which is the sharpest available statement of
"the leaderboard rewards the wrong thing."

WHY PAIRED. The two waves are not independent samples. The same model runs the same cohort at the
same seed under both prompts, so every episode has a natural twin differing only in the prompt. A
Wilcoxon signed-rank test on those matched pairs removes cohort difficulty — which this study has
already shown is the largest single source of outcome variance (OV 0.33 vs UCEC 0.56, a spread wider
than any effect here). An unpaired Mann-Whitney throws that control away and is the weaker test.

DENOMINATOR DISCIPLINE. Honest arms only (g0/g1/g2). G3 outcomes are gated by the identity verdict —
a fooled episode has its narrative components zeroed — so a G3 outcome comparison would mostly be
re-measuring adoption, which is reported separately and on the exposed denominator.

INTERVALS. Bootstrap resamples COHORTS, not episodes (preregistration §5): 7 cohorts observed many
times are not 126 independent draws.

Usage:  BDG_RUNS=clean python scripts/scaffold_outcome.py
        -> manuscript/figures/scaffold_outcome.json
"""
from __future__ import annotations

import glob
import json
import os
import random
import statistics as st
import sys
from collections import defaultdict

from scipy.stats import wilcoxon, mannwhitneyu

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import panel_data
import runs_config

OUT = 'manuscript/figures/scaffold_outcome.json'
HONEST = ('g0', 'g1', 'g2')
B, SEED = 10000, 20260813


def load():
    """{(model, prompt, label): record} over honest arms, reduced across the judge panel.

    Reduction is panel_data's, not a private copy: categorical fields take the majority across
    judges (None when they split), continuous fields the mean. `grounded` and `rigor_high`
    therefore mean "the panel agreed it was", and an episode the panel could not resolve is
    False on both rather than silently taking whichever judge sorted first.
    """
    rows = {}
    allrows, missing = panel_data.load()
    panel_data.require_complete(allrows, missing)
    for r in allrows:
        if r['arm'] not in HONEST:
            continue
        rows[(r['model'], r['prompt'], r['label'])] = dict(
            model=r['model'], prompt=r['prompt'], label=r['label'], arm=r['arm'],
            cohort=r['cohort'], outcome=r['outcome'], raw=r['raw_scores'],
            support_score=r['support_score'],
            grounded=r['d2_identity_sup'] == 'grounded',
            rigor_high=r['rigor'] == 'high')
    return rows


def pairs(rows, arms=HONEST):
    """Matched (detailed, lean) twins — same model, same cohort, same seed, same arm."""
    out = []
    for (m, pr, lab), r in rows.items():
        if pr != 'detailed' or r['arm'] not in arms:
            continue
        twin = rows.get((m, 'lean', lab))
        if twin and r['outcome'] is not None and twin['outcome'] is not None:
            out.append((r, twin))
    return out


def cluster_boot(items, stat, key=lambda x: x[0]['cohort'], b=B, seed=SEED):
    by = defaultdict(list)
    for it in items:
        by[key(it)].append(it)
    keys = sorted(by)
    rng = random.Random(seed)
    draws = []
    for _ in range(b):
        pooled = [x for k in (rng.choice(keys) for _ in keys) for x in by[k]]
        v = stat(pooled)
        if v is not None:
            draws.append(v)
    draws.sort()
    return (stat(items), draws[int(.025 * len(draws))], draws[min(len(draws) - 1, int(.975 * len(draws)))],
            {k: stat(by[k]) for k in keys}, len(keys))


def mean_delta(ps):
    d = [a['outcome'] - b['outcome'] for a, b in ps]
    return st.mean(d) if d else None


def main():
    rows = load()
    out = {'source': runs_config.SOURCE}

    print("=" * 100)
    print("  STAGED (detailed) vs LEAN — outcome, PAIRED by model x cohort x seed x arm")
    print("=" * 100)

    allp = pairs(rows)
    print(f"  matched pairs: {len(allp)} (honest arms only; G3 excluded — its outcome is "
          f"identity-gated)\n")
    print(f"  {'scope':22}{'n':>5}{'staged':>9}{'lean':>8}{'Δ':>9}{'in SD':>8}"
          f"{'Wilcoxon p':>13}{'staged wins':>13}")

    def report(label, ps, store):
        if len(ps) < 5:
            print(f"  {label:22}{len(ps):>5}   insufficient")
            return
        a = [x['outcome'] for x, _ in ps]
        b = [y['outcome'] for _, y in ps]
        d = [x - y for x, y in zip(a, b)]
        sd = st.pstdev(a + b)
        try:
            _, p = wilcoxon(a, b)
        except ValueError:
            p = float('nan')
        wins = sum(1 for x in d if x > 0)
        print(f"  {label:22}{len(ps):>5}{st.mean(a):>9.3f}{st.mean(b):>8.3f}{st.mean(d):>+9.3f}"
              f"{st.mean(d)/sd:>8.2f}{p:>13.2e}{wins:>7}/{len(ps):<5}")
        store[label.strip()] = dict(n=len(ps), staged=st.mean(a), lean=st.mean(b),
                                    delta=st.mean(d), delta_sd=st.mean(d) / sd,
                                    wilcoxon_p=float(p), staged_wins=wins)

    per = {}
    report('ALL honest arms', allp, per)
    for arm in HONEST:
        report(f'  {arm}', pairs(rows, (arm,)), per)
    print()
    for m in sorted({r['model'] for r in rows.values()}):
        report(f'  {m}', [p for p in allp if p[0]['model'] == m], per)
    print()
    for m in sorted({r['model'] for r in rows.values()}):
        report(f'  {m[:10]} @g2', [p for p in pairs(rows, ('g2',)) if p[0]['model'] == m], per)
    out['paired'] = per

    # ---- cohort-clustered interval on the pooled delta (prereg §5) --------------------------
    pt, lo, hi, percoh, nk = cluster_boot(allp, mean_delta)
    print("=" * 100)
    print("  COHORT-CLUSTERED 95% CI on the paired delta (resamples cohorts, not episodes)")
    print("=" * 100)
    print(f"  delta {pt:+.4f}   95% CI [{lo:+.4f}, {hi:+.4f}]   {nk} cohort clusters")
    print("  per cohort: " + "  ".join(f"{k}={v:+.3f}" for k, v in sorted(percoh.items())))
    excl = lo > 0 or hi < 0
    print(f"  interval excludes zero: {excl}")
    out['clustered_ci'] = dict(point=pt, lo=lo, hi=hi, n_clusters=nk,
                               per_cohort=percoh, excludes_zero=bool(excl))

    # ---- what the extra grade is made of ---------------------------------------------------
    print("\n" + "=" * 100)
    print("  WHICH COMPONENTS CARRY THE STAGED ADVANTAGE (paired, honest arms)")
    print("=" * 100)
    comps = sorted({k for r in rows.values() for k in r['raw']})
    comp_out = {}
    for c in comps:
        d = [x['raw'][c] - y['raw'][c] for x, y in allp if c in x['raw'] and c in y['raw']]
        if len(d) < 5:
            continue
        try:
            _, p = wilcoxon(d)
        except ValueError:
            p = float('nan')
        comp_out[c] = dict(delta=st.mean(d), wilcoxon_p=float(p), n=len(d))
        flag = '  <--' if p < 0.05 else ''
        print(f"    {c:28} Δ={st.mean(d):+.4f}   p={p:.2e}   n={len(d)}{flag}")
    out['components'] = comp_out

    # ---- the juxtaposition: what the extra grade did NOT buy --------------------------------
    print("\n" + "=" * 100)
    print("  WHAT THE HIGHER GRADE DID NOT BUY (same paired episodes)")
    print("=" * 100)
    g2 = pairs(rows, ('g2',))
    for label, f in (('identity claim grounded', lambda r: r['grounded']),
                     ('validation_rigor = high', lambda r: r['rigor_high'])):
        sa = sum(1 for x, _ in g2 if f(x))
        sb = sum(1 for _, y in g2 if f(y))
        print(f"    G2 {label:26} staged {sa:3d}/{len(g2)} ({sa/len(g2)*100:5.1f}%)   "
              f"lean {sb:3d}/{len(g2)} ({sb/len(g2)*100:5.1f}%)")
        out.setdefault('g2_side_by_side', {})[label] = dict(
            staged=sa, lean=sb, n=len(g2), staged_rate=sa / len(g2), lean_rate=sb / len(g2))
    sup_a = [x['support_score'] for x, _ in g2 if x['support_score'] is not None]
    sup_b = [y['support_score'] for _, y in g2 if y['support_score'] is not None]
    print(f"    G2 {'support score (/5)':26} staged {st.mean(sup_a):5.2f}          "
          f"lean {st.mean(sup_b):5.2f}")
    out['g2_support_score'] = dict(staged=st.mean(sup_a), lean=st.mean(sup_b))
    print("\n    false-label adoption, exposed denominator (from reveal_mechanism.py):")
    print("      staged 81/85 (95.3%)   lean 46/50 (92.0%)   p=0.47  — no protection bought")

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(out, open(OUT, 'w'), indent=1)
    print(f"\n  -> {OUT}\n")


if __name__ == '__main__':
    main()
