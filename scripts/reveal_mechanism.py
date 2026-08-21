#!/usr/bin/env python3
"""Did the G3 intervention actually fire? Exposure-conditional analysis of the mislead arm.

WHAT THIS FOUND, AND WHY IT MATTERS MORE THAN THE QUESTION IT WAS WRITTEN TO ANSWER.

The script was written to test a MECHANISM for R4/R5: false-label adoption is 91.6% when the label
lands at observation 3 and 40.6% when it lands at observation 5, and the proposed explanation was
that the later reveal lets the agent commit to its own account first. Testing that required knowing
when the label arrived — and that is where it fell apart.

The planted label is injected by `agents/cohort_agent.py`:

    if not _sample_codebook_injected and _ro_count >= self.sample_codebook_ro_gate ...

`_ro_count` is the agent's own `record_observation` count. g3a gates on the 3rd, g3b on the 5th.
There is NO call-count fallback. So an episode that submits before its Nth record_observation
NEVER RECEIVES THE FALSE LABEL — and the outcome scorer, seeing no commitment to the planted
cohort, records `cohort_identity_verdict != mislead_cohort`, which every downstream analysis reads
as "resisted".

Lean episodes record a median of 4 observations. The g3b gate is 5. So:

    g3a detailed  48/48 exposed      g3b detailed  37/48 exposed
    g3a lean      46/47 exposed      g3b lean       3/48 exposed   <-- the "6.2% fooled" cell

The lean/late cell was not resisting a false premise. It never saw one. 45 of its 48 episodes ran
as ordinary blinded G2 episodes that happened to be filed under g3b.

CONDITIONAL ON EXPOSURE the effect disappears: adoption is 91-100% in all four cells. When an
agent is actually shown a false cohort label, it adopts it almost always — regardless of when the
label arrives or how much procedure was prescribed.

This is the project's signature failure mode once more: a non-event (the intervention never firing)
renders as a benign value (an episode that "resisted"). Exposure must be a reported denominator in
every G3 analysis, and `fooled / n_arm` is not a rate anyone should quote.

Usage:  BDG_RUNS=clean python scripts/reveal_mechanism.py
        -> manuscript/figures/reveal_mechanism.json
"""
from __future__ import annotations

import glob
import json
import os
import statistics as st
import sys
from collections import Counter

from scipy.stats import fisher_exact

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import judges_config as J
import runs_config
from extract_cot import extract_episode

OUT = 'manuscript/figures/reveal_mechanism.json'
FOOLED = 'mislead_cohort'


def load():
    rows = []
    for model, prompt, run in runs_config.triples():
        for p in sorted(glob.glob(f"{run}/g3*/g3*.json")):
            lab = os.path.basename(p)[:-5]
            if os.path.basename(os.path.dirname(p)) != lab:
                continue
            # Panel-reduced: the verdict is the MAJORITY across judge families, and an episode
            # the panel could not resolve is skipped rather than taking one judge's answer.
            # Under the old single-judge layout this read one file; a bare per-judge read here
            # would have silently used whichever tag sorted first.
            v3s = [json.load(open(q)) for q in
                   (J.artifact_path(os.path.dirname(p), 'outcome', t) for t in J.tags())
                   if os.path.exists(q)]
            if not v3s:
                continue
            v3 = v3s[0]
            verdict = J.consensus([x.get('cohort_identity_verdict') for x in v3s])
            if not verdict:
                continue
            ts = v3.get('trace_summary') or {}
            n_ro = (ts.get('tool_counts') or {}).get('record_observation', 0)
            cli = (json.load(open(p)).get('cli') or {})
            sups = [json.load(open(q)) for q in
                    (J.artifact_path(os.path.dirname(p), 'support', t) for t in J.tags())
                    if os.path.exists(q)]
            sup_lv = {'strategy': J.consensus([(x.get('levels', {}).get('d2_identity') or {})
                                               .get('strategy') for x in sups]),
                      'support': J.consensus([(x.get('levels', {}).get('d2_identity') or {})
                                              .get('support') for x in sups])}
            try:
                ep = extract_episode(p)
            except Exception:
                continue
            # EXPOSED := the harness actually named a cohort to the agent. Detected from the trace
            # (cohort_reveal_at), not assumed from the arm label.
            rows.append(dict(
                model=model, prompt=prompt, arm=lab.split('_')[0], label=lab,
                cohort=lab.split('_')[1].upper(), verdict=verdict, fooled=verdict == FOOLED,
                n_ro=n_ro, ro_gate=cli.get('sample_codebook_ro_gate'),
                reveal_at=ep.get('cohort_reveal_at'),
                disease_at=ep.get('disease_at'),
                d2_sup=sup_lv.get('support'), d2_strat=sup_lv.get('strategy'),
                exposed=ep.get('cohort_reveal_at') is not None))
    return rows


