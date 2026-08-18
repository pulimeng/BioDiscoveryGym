#!/usr/bin/env python3
"""Data-integrity audit — the two defects found 2026-07-28, made reproducible.

Both were found by reading episodes rather than aggregates, and neither is visible in any report:
one silently weakens a headline metric, the other silently fabricates a zero.

AUDIT 1 — BLINDING LEAK VIA output_dir
  executor.py injects `output_dir` into the agent's code namespace, and cohort_agent's tool
  description instructs the agent to write results there. The path is
  results/tcga/<arm>/<run>/g2_lihc_s42 — the cohort name is IN THE PATH. On the blinded arms the
  agent can therefore read the answer out of its own working directory.
  Reported at two levels, because they mean different things:
    availability — the cohort-bearing path appears in agent-visible tool output
    use          — the agent's own REASONING invokes the path/directory
  Availability was near-universal in the PILOT (saving a file printed the path); use is what corrupts an
  identity_derivation label.

AUDIT 2 — SILENTLY FAILED IDENTITY GATES
  cohort_identity_verdict is an LLM call that can fail. On failure it records verdict="error".
  Every consumer computes `fooled = (verdict == "mislead_cohort")`, so an errored gate is counted
  as NOT FOOLED — indistinguishable from a model that resisted the mislead. A whole run arm failed
  this way and produced an apparent "0/12 fooled", which was then read as a finding.

Usage: python scripts/audit_integrity.py            # human-readable
       python scripts/audit_integrity.py --json out.json
Exit code 1 if any errored gate is found, so this can gate a release.
"""
import argparse, glob, json, os, re, sys
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from extract_cot import extract_episode

# Runs come from runs_config, like every other analysis script. These six paths used to be
# hardcoded to the pilot, which made this audit unable to say anything about the clean run while
# looking exactly as though it had: `BDG_RUNS=clean python scripts/audit_integrity.py` printed
# pilot counts, pilot model names and "no silent zeros", with no indication it had ignored the
# variable. An integrity audit that silently audits the wrong data is the failure mode it exists
# to catch. triples() already returns (label, prompt, path) — the shape this file wanted.
import runs_config

RUNS = runs_config.triples()
# the agent invoking the PATH as a source, not merely a file being saved to it
# A path mention is only evidence of a leak if the path CARRIES IDENTITY. This pattern used to be
# a bare keyword list — "directory", "folder", "file path" — and on the clean run it flagged 14/126
# G2 episodes as having "reasoned from the path" while `path visible` was 0/126: an agent cannot
# reason from an identity-bearing path that does not exist. Every one of the 14 was benign
# ("saved to the output directory", "grouping file path ready", "investigate the data directory").
#
# audit_blinding.py already learned this in 933e6a9 — "a results path is only a leak if it carries
# identity" — after the same false positive failed a correctly-blinded smoke run. AUDIT 1 never got
# the fix. This is the mirror image of the project's usual defect: instead of a failure rendering
# as a benign value, a non-failure rendered as an alarming one, which erodes trust in the gate just
# as effectively.
#
# Rule: the keyword must appear WITH this episode's cohort token (or a cohort-bearing results path)
# in the surrounding window.
PATH_KEYWORD = re.compile(
    r"(output_dir|directory|folder|dir(?:ectory)? name|file ?path|path (?:name|contain|suggest))", re.I)
_WINDOW = 120


def path_reasoning_hit(text: str, cohort: str) -> bool:
    """True only if a path/dir mention sits next to this cohort's identity."""
    ident = re.compile(rf"(?<![a-z0-9]){re.escape(cohort)}(?![a-z0-9])|results[/\\]\S*{re.escape(cohort)}", re.I)
    for m in PATH_KEYWORD.finditer(text):
        if ident.search(text[max(0, m.start() - _WINDOW):m.end() + _WINDOW]):
            return True
    return False


def episodes(run, prefix='g'):
    for p in sorted(glob.glob(f"{run}/{prefix}*/{prefix}*.json")):
        lab = os.path.basename(p)[:-5]
        if lab == os.path.basename(os.path.dirname(p)):
            yield p, lab


def visible_text(ep):
    """Everything the agent could READ — tool results only."""
    out = []
    for m in ep.get('messages', []):
        c = m.get('content')
        if not isinstance(c, list):
            continue
        for b in c:
            if isinstance(b, dict) and b.get('type') == 'tool_result':
                r = b.get('content', '')
                if isinstance(r, list):
                    r = ' '.join(x.get('text', '') for x in r if isinstance(x, dict))
                out.append(str(r))
    return '\n'.join(out)


