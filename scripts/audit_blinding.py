#!/usr/bin/env python3
"""Pre-flight blinding audit — assert that NOTHING the harness showed the agent reveals identity.

This is the gate that makes a clean rerun verifiable rather than assumed. Run it on every new run
BEFORE any analysis. Exit code 1 on any hit, so it can gate a pipeline.

WHAT COUNTS AS A LEAK, AND WHAT DOES NOT
  We scan only what the HARNESS PUT IN FRONT OF the agent — tool results, and system/user turns.
  We deliberately do NOT scan the agent's own assistant text, because an agent writing "this looks
  like LIHC" is the behaviour we are trying to MEASURE. Flagging that would make derivation
  indistinguishable from leakage, which is the exact confusion the audit exists to prevent.

ARM-AWARE BY NECESSITY: G0 discloses the true cohort and G3 discloses a FALSE one — those are the
arms' definitions, not leaks. An audit that flagged them could never pass and would conflate "the
manipulation worked" with "the blinding failed". What must never appear in ANY arm is the plumbing.

WHAT WE LOOK FOR (all case-insensitive, in agent-visible text only)
  episode label   g2_lihc_s42 — the whole identifier
  arm token       g0/g1/g2/g3a/g3b as a path-ish or standalone token
  true cohort     the cohort name and its common disease synonyms
  planted cohort  on G3, the mislead label — revealing it is as bad as revealing the truth
  "mislead"       reveals that the condition is adversarial at all
  seed token      s7/s42/s123 alongside an arm, which reconstructs the label
  results paths   any results/... path fragment, the channel we already found

WHY "mislead" MATTERS AS MUCH AS THE COHORT: an agent that learns it is in a deception condition
can resist the planted label for the wrong reason, which corrupts the G3 result in the direction
that flatters us.

Usage:
  python scripts/audit_blinding.py <run_dir> [<run_dir> ...]
  python scripts/audit_blinding.py --all            # the six standard runs
  python scripts/audit_blinding.py <run> --verbose  # show the offending text
"""
import argparse, glob, json, os, re, sys
from collections import defaultdict

COHORT_SYNONYMS = {
    'brca': [r'\bbrca\b', r'\bbreast\b'],
    'lihc': [r'\blihc\b', r'\bliver\b', r'hepatocellul'],
    'luad': [r'\bluad\b', r'lung adeno'],
    'lusc': [r'\blusc\b', r'squamous cell carcinoma of the lung'],
    'ov':   [r'\bov\b', r'\bovarian\b', r'\bhgsoc\b'],
    'prad': [r'\bprad\b', r'\bprostate\b'],
    'ucec': [r'\bucec\b', r'\bendometri'],
}


def agent_visible_text(ep: dict) -> str:
    """Everything the HARNESS showed the agent. Excludes assistant output by design."""
    out = []
    for m in ep.get('messages', []):
        role = m.get('role')
        c = m.get('content')
        if isinstance(c, str):
            if role != 'assistant':
                out.append(c)
            continue
        if not isinstance(c, list):
            continue
        for b in c:
            if not isinstance(b, dict):
                continue
            t = b.get('type')
            if t == 'tool_result':                      # what the executor returned
                r = b.get('content', '')
                if isinstance(r, list):
                    r = ' '.join(x.get('text', '') for x in r if isinstance(x, dict))
                out.append(str(r))
            elif t == 'text' and role != 'assistant':   # harness-authored turns only
                out.append(b.get('text', ''))
    return '\n'.join(out)


def parse_label(label: str):
    """g3a_lusc_mislead_luad_s42 -> (arm, true cohort, planted cohort, seed)."""
    parts = label.split('_')
    arm = parts[0]
    true_c = parts[1] if len(parts) > 1 else None
    planted = parts[3] if ('mislead' in parts and len(parts) > 3) else None
    seed = next((p for p in parts if re.fullmatch(r's\d+', p)), None)
    return arm, true_c, planted, seed


