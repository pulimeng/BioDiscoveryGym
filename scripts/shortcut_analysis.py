#!/usr/bin/env python3
"""Shortcut analysis — how agents reach cohort identity on the blinded arm, and what it costs them.

THE CLAIM THIS SUPPORTS: in the SHORTCUT-AVAILABLE condition, process varied enormously between
agents while the outcome score did not see it.

SCOPE — READ BEFORE QUOTING. 83% of the shortcut signal here is OUR OWN blinding defect (45 of 47
episodes cite the working path; only 8 are agent-generated sample-count recognition). This is a
CONDITION-A result — what agents do when a shortcut is handed to them — not a standing claim about
agents, and it will largely evaporate in the clean rerun BY DESIGN. The paper must not rest on it;
see docs/PILOT_AS_EXPERIMENT.md and the "what carries the argument WITHOUT the leak" section of
manuscript/STORY.md.

It also DISCIPLINES an overstatement worth guarding against. "Blinded agents recognise rather than
derive" is NOT true across the board: 52% of blinded episodes are judged data-derived and 94% carry
a grounded identity claim. Shortcut-taking ranges from 0% (GPT lean) to 81% (Gemini, both prompts).
The finding is the VARIANCE plus the outcome score's blindness to it — not a universal behaviour.

Two shortcut channels, both surface features that bypass biological derivation:
  count-leak   the model names this cohort's cancer with its exact sample size nearby, pre-reveal
               (extract_cot.count_based_identity — tightened, hand-validated probe)
  path-cited   the agent's own reasoning invokes the working directory, which contained the cohort
               name (our own blinding defect — FIXED 48d1db0; see docs/DATA_INTEGRITY_AUDIT.md)

Reported per arm alongside derivation rate, grounding rate and outcome, so the comparison that
matters is visible in one table.

Usage: python scripts/shortcut_analysis.py   ->  manuscript/figures/shortcut_stats.json
"""
import glob, json, os, re, statistics as st, sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import runs_config
from extract_cot import extract_episode, count_based_identity

from scipy.stats import spearmanr

RUNS = runs_config.triples()
SF = ['_cotsummary.json', '_cotsummary_j2.json', '_cotsummary_j3.json']
OUT = 'manuscript/figures/shortcut_stats.json'
# the agent INVOKING the path as a source — not a file merely being saved to it
PATH_CITED = re.compile(
    r"(output_dir|directory|folder|dir(?:ectory)? name|file ?path|path (?:name|contain|suggest))", re.I)


def cohort_sizes():
    sz = {}
    for _, _, r in RUNS:
        for p in glob.glob(f"{r}/g2_*/grouping.json"):
            c = os.path.basename(os.path.dirname(p)).split('_')[1].upper()
            try: sz[c] = len(json.load(open(p)))
            except Exception: pass
    return sz


def consensus(votes):
    c = Counter(votes).most_common()
    return None if len(c) > 1 and c[0][1] == c[1][1] else c[0][0]


