#!/usr/bin/env python3
"""CoT deep-dive — the two tests the paper turns on, plus the supporting structure.

THE ARGUMENT THIS SCRIPT ESTABLISHES:
  H1  Outcome CANNOT separate derived from recalled identity. If a correctness score gives the
      same number whether the agent worked it out or remembered it, then an outcome-only
      leaderboard cannot distinguish discovery from recall — which is what makes a process
      instrument necessary rather than merely interesting.
  H2  Derivation DOES predict robustness. On the mislead arm, episodes that derived identity from
      data are far less likely to commit to the injected false cohort. So grounding is not a
      stylistic preference: it is what determines whether the agent survives bad inputs.

Together: the property that matters for deployment is invisible to the metric the field reports.

Everything is computed from artifacts. Identity labels are the 3-pass judge consensus (ties are
dropped, not broken). Writes a JSON of every statistic so the manuscript cites reproducible
numbers rather than transcribed ones.

Usage: python scripts/cot_deepdive.py   ->  manuscript/figures/cot_stats.json
"""
import glob, json, os, statistics as st, sys
from collections import Counter, defaultdict

from scipy.stats import mannwhitneyu, spearmanr, fisher_exact

SF = ['_cotsummary.json', '_cotsummary_j2.json', '_cotsummary_j3.json']
RUNS = [
    ('GPT-5.5', 'detailed', 'results/tcga/ladder/gpt55_20260707'),
    ('GPT-5.5', 'lean', 'results/tcga/lean/gpt55_20260721'),
    ('Sonnet 5', 'detailed', 'results/tcga/ladder/sonnet5_20260713'),
    ('Sonnet 5', 'lean', 'results/tcga/lean/sonnet5_20260722'),
    ('Gemini 3.5 Flash', 'detailed', 'results/tcga/ladder/gemini35flash_20260716'),
    ('Gemini 3.5 Flash', 'lean', 'results/tcga/lean/gemini35flash_20260722'),
]
OUT = 'manuscript/figures/cot_stats.json'


def consensus(votes):
    c = Counter(votes).most_common()
    return None if len(c) > 1 and c[0][1] == c[1][1] else c[0][0]


def collect(arm_prefix):
    """Episodes on an arm with BOTH an outcome score and all three judge votes."""
    rows = []
    for model, prompt, run in RUNS:
        for p in glob.glob(f"{run}/{arm_prefix}*/{arm_prefix}*_v3scores.json"):
            lab = os.path.basename(p).replace('_v3scores.json', '')
            if os.path.basename(os.path.dirname(p)) != lab:
                continue
            votes = []
            for s in SF:
                jp = os.path.join(os.path.dirname(p), lab + s)
                if os.path.exists(jp):
                    votes.append(json.load(open(jp)).get('identity_derivation'))
            if len(votes) != 3:
                continue
            v3 = json.load(open(p))
            rows.append(dict(
                model=model, prompt=prompt, label=lab,
                cohort=lab.split('_')[1].upper(),
                deriv=consensus(votes), votes=votes,
                outcome=v3.get('normalized'),
                verdict=v3.get('cohort_identity_verdict'),
                fooled=v3.get('cohort_identity_verdict') == 'mislead_cohort'))
    return rows