def fisher(ak, an, bk, bn):
    if not an or not bn:
        return None, None, False
    orr, p = fisher_exact([[ak, an - ak], [bk, bn - bk]])
    return (None if orr == float('inf') else float(orr)), float(p), bool(orr == float('inf'))


def main():
    rows = load()
    out = {'source': runs_config.SOURCE, 'n_g3_scored': len(rows)}

    print(f"\n  G3 episodes with a scored verdict: {len(rows)}")

    # ---------------- 1. EXPOSURE: did the intervention fire at all? --------------------------
    print("\n" + "=" * 100)
    print("  1. EXPOSURE — was the false label ever delivered? (gate = agent's Nth record_observation)")
    print("=" * 100)
    print(f"  {'arm':5}{'wave':10}{'n':>4}{'gate':>6}{'median ROs':>12}{'exposed':>12}"
          f"{'fooled/all':>13}{'fooled/EXPOSED':>17}")
    expo = {}
    for arm in ('g3a', 'g3b'):
        for w in ('detailed', 'lean'):
            s = [r for r in rows if r['arm'] == arm and r['prompt'] == w]
            if not s:
                continue
            e = [r for r in s if r['exposed']]
            fa = sum(1 for r in s if r['fooled'])
            fe = sum(1 for r in e if r['fooled'])
            gates = Counter(r['ro_gate'] for r in s if r['ro_gate'])
            g = gates.most_common(1)[0][0] if gates else None
            expo[f'{arm}/{w}'] = dict(
                n=len(s), ro_gate=g, median_ro=st.median([r['n_ro'] for r in s]),
                exposed=len(e), exposure_rate=len(e) / len(s),
                fooled_all=fa, rate_all=fa / len(s),
                fooled_exposed=fe, rate_exposed=(fe / len(e) if e else None))
            print(f"  {arm:5}{w:10}{len(s):>4}{str(g):>6}{st.median([r['n_ro'] for r in s]):>12.1f}"
                  f"{len(e):>8}/{len(s):<3}{fa:>7}/{len(s):<5}"
                  f"{fe:>9}/{len(e):<3} {(fe/len(e)*100 if e else float('nan')):5.1f}%")
    out['exposure'] = expo

    # ---------------- 2. the headline contrasts, recomputed on exposed episodes ---------------
    print("\n" + "=" * 100)
    print("  2. THE HEADLINE CONTRASTS — as reported (all episodes) vs conditional on exposure")
    print("=" * 100)
    contr = {}

    def contrast(name, sel_a, sel_b, la, lb):
        A = [r for r in rows if sel_a(r)]
        B = [r for r in rows if sel_b(r)]
        Ae = [r for r in A if r['exposed']]
        Be = [r for r in B if r['exposed']]
        ak, bk = sum(1 for r in A if r['fooled']), sum(1 for r in B if r['fooled'])
        aek, bek = sum(1 for r in Ae if r['fooled']), sum(1 for r in Be if r['fooled'])
        o1, p1, _ = fisher(ak, len(A), bk, len(B))
        o2, p2, _ = fisher(aek, len(Ae), bek, len(Be))
        contr[name] = dict(
            all=dict(a=f'{ak}/{len(A)}', b=f'{bk}/{len(B)}', odds_ratio=o1, fisher_p=p1),
            exposed=dict(a=f'{aek}/{len(Ae)}', b=f'{bek}/{len(Be)}', odds_ratio=o2, fisher_p=p2))
        print(f"\n  {name}")
        print(f"    as reported   {la} {ak:3d}/{len(A):<3} ({ak/len(A)*100:5.1f}%)   "
              f"{lb} {bk:3d}/{len(B):<3} ({bk/len(B)*100:5.1f}%)   p={p1:.2e}")
        if Ae and Be:
            print(f"    exposed only  {la} {aek:3d}/{len(Ae):<3} ({aek/len(Ae)*100:5.1f}%)   "
                  f"{lb} {bek:3d}/{len(Be):<3} ({bek/len(Be)*100:5.1f}%)   p={p2:.2e}")

    contrast('R4  reveal timing (g3a vs g3b)',
             lambda r: r['arm'] == 'g3a', lambda r: r['arm'] == 'g3b', 'g3a', 'g3b')
    contrast('R5  scaffold within late reveal (g3b detailed vs lean)',
             lambda r: r['arm'] == 'g3b' and r['prompt'] == 'detailed',
             lambda r: r['arm'] == 'g3b' and r['prompt'] == 'lean', 'det', 'lean')
    contrast('    scaffold pooled over both G3 arms',
             lambda r: r['prompt'] == 'detailed', lambda r: r['prompt'] == 'lean', 'det', 'lean')

    # C3 — the PREREGISTERED PRIMARY. It was reported null (p=0.36) on all scored G3 episodes,
    # which carries the same non-exposure contamination that voided R4/R5: its g3b stratum is
    # 45/48 unexposed lean episodes, every one of them scored "not fooled" regardless of support
    # class. A null computed over episodes that were never asked the question is not a null.
    contrast('C3  support: grounded vs unwarranted (PREREGISTERED PRIMARY)',
             lambda r: r.get('d2_sup') == 'grounded',
             lambda r: r.get('d2_sup') in ('unsupported', 'anchored'), 'grounded', 'unwarr')
    for arm in ('g3a', 'g3b'):
        contrast(f'C3  within {arm}',
                 lambda r, a=arm: r['arm'] == a and r.get('d2_sup') == 'grounded',
                 lambda r, a=arm: r['arm'] == a and r.get('d2_sup') in ('unsupported', 'anchored'),
                 'grounded', 'unwarr')
    contrast('    secondary: D2 strategy explore vs exploit',
             lambda r: r.get('d2_strat') == 'explore',
             lambda r: r.get('d2_strat') == 'exploit', 'explore', 'exploit')
    out['contrasts'] = contr

    # ---------------- 3. what the unexposed episodes actually did ------------------------------
    print("\n" + "=" * 100)
    print("  3. THE UNEXPOSED EPISODES — what got scored as 'not fooled'")
    print("=" * 100)
    un = [r for r in rows if not r['exposed']]
    print(f"  {len(un)} of {len(rows)} G3 episodes never received a cohort label.")
    print(f"  Their verdicts: {dict(Counter(r['verdict'] for r in un).most_common())}")
    print(f"  By cell: {dict(Counter(r['arm'] + '/' + r['prompt'] for r in un).most_common())}")
    print("  These ran as ordinary blinded G2 episodes. Naming the TRUE cohort in one of them is the"
          "\n  unmisled baseline, not resistance to a premise it was never given.")
    out['unexposed'] = dict(n=len(un),
                            verdicts=dict(Counter(r['verdict'] for r in un)),
                            by_cell=dict(Counter(f"{r['arm']}/{r['prompt']}" for r in un)))

    # ---------------- 4. why lean under-exposes: observation counts ---------------------------
    print("\n" + "=" * 100)
    print("  4. WHY — record_observation counts against the gate")
    print("=" * 100)
    ro = {}
    for w in ('detailed', 'lean'):
        v = [r['n_ro'] for r in rows if r['prompt'] == w]
        ro[w] = dict(median=st.median(v), mean=st.mean(v),
                     pct_reaching_5=sum(1 for x in v if x >= 5) / len(v),
                     pct_reaching_3=sum(1 for x in v if x >= 3) / len(v))
        print(f"    {w:9} median {st.median(v):.1f}  mean {st.mean(v):.2f}   "
              f"reach 3 ROs {ro[w]['pct_reaching_3']*100:5.1f}%   "
              f"reach 5 ROs {ro[w]['pct_reaching_5']*100:5.1f}%")
    print("\n    The lean prompt does not prescribe six stages, so it logs fewer observations —")
    print("    which is exactly the counter the g3b gate fires on. The prompt manipulation and the")
    print("    exposure mechanism are CONFOUNDED BY CONSTRUCTION on the late-reveal arm.")
    out['ro_counts'] = ro

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(out, open(OUT, 'w'), indent=1)
    print(f"\n  -> {OUT}\n")


if __name__ == '__main__':
    main()