def audit_leak():
    print("=" * 78)
    print("  AUDIT 1 — blinding leak via output_dir (G2 = the arm that must be blind)")
    print("=" * 78)
    res = {}
    print(f"  {'arm':26} {'path visible':>13} {'REASONED FROM':>14}")
    for model, prompt, run in RUNS:
        seen = used = n = 0
        used_labels = []
        for p, lab in episodes(run, 'g2_'):
            n += 1
            coh = lab.split('_')[1].lower()
            try:
                ep = json.load(open(p))
            except Exception:
                continue
            if re.search(rf"(results/tcga\S*{re.escape(coh)}|{re.escape(lab)})", visible_text(ep), re.I):
                seen += 1
            try:
                rec = extract_episode(p)
            except Exception:
                continue
            txt = []
            for c in rec['calls']:
                txt += [c.get('why', '') or '', c.get('expects', '') or '']
                if c.get('obs'):
                    txt += [str(v) for v in c['obs'].values()]
            if path_reasoning_hit(' '.join(txt), coh):
                used += 1
                used_labels.append(lab)
        res[f"{model}/{prompt}"] = dict(n=n, path_visible=seen, reasoned_from=used,
                                        episodes=used_labels)
        print(f"  {model+'/'+prompt:26} {seen:>8}/{n:<4} {used:>9}/{n:<4}")
    tv = sum(v['path_visible'] for v in res.values()); tu = sum(v['reasoned_from'] for v in res.values())
    tn = sum(v['n'] for v in res.values())
    print(f"  {'TOTAL':26} {tv:>8}/{tn:<4} {tu:>9}/{tn:<4}")
    # Narrated from the numbers. This used to assert "path visible is near-universal", which was
    # true of the contaminated pilot and flatly contradicts a clean run reporting 0/126 two lines
    # above — the report arguing with its own output.
    if tv == 0:
        print("\n  No identity-bearing path was visible in any episode: the blinding fix holds.")
        print("  'REASONED FROM' is 0 as a consequence — there was no path to reason from.")
    else:
        print(f"\n  An identity-bearing path was visible in {tv}/{tn} episodes. Visibility alone does")
        print("  not corrupt a label — 'REASONED FROM' is the number that does: on those episodes")
        print("  identity may have come from the directory name rather than the biology.")
    return res


def audit_gates():
    print("\n" + "=" * 78)
    print("  AUDIT 2 — identity gates that failed and were counted as 'not fooled'")
    print("=" * 78)
    res, bad = {}, 0
    print(f"  {'arm':26} {'n':>3} {'fooled':>7} {'ERRORED':>8}")
    for model, prompt, run in RUNS:
        c = Counter()
        for p, lab in episodes(run, 'g3'):
            sp = p[:-5] + '_v3scores.json'
            if not os.path.exists(sp):
                continue
            c[json.load(open(sp)).get('cohort_identity_verdict')] += 1
        # UNUSABLE, not just 'error'. A scorer that dies before writing anything leaves a
        # PLACEHOLDER — verdict "", empty raw_scores/diagnostics, normalized 0.0, wall_time ~4e-06 —
        # and `verdict == 'error'` does not match it. One such file
        # (clean_lean/gemini25pro/g3a_ov_mislead_brca_s7) sat inside the exposed denominator as a
        # non-fooled episode. Same silent-zero class this audit exists to catch, one level down.
        n = sum(c.values())
        err = c.get('error', 0) + c.get('', 0) + c.get(None, 0)
        bad += err
        res[f"{model}/{prompt}"] = dict(n=n, verdicts=dict(c), errored=err,
                                        fooled=c.get('mislead_cohort', 0))
        flag = "   <-- UNSCORED (error or empty placeholder), not a real zero" if err else ""
        print(f"  {model+'/'+prompt:26} {n:>3} {c.get('mislead_cohort',0):>7} {err:>8}{flag}")
    if bad:
        print(f"\n  {bad} episodes have NO usable fooling verdict (verdict 'error' or empty).")
        print("  Every consumer computes")
        print("  fooled = (verdict == 'mislead_cohort'), so these are silently counted as NOT")
        print("  fooled — inflating apparent robustness. Re-score them or exclude them explicitly;")
        print("  do not let them pass as zeros.")
    else:
        print("\n  All gates scored — no silent zeros.")
    return res, bad


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--json', type=str, default=None)
    args = ap.parse_args()
    leak = audit_leak()
    gates, bad = audit_gates()
    if args.json:
        os.makedirs(os.path.dirname(args.json) or '.', exist_ok=True)
        # Provenance stamp. runs_config DEFAULTS TO THE CONTAMINATED PILOT, so a bare
        # invocation silently produces pilot numbers into the same path the clean run
        # writes. Without this field the only way to tell them apart is to infer it from
        # which Gemini appears in the payload — which worked by luck, not by design.
        json.dump(dict(source=runs_config.SOURCE, leak=leak, gates=gates, errored_total=bad),
                  open(args.json, 'w'), indent=2)
        print(f"\nwrote {args.json}")
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