def audit_episode(path: str, label: str, verbose: bool):
    try:
        ep = json.load(open(path))
    except Exception as e:
        return [('unreadable', str(e)[:80])]
    txt = agent_visible_text(ep)
    arm, true_c, planted, seed = parse_label(label)
    hits = []

    def find(pat, kind):
        m = re.search(pat, txt, re.I)
        if m:
            s = max(0, m.start() - 60)
            hits.append((kind, re.sub(r'\s+', ' ', txt[s:m.end() + 60]).strip()))

    # ---- ARM-AWARE: some disclosure is the arm's DEFINITION, not a leak ---------------------
    # G0 tells the agent the cohort. G3 tells it a FALSE cohort. Flagging those would make the
    # audit unpassable by construction and would confuse "the experiment worked" with "the
    # blinding failed". What must never appear, in any arm, is the plumbing: the episode label,
    # a results path, the arm token, or the word "mislead" (which reveals the condition is
    # adversarial — an agent that learns that can resist the planted label for the wrong reason,
    # corrupting G3 in the direction that flatters us).
    find(re.escape(label), 'EPISODE LABEL')
    find(r'results[/\\][\w/\\.+-]*', 'RESULTS PATH')
    find(r'\bmislead\b', 'MISLEAD KEYWORD')
    if arm:
        find(rf'(?<![a-z0-9]){re.escape(arm)}(?![a-z0-9])', 'ARM TOKEN')
    if seed and arm:
        find(rf'{re.escape(arm)}\W{{0,3}}\w*\W{{0,3}}{re.escape(seed)}', 'ARM+SEED')

    # true cohort: disclosed BY DESIGN in G0 only
    if arm != 'g0':
        for pat in COHORT_SYNONYMS.get(true_c or '', []):
            find(pat, 'TRUE COHORT')
    # planted cohort: disclosed BY DESIGN on the mislead arms — that IS the manipulation
    if planted and not arm.startswith('g3'):
        for pat in COHORT_SYNONYMS.get(planted, []):
            find(pat, 'PLANTED COHORT')
    return hits


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('run_dirs', nargs='*')
    ap.add_argument('--all', action='store_true', help='the six standard runs')
    ap.add_argument('--verbose', action='store_true', help='print the offending text')
    args = ap.parse_args()
    runs = args.run_dirs or ([
        'results/tcga/ladder/gpt55_20260707', 'results/tcga/lean/gpt55_20260721',
        'results/tcga/ladder/sonnet5_20260713', 'results/tcga/lean/sonnet5_20260722',
        'results/tcga/ladder/gemini35flash_20260716', 'results/tcga/lean/gemini35flash_20260722',
    ] if args.all else [])
    if not runs:
        ap.error('give a run dir or --all')

    grand = 0
    for run in runs:
        eps, bad = 0, 0
        kinds = defaultdict(int)
        examples = []
        for p in sorted(glob.glob(f"{run}/*/*.json")):
            label = os.path.basename(p)[:-5]
            if label != os.path.basename(os.path.dirname(p)):
                continue
            eps += 1
            hits = audit_episode(p, label, args.verbose)
            if hits:
                bad += 1
                for k, ctx in hits:
                    kinds[k] += 1
                    if len(examples) < 6:
                        examples.append((label, k, ctx))
        grand += bad
        status = 'CLEAN' if not bad else f'{bad}/{eps} LEAKING'
        print(f"  {run:52} {eps:>4} eps   {status}")
        if kinds:
            print(f"       channels: {dict(kinds)}")
        if args.verbose:
            for lab, k, ctx in examples:
                print(f"       [{lab}] {k}: …{ctx[:150]}…")

    print()
    if grand:
        print(f"  FAIL — {grand} episode(s) leak identity to the agent.")
        print("  A run in this state cannot support a blinding claim. Fix and re-run.")
        return 1
    print("  PASS — no identity-bearing content reached the agent in any episode.")
    print("  NOTE: absence of these channels is necessary, not sufficient. Dataset SHAPE")
    print("  (cohort size, mutation-frequency fingerprint) remains recognisable by design.")
    return 0


if __name__ == '__main__':
    sys.exit(main())
