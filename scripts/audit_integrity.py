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
  Availability is near-universal (saving a file prints the path); use is what actually corrupts an
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

RUNS = [
    ('GPT-5.5', 'detailed', 'results/tcga/ladder/gpt55_20260707'),
    ('GPT-5.5', 'lean', 'results/tcga/lean/gpt55_20260721'),
    ('Sonnet 5', 'detailed', 'results/tcga/ladder/sonnet5_20260713'),
    ('Sonnet 5', 'lean', 'results/tcga/lean/sonnet5_20260722'),
    ('Gemini 3.5 Flash', 'detailed', 'results/tcga/ladder/gemini35flash_20260716'),
    ('Gemini 3.5 Flash', 'lean', 'results/tcga/lean/gemini35flash_20260722'),
]
# the agent invoking the PATH as a source, not merely a file being saved to it
PATH_REASONING = re.compile(
    r"(output_dir|directory|folder|dir(?:ectory)? name|file ?path|path (?:name|contain|suggest))", re.I)


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
            if PATH_REASONING.search(' '.join(txt)):
                used += 1
                used_labels.append(lab)
        res[f"{model}/{prompt}"] = dict(n=n, path_visible=seen, reasoned_from=used,
                                        episodes=used_labels)
        print(f"  {model+'/'+prompt:26} {seen:>8}/{n:<4} {used:>9}/{n:<4}")
    tv = sum(v['path_visible'] for v in res.values()); tu = sum(v['reasoned_from'] for v in res.values())
    tn = sum(v['n'] for v in res.values())
    print(f"  {'TOTAL':26} {tv:>8}/{tn:<4} {tu:>9}/{tn:<4}")
    print("\n  'path visible' is near-universal because saving a file echoes its path — that alone")
    print("  does not corrupt a label. 'REASONED FROM' is the number that does: on those episodes")
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
        n = sum(c.values()); err = c.get('error', 0); bad += err
        res[f"{model}/{prompt}"] = dict(n=n, verdicts=dict(c), errored=err,
                                        fooled=c.get('mislead_cohort', 0))
        flag = "   <-- UNSCORED, not a real zero" if err else ""
        print(f"  {model+'/'+prompt:26} {n:>3} {c.get('mislead_cohort',0):>7} {err:>8}{flag}")
    if bad:
        print(f"\n  {bad} episodes have NO usable fooling verdict. Every consumer computes")
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
        json.dump(dict(leak=leak, gates=gates, errored_total=bad), open(args.json, 'w'), indent=2)
        print(f"\nwrote {args.json}")
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