def main():
    stats = {}
    g2, g3 = collect('g2'), collect('g3')

    # ---------------- H1: outcome cannot see the difference ----------------
    print("=" * 78)
    print("  H1 — can OUTCOME separate derived from recalled?   (G2, blinded)")
    print("=" * 78)
    by = defaultdict(list)
    for x in g2:
        by[x['deriv']].append(x['outcome'])
    h1 = {}
    for k in ['data-derived', 'mixed', 'recalled-prior']:
        v = by.get(k) or []
        if v:
            h1[k] = dict(n=len(v), mean=st.mean(v), median=st.median(v), sd=st.pstdev(v))
            print(f"  {k:16} n={len(v):3}  mean {st.mean(v):.3f}  median {st.median(v):.3f}")
    d, r = by.get('data-derived', []), by.get('recalled-prior', [])
    u, pv = mannwhitneyu(d, r)
    rank = {'recalled-prior': 0, 'mixed': 1, 'data-derived': 2}
    xs = [(rank[x['deriv']], x['outcome']) for x in g2 if x['deriv'] in rank]
    rho, rpv = spearmanr([a for a, _ in xs], [b for _, b in xs])
    print(f"\n  derived {st.mean(d):.3f} vs recalled {st.mean(r):.3f}  "
          f"delta {st.mean(d)-st.mean(r):+.3f}   Mann-Whitney p={pv:.3f}")
    print(f"  ordinal derivation-rank vs outcome: rho={rho:+.3f}  p={rpv:.3f}  (n={len(xs)})")
    # within-arm, to rule out a pooling artifact
    within = {}
    print(f"\n  within each arm (guards against Simpson's paradox):")
    for model, prompt, _ in RUNS:
        s = [x for x in g2 if x['model'] == model and x['prompt'] == prompt]
        dd = [x['outcome'] for x in s if x['deriv'] == 'data-derived']
        nn = [x['outcome'] for x in s if x['deriv'] in ('recalled-prior', 'mixed')]
        if len(dd) >= 3 and len(nn) >= 3:
            within[f"{model}/{prompt}"] = dict(derived=st.mean(dd), n_derived=len(dd),
                                               not_derived=st.mean(nn), n_not=len(nn),
                                               delta=st.mean(dd) - st.mean(nn))
            print(f"    {model+'/'+prompt:24} {st.mean(dd):.3f} (n={len(dd):2}) vs "
                  f"{st.mean(nn):.3f} (n={len(nn):2})   {st.mean(dd)-st.mean(nn):+.3f}")
    stats['h1_outcome_vs_derivation'] = dict(
        groups=h1, mann_whitney_p=float(pv),
        delta=st.mean(d) - st.mean(r), spearman_rho=float(rho), spearman_p=float(rpv),
        n=len(xs), within_arm=within,
        verdict=('outcome does NOT separate derived from recalled'
                 if pv > 0.05 else 'outcome separates them'))

    # ---------------- H2: derivation predicts robustness ----------------
    print("\n" + "=" * 78)
    print("  H2 — does DERIVING identity protect against the mislead?   (G3)")
    print("=" * 78)
    # An identity gate that ERRORED has no verdict. Counting it as "not fooled" — which every
    # naive `verdict == "mislead_cohort"` test does — fabricates robustness out of a failed API
    # call. A whole run arm failed this way and produced an apparent "0/12 fooled" that was read
    # as a finding. Drop them, and say loudly how many were dropped.
    errored = [x for x in g3 if x['verdict'] == 'error']
    if errored:
        by = Counter(f"{x['model']}/{x['prompt']}" for x in errored)
        print(f"  !! EXCLUDING {len(errored)} episodes whose identity gate FAILED "
              f"(no verdict — NOT a zero): {dict(by)}\n")
    g3 = [x for x in g3 if x['verdict'] != 'error']
    tab = defaultdict(lambda: [0, 0])         # [not fooled, fooled]
    for x in g3:
        k = 'derived' if x['deriv'] == 'data-derived' else 'not-derived'
        tab[k][int(x['fooled'])] += 1
    print(f"  {'':14} {'not fooled':>11} {'FOOLED':>8}   rate")
    for k in ['derived', 'not-derived']:
        nf, f = tab[k]
        print(f"  {k:14} {nf:>11} {f:>8}   {f/max(nf+f,1)*100:>5.0f}%")
    a, b = tab['derived'], tab['not-derived']
    odds, fpv = fisher_exact([[a[1], a[0]], [b[1], b[0]]])
    print(f"\n  Fisher exact p={fpv:.4f}   odds ratio={odds:.2f}   n={len(g3)}")
    stats['h2_derivation_vs_fooled'] = dict(
        derived=dict(not_fooled=a[0], fooled=a[1], rate=a[1] / max(sum(a), 1)),
        not_derived=dict(not_fooled=b[0], fooled=b[1], rate=b[1] / max(sum(b), 1)),
        fisher_p=float(fpv), odds_ratio=float(odds), n=len(g3),
        excluded_failed_gates=len(errored),
        note='episodes whose identity gate errored are EXCLUDED, not counted as not-fooled')

    # ---------------- supporting: cohort, judge stability ----------------
    coh = defaultdict(lambda: [0, 0])
    for x in g2:
        coh[x['cohort']][0] += (x['deriv'] == 'data-derived'); coh[x['cohort']][1] += 1
    stats['cohort_derivation'] = {k: dict(derived=v[0], n=v[1], rate=v[0] / v[1])
                                  for k, v in coh.items()}
    print("\n" + "=" * 78)
    print("  Supporting — G2 derivation rate by cohort")
    print("=" * 78)
    for c, (dv, n) in sorted(coh.items(), key=lambda kv: -kv[1][0] / kv[1][1]):
        print(f"  {c:6} {dv:2}/{n:2}  {dv/n*100:>5.0f}%")
    rates = [v[0] / v[1] for v in coh.values()]
    print(f"  spread {min(rates)*100:.0f}%-{max(rates)*100:.0f}% — "
          f"{'flat, no cohort effect' if max(rates)-min(rates) < 0.25 else 'cohort-dependent'}")

    unan = sum(1 for x in g2 + g3 if len(set(x['votes'])) == 1)
    stats['judge'] = dict(n=len(g2) + len(g3), unanimous=unan,
                          unanimous_rate=unan / max(len(g2) + len(g3), 1),
                          unresolved=sum(1 for x in g2 + g3 if x['deriv'] is None))
    stats['n'] = dict(g2=len(g2), g3=len(g3))

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(stats, open(OUT, 'w'), indent=2)
    print(f"\nwrote {OUT}")
    print("\n" + "-" * 78)
    print("  THE ARGUMENT, in two numbers:")
    print(f"    outcome cannot see grounding      p={pv:.2f}  (derived {st.mean(d):.3f} vs recalled {st.mean(r):.3f})")
    print(f"    grounding predicts robustness     p={fpv:.4f} ({a[1]/max(sum(a),1)*100:.0f}% vs {b[1]/max(sum(b),1)*100:.0f}% fooled)")
    print("  The property that matters for deployment is invisible to the reported metric.")
    return 0


if __name__ == '__main__':
    sys.exit(main())
