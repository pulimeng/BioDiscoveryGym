#!/usr/bin/env python3
"""Cohort-clustered bootstrap intervals — the interval the preregistration actually asks for.

WHY CLUSTERS AND NOT EPISODES. `manuscript/PREREGISTRATION.md` §5 names pseudoreplication, not
power, as this design's real statistical risk: the same cohort recurs across arms, prompts, models
and seeds, so 126 G2 episodes are not 126 independent draws — they are **7 cohorts** observed many
times each. Resampling episodes would treat them as independent and report an interval far tighter
than the design earns. So we resample the CLUSTER (cohort, or cohort-pair on G3) with replacement,
rebuild the statistic from whichever episodes those clusters carry, and take percentiles.

WHAT TO EXPECT, STATED BEFORE LOOKING (prereg §5, "show the structure"):
  * R1 (ladder -> identity strategy) has 7 cohorts. That is few, but enough for a usable interval.
  * R4' (adoption once exposed) has **2 cohort-pairs**. A 2-cluster bootstrap can only ever resample
    {LUSC,LUSC}, {LUSC,OV}, {OV,OV} — three distinct worlds. The interval it produces is close to
    meaningless and we report it as such rather than dressing it up. This is the honest ceiling the
    preregistration already named: more seeds cannot manufacture independent units.

Per-cluster values are printed beside every interval, because with 2-7 clusters the individual
values ARE the evidence and a summary interval hides them.

Usage:  BDG_RUNS=clean python scripts/cluster_intervals.py
        -> manuscript/figures/cluster_intervals.json
"""
from __future__ import annotations

import glob
import json
import os
import random
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import panel_data
import runs_config
from g3_exposure import was_exposed

OUT = 'manuscript/figures/cluster_intervals.json'
B = 10000
SEED = 20260813          # fixed: an interval that moves between runs is not a reported number
LEVELS = ['d1_partition', 'd2_identity', 'd3_mechanism']


def load():
    """Panel-reduced rows. Reduction is panel_data's, so this file cannot drift from
    explore_exploit's definition of what a strategy label or a verdict IS — which matters here
    because these are the intervals the paper quotes."""
    allrows, missing = panel_data.load()
    panel_data.require_complete(allrows, missing)
    rows = [dict(model=r['model'], prompt=r['prompt'], arm=r['arm'], cohort=r['cohort'],
                 outcome=r['outcome'], verdict=r['verdict'],
                 d2_strat=r['d2_identity_strat'], d2_sup=r['d2_identity_sup'],
                 exposed=r['exposed'])
            for r in allrows]
    return rows


def cluster_boot(rows, stat, cluster_key='cohort', b=B, seed=SEED):
    """Percentile CI resampling CLUSTERS with replacement. Returns (point, lo, hi, per-cluster)."""
    by = defaultdict(list)
    for r in rows:
        by[r[cluster_key]].append(r)
    keys = sorted(by)
    point = stat(rows)
    per = {k: stat(by[k]) for k in keys}
    rng = random.Random(seed)
    draws = []
    for _ in range(b):
        pick = [rng.choice(keys) for _ in keys]
        pooled = [r for k in pick for r in by[k]]
        v = stat(pooled)
        if v is not None:
            draws.append(v)
    draws.sort()
    if not draws:
        return point, None, None, per, 0
    lo = draws[int(0.025 * len(draws))]
    hi = draws[min(len(draws) - 1, int(0.975 * len(draws)))]
    return point, lo, hi, per, len(keys)


def frac(key, val):
    def f(rs):
        v = [r for r in rs if r.get(key) is not None]
        return sum(1 for r in v if r[key] == val) / len(v) if v else None
    return f


def mean_of(key):
    def f(rs):
        v = [r[key] for r in rs if r.get(key) is not None]
        return sum(v) / len(v) if v else None
    return f


def show(title, rows, stat, ckey='cohort', pct=True, note=''):
    pt, lo, hi, per, nk = cluster_boot(rows, stat, ckey)
    fmt = (lambda x: '  n/a' if x is None else (f"{x*100:5.1f}%" if pct else f"{x:6.3f}"))
    print(f"\n  {title}")
    print(f"    point {fmt(pt)}   95% CI [{fmt(lo)}, {fmt(hi)}]   "
          f"n={len(rows)} episodes across {nk} {ckey} clusters{note}")
    print("    per cluster: " + "  ".join(f"{k}={fmt(v)}" for k, v in sorted(per.items())))
    return dict(point=pt, lo=lo, hi=hi, n_episodes=len(rows), n_clusters=nk,
                per_cluster=per, cluster_key=ckey)


def main():
    rows = load()
    out = {'source': runs_config.SOURCE, 'bootstrap': B, 'seed': SEED}

    print("=" * 100)
    print("  R1 — identity strategy across the ladder (7 cohort clusters)")
    print("=" * 100)
    r1 = {}
    for w in ('detailed', 'lean'):
        for arm in ('g0', 'g1', 'g2'):
            sub = [r for r in rows if r['prompt'] == w and r['arm'] == arm]
            r1[f'{w}/{arm}'] = show(f"{w}/{arm}  explore-rate at D2 identity",
                                    sub, frac('d2_strat', 'explore'))
    out['r1_explore_rate'] = r1

    print("\n" + "=" * 100)
    print("  R2 — outcome across the ladder (7 cohort clusters)")
    print("=" * 100)
    r2 = {}
    for w in ('detailed', 'lean'):
        for arm in ('g0', 'g1', 'g2'):
            sub = [r for r in rows if r['prompt'] == w and r['arm'] == arm]
            r2[f'{w}/{arm}'] = show(f"{w}/{arm}  mean outcome", sub, mean_of('outcome'), pct=False)
    out['r2_outcome'] = r2

    print("\n" + "=" * 100)
    print("  R3 — grounded identity claims (7 cohort clusters)")
    print("=" * 100)
    r3 = {}
    for w in ('detailed', 'lean'):
        for arm in ('g0', 'g2'):
            sub = [r for r in rows if r['prompt'] == w and r['arm'] == arm]
            r3[f'{w}/{arm}'] = show(f"{w}/{arm}  grounded rate", sub, frac('d2_sup', 'grounded'))
    out['r3_grounded'] = r3

    print("\n" + "=" * 100)
    print("  R4' — adoption once EXPOSED  (2 cohort-pair clusters — see the warning)")
    print("=" * 100)
    print("  !! Two clusters. The bootstrap can only draw {LUSC,LUSC}, {LUSC,OV}, {OV,OV}, so the")
    print("     interval below has three possible values and is NOT a usable uncertainty estimate.")
    print("     The per-cluster values and the replication table are the evidence. Reported to")
    print("     satisfy prereg §5 and to make the ceiling visible, not because it is informative.")
    g3e = [r for r in rows if r['arm'].startswith('g3') and r['exposed'] and r['verdict']]
    out['r4_adoption_exposed'] = show("adoption of the planted label | exposed", g3e,
                                      frac('verdict', 'mislead_cohort'), note=' (2 clusters!)')
    out['r4_adoption_exposed']['warning'] = (
        'Two cohort-pairs only. Interval is degenerate; cite the per-cluster values and the '
        'per-model replication instead. Prereg §5 names this ceiling explicitly.')

    # model-level view, which has 3 clusters and is at least slightly better behaved
    out['r4_by_model_cluster'] = show("adoption | exposed, resampling MODELS instead", g3e,
                                      frac('verdict', 'mislead_cohort'), ckey='model')

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(out, open(OUT, 'w'), indent=1)
    print(f"\n  -> {OUT}\n")


if __name__ == '__main__':
    main()