def main():
    SIZES = cohort_sizes()
    out = {'arms': {}, 'sizes': SIZES}
    print("=== G2 (blinded): how identity is reached, and what it costs ===")
    print(f"  {'arm':22} {'n':>3} {'derived':>8} {'grounded':>9} {'count':>6} {'path':>5} "
          f"{'ANY':>8} {'outcome':>8}")
    xs, ys = [], []
    tot = Counter()
    for model, prompt, run in RUNS:
        n = der = grd = cnt = pth = anyx = 0
        outs, ep_short = [], []
        for p in sorted(glob.glob(f"{run}/g2_*/g2_*.json")):
            lab = os.path.basename(p)[:-5]
            if lab != os.path.basename(os.path.dirname(p)):
                continue
            n += 1
            d = os.path.dirname(p)
            votes = [json.load(open(os.path.join(d, lab + s))).get('identity_derivation')
                     for s in SF if os.path.exists(os.path.join(d, lab + s))]
            if len(votes) == 3 and consensus(votes) == 'data-derived':
                der += 1
            sp = os.path.join(d, lab + '_supportscores.json')
            if os.path.exists(sp):
                if json.load(open(sp)).get('levels', {}).get('d2_identity', {}).get('support') == 'grounded':
                    grd += 1
            vp = os.path.join(d, lab + '_v3scores.json')
            if os.path.exists(vp):
                outs.append(json.load(open(vp))['normalized'])
            c = pa = False
            try:
                rec = extract_episode(p)
                c = bool(count_based_identity(rec, SIZES))
                txt = ' '.join((x.get('why') or '') + ' ' + (x.get('expects') or '') + ' ' +
                               ' '.join(str(z) for z in (x.get('obs') or {}).values())
                               for x in rec['calls'])
                pa = bool(PATH_CITED.search(txt))
            except Exception:
                pass
            cnt += c; pth += pa
            if c or pa:
                anyx += 1; ep_short.append(lab)
        mo = st.mean(outs) if outs else 0.0
        xs.append(anyx / max(n, 1)); ys.append(mo)
        out['arms'][f"{model}/{prompt}"] = dict(
            n=n, derived=der, grounded=grd, count_leak=cnt, path_cited=pth,
            any_shortcut=anyx, shortcut_rate=anyx / max(n, 1), outcome_g2=mo,
            shortcut_episodes=ep_short)
        for k, v in (('n', n), ('der', der), ('grd', grd), ('cnt', cnt), ('pth', pth), ('any', anyx)):
            tot[k] += v
        print(f"  {model+'/'+prompt:22} {n:>3} {der:>8} {grd:>9} {cnt:>6} {pth:>5} "
              f"{anyx:>3} ={anyx/n*100:>3.0f}% {mo:>8.3f}")
    print(f"  {'TOTAL':22} {tot['n']:>3} {tot['der']:>8} {tot['grd']:>9} {tot['cnt']:>6} "
          f"{tot['pth']:>5} {tot['any']:>3} ={tot['any']/tot['n']*100:>3.0f}%")

    rho, p = spearmanr(xs, ys)
    out['summary'] = dict(
        n_g2=tot['n'], derived=tot['der'], derived_rate=tot['der'] / tot['n'],
        grounded=tot['grd'], grounded_rate=tot['grd'] / tot['n'],
        count_leak=tot['cnt'], path_cited=tot['pth'], any_shortcut=tot['any'],
        shortcut_rate=tot['any'] / tot['n'],
        shortcut_range=[min(xs), max(xs)], outcome_range=[min(ys), max(ys)],
        outcome_spread=max(ys) - min(ys),
        spearman_shortcut_vs_outcome=float(rho), spearman_p=float(p), n_arms=len(xs))

    print("\n=== the comparison that carries the argument ===")
    print(f"  shortcut rate across arms : {min(xs)*100:>4.0f}% .. {max(xs)*100:>4.0f}%   "
          f"(spread {(max(xs)-min(xs))*100:.0f} points)")
    print(f"  G2 outcome across arms    : {min(ys):.3f} .. {max(ys):.3f}   "
          f"(spread {max(ys)-min(ys):.3f})")
    print(f"  correlation shortcut vs outcome: rho={rho:+.2f}, p={p:.2f} (n={len(xs)} arms)")
    print("\n  Process varies across ~80 points; the answer varies across ~3. The arm that takes")
    print("  shortcuts MOST often is not penalised — it scores at the top. That is the claim:")
    print("  an outcome score cannot tell you which kind of agent you have.")
    cnt, pth, anyx = tot['cnt'], tot['pth'], tot['any']
    print(f"\n  DECOMPOSITION — how much of this is OUR defect vs agent-generated:")
    print(f"    count-leak (agent-generated) {cnt:>3}   path-cited (our plumbing) {pth:>3}   "
          f"ANY {anyx:>3}")
    print(f"    share attributable to the path defect: {(anyx-cnt)/max(anyx,1)*100:.0f}%")
    print(f"    survives the fix on current evidence : {cnt}/{tot['n']} = {cnt/tot['n']*100:.0f}%")
    print("    => CONDITION-A result. Not a standing claim about agents; it will largely")
    print("       evaporate in the clean rerun BY DESIGN. Do not build the paper on it.")
    print("\n  GUARD AGAINST OVERSTATEMENT: this is about VARIANCE, not a universal behaviour.")
    print(f"  {tot['der']}/{tot['n']} ({tot['der']/tot['n']*100:.0f}%) of blinded episodes are "
          f"data-derived and {tot['grd']}/{tot['n']} ({tot['grd']/tot['n']*100:.0f}%) are grounded.")
    print("  'Blinded agents recognise rather than derive' is NOT supported across models.")

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(out, open(OUT, 'w'), indent=2)
    print(f"\nwrote {OUT}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
