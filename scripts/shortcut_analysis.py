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
import judges_config as J
import runs_config
from extract_cot import extract_episode, count_based_identity, COHORT_DIS

from scipy.stats import spearmanr

RUNS = runs_config.triples()
OUT = 'manuscript/figures/shortcut_stats.json'
# the agent INVOKING the path as a source — not a file merely being saved to it
PATH_CITED = re.compile(
    r"(output_dir|directory|folder|dir(?:ectory)? name|file ?path|path (?:name|contain|suggest))", re.I)


def path_cited_identity(txt, cohort, window=150):
    """True iff the agent names THIS cohort's cancer BESIDE a path mention.

    The bare regex above matches the word "directory", which agents say constantly for reasons
    that have nothing to do with identity: "save grouping.json to the output directory", "list the
    data directory to find a GMT". A hand-read of all 14 episodes it flagged on the clean run
    (2026-08-12) found 14/14 to be exactly that, and ZERO naming the cohort anywhere near the
    match — while `audit_blinding` independently reported no leak on the same lanes.

    Counting those as shortcuts fabricated a defect in a clean run and inflated the one number the
    paper's "does it survive the fix?" claim rests on. Same false-positive mode, same fix, as the
    leak probe in audit_integrity.py: require the identity to be ADJACENT to the mention, mirroring
    count_based_identity's validated window approach.
    """
    dis = COHORT_DIS.get(cohort)
    if not dis:
        return False
    dpat = re.compile(dis, re.I)
    for m in PATH_CITED.finditer(txt):
        if dpat.search(txt[max(0, m.start() - window):m.end() + window]):
            return True
    return False


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
            # Panel consensus across judge FAMILIES, not three passes of one model. An episode
            # the families cannot agree on counts as neither derived nor grounded — it is
            # unresolved, and inflating either rate with a tie-break would misstate exactly the
            # quantity this section is about.
            votes = [json.load(open(q)).get('identity_derivation')
                     for q in (J.artifact_path(d, 'cot', t) for t in J.tags())
                     if os.path.exists(q)]
            if J.consensus(votes) == 'data-derived':
                der += 1
            sups = [json.load(open(q)) for q in
                    (J.artifact_path(d, 'support', t) for t in J.tags()) if os.path.exists(q)]
            if J.consensus([(x.get('levels', {}).get('d2_identity') or {}).get('support')
                            for x in sups]) == 'grounded':
                grd += 1
            v3s = [json.load(open(q)) for q in
                   (J.artifact_path(d, 'outcome', t) for t in J.tags()) if os.path.exists(q)]
            if v3s:
                outs.append(sum(x['normalized'] for x in v3s) / len(v3s))
            c = pa = False
            try:
                rec = extract_episode(p)
                c = bool(count_based_identity(rec, SIZES))
                txt = ' '.join((x.get('why') or '') + ' ' + (x.get('expects') or '') + ' ' +
                               ' '.join(str(z) for z in (x.get('obs') or {}).values())
                               for x in rec['calls'])
                pa = path_cited_identity(txt, rec.get('cohort'))
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
    # NARRATE FROM THE NUMBERS, never alongside them. This block used to print a fixed sentence —
    # "Process varies across ~80 points; the answer varies across ~3 … the arm that takes shortcuts
    # MOST often is not penalised, it scores at the top" — describing the pilot. On the clean run
    # the spread is 33 points, and the worst-shortcutting arm has the LOWEST outcome, so the stored
    # prose contradicted the table printed three lines above it. A reviewer running the code sees
    # both at once.
    _arms = list(out['arms'].items())
    _worst = max(_arms, key=lambda kv: kv[1]['shortcut_rate'])          # most shortcuts
    _rank = sorted(_arms, key=lambda kv: -kv[1]['outcome_g2'])          # best outcome first
    _pos = [k for k, _ in _rank].index(_worst[0]) + 1
    _place = ('the TOP' if _pos == 1 else 'the BOTTOM' if _pos == len(_rank) else f'#{_pos}')
    print(f"\n  Process varies across {(max(xs)-min(xs))*100:.0f} points; the answer varies across "
          f"{(max(ys)-min(ys))*100:.0f}. The arm that takes")
    print(f"  shortcuts MOST often ({_worst[0]}, {_worst[1]['shortcut_rate']*100:.0f}%) ranks "
          f"{_place} of {len(_rank)} on outcome ({_worst[1]['outcome_g2']:.3f}).")
    if p < 0.05:
        _verdict = ("Outcome TRACKS shortcut-taking here — the dissociation claim does NOT hold "
                    "on this run set.") if rho < 0 else (
                   "Outcome rises with shortcut-taking — inspect before claiming anything.")
    else:
        _verdict = (f"The rank correlation is rho={rho:+.2f} at p={p:.2f} with n={len(xs)} arms: "
                    "directional, NOT established.")
    print(f"  {_verdict}")
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
    # Provenance stamp. runs_config DEFAULTS TO THE CONTAMINATED PILOT, so a bare
    # invocation silently produces pilot numbers into the same path the clean run
    # writes. Without this field the only way to tell them apart is to infer it from
    # which Gemini appears in the payload — which worked by luck, not by design.
    out['source'] = runs_config.SOURCE
    json.dump(out, open(OUT, 'w'), indent=2)
    print(f"\nwrote {OUT}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
