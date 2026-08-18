#!/usr/bin/env python3
"""Pre-flight blinding audit — assert that NOTHING the harness showed the agent reveals identity.

This is the gate that makes a clean rerun verifiable rather than assumed. Run it on every new run
BEFORE any analysis. Exit code 1 on any hit, so it can gate a pipeline.

WHAT COUNTS AS A LEAK, AND WHAT DOES NOT — split by AUTHOR, not by channel.
  Assistant turns are never scanned: an agent writing "this looks like LIHC" is the behaviour we
  are MEASURING. Less obviously, neither are cohort names inside tool_results — those payloads are
  mostly stdout from the agent's OWN code coming back, so "=== CONFIRMING OVARIAN CANCER IDENTITY
  ===" is a derivation, not a leak. Flagging either would make derivation indistinguishable from
  leakage, the exact confusion this audit exists to prevent.

  So: cohort names are checked in HARNESS-AUTHORED text only. Harness STATE the agent cannot
  invent — the episode label, an identity-bearing path, "mislead", the arm token — is checked
  everywhere, tool_results included.

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
  results paths   only when an identity token sits INSIDE the path — after the fix the agent's
                  working dir is an opaque `_work/<uuid12>`, which is not a leak

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


def agent_visible_text(ep: dict) -> tuple[str, str]:
    """Split agent-visible text by AUTHOR, because the two need different rules.

    `harness`  — prompts and harness-authored turns. The harness wrote every word, so ANY identity
                 token here is a leak (subject to the by-design arm exemptions).
    `echoed`   — tool_result payloads. These are mostly STDOUT FROM THE AGENT'S OWN CODE round-
                 tripping back. An agent that prints "=== CONFIRMING OVARIAN CANCER IDENTITY ==="
                 has DERIVED that — the behaviour we are measuring — and flagging it would make
                 derivation indistinguishable from leakage.

    The harness does append the codebook narrative into a tool_result, but that narrative reveals
    gene symbols and file paths and never names the cancer (checked). So a cohort name in a
    tool_result is always agent-authored. What the agent CANNOT invent is harness state: the
    episode label, an identity-bearing path, the word "mislead". Those we still flag everywhere.
    """
    harness, echoed = [], []
    for m in ep.get('messages', []):
        role = m.get('role')
        c = m.get('content')
        if isinstance(c, str):
            if role != 'assistant':
                harness.append(c)
            continue
        if not isinstance(c, list):
            continue
        for b in c:
            if not isinstance(b, dict):
                continue
            t = b.get('type')
            if t == 'tool_result':
                r = b.get('content', '')
                if isinstance(r, list):
                    r = ' '.join(x.get('text', '') for x in r if isinstance(x, dict))
                echoed.append(str(r))
            elif t == 'text' and role != 'assistant':
                harness.append(b.get('text', ''))
    return '\n'.join(harness), '\n'.join(echoed)


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
    harness_txt, echoed_txt = agent_visible_text(ep)
    both = harness_txt + '\n' + echoed_txt
    arm, true_c, planted, seed = parse_label(label)
    hits = []

    def find(pat, kind, where):
        m = re.search(pat, where, re.I)
        if m:
            s = max(0, m.start() - 60)
            hits.append((kind, re.sub(r'\s+', ' ', where[s:m.end() + 60]).strip()))

    # ---- ARM-AWARE: some disclosure is the arm's DEFINITION, not a leak ---------------------
    # G0 tells the agent the cohort. G3 tells it a FALSE cohort. Flagging those would make the
    # audit unpassable by construction and would confuse "the experiment worked" with "the
    # blinding failed". What must never appear, in any arm, is the plumbing: the episode label,
    # a results path, the arm token, or the word "mislead" (which reveals the condition is
    # adversarial — an agent that learns that can resist the planted label for the wrong reason,
    # corrupting G3 in the direction that flatters us).
    find(re.escape(label), 'EPISODE LABEL', both)
    # A results path is only a leak if it CARRIES identity. After the blinding fix the agent's
    # working dir is `<base>/_work/<uuid12>`, which is opaque by construction — flagging every
    # `results/...` string would fail a correctly-blinded run forever. So: flag a path only when
    # an identity token sits inside it.
    # ...and the identity tokens are ARM-AWARE for the same reason the prose checks are. The agent
    # names its own files. In G0 it has been TOLD the cohort, so it writes lihc_markers.tsv; in G3
    # it has been told a FALSE cohort, so it writes grouping_luad_final.json. Both land under the
    # agent's own opaque `_work/<uuid12>` dir, and flagging them fails a correctly-blinded run on
    # the strength of the agent repeating what the arm deliberately disclosed to it. Verified on
    # clean_lean/gpt55: the two "leaks" were exactly these, and in the G3 case the TRUE cohort
    # (lusc) appeared in zero paths — the filename carried the planted label, which is the mislead
    # working, not the blinding failing.
    #
    # What stays flagged is what a leak actually looks like: the TRUE cohort in G1/G2/G3 (in G3
    # that is the whole experiment collapsing), the arm token, and the seed — none of which the
    # agent is ever told. The original output_dir defect put the cohort in a HARNESS-controlled
    # path, so it still fires here.
    _disclosed = set()
    if arm == 'g0':
        _disclosed.add(true_c)                    # G0 discloses the real cohort by definition
    elif arm and arm.startswith('g3'):
        _disclosed.add(planted)                   # G3 discloses a false one by definition
    ident = [t for t in (arm, true_c, planted, seed) if t and t not in _disclosed]
    if ident:
        find(r'results[/\\][\w/\\.+-]*(?:' + '|'.join(re.escape(t) for t in ident) + r')[\w/\\.+-]*',
             'IDENTITY-BEARING PATH', both)
    find(r'\bmislead\b', 'MISLEAD KEYWORD', both)
    if arm:
        # Underscore counts as a BOUNDARY, so `_` must be excluded on both sides. In cancer
        # genomics `G1`/`G2` are also cell-cycle phases, and MSigDB ships their pathway names:
        # REACTOME_G2_M_CHECKPOINTS, REACTOME_G1_S_DNA_DAMAGE_CHECKPOINTS. Those are the agent's
        # own enrichment output, not disclosure, and they failed 10/190 correctly-blinded episodes
        # in the 2026-08-05 run. Agent-authored variable names (`mean_g0`) hit the same way.
        #
        # This CANNOT hide a real leak: the arm never appears alone in the plumbing, it appears
        # inside the episode label (`g2_lihc_s42`) or a path — both of which have their own checks
        # above, and both of which still fire. Prose disclosure ("the G2 arm", "arm: G2") also
        # still fires, since neither neighbour is an underscore. Positive controls in the
        # self-test below cover all four cases.
        # HARNESS CHANNEL ONLY, for the same reason cohort names are checked there: the agent
        # cannot disclose the arm to itself. A bare `g0`/`g1` in the echoed channel is the agent's
        # own stdout naming its own two clusters — `THBS2: g0=1.241, g1=3.181, cohen_d=-1.99` is
        # a group contrast it computed, carrying no information it did not already have. Checking
        # `both` failed g0_ov_s42 on exactly that.
        #
        # Tradeoff, stated plainly: a harness string that injected the arm *through a tool_result*
        # would now be missed by THIS check. The realistic forms of that leak — the episode label
        # and an identity-bearing path — are still checked against `both` above, so the gap is
        # narrow and deliberate rather than unnoticed.
        find(rf'(?<![a-z0-9_]){re.escape(arm)}(?![a-z0-9_])', 'ARM TOKEN', harness_txt)
    if seed and arm:
        find(rf'{re.escape(arm)}\W{{0,3}}\w*\W{{0,3}}{re.escape(seed)}', 'ARM+SEED', both)

    # true cohort: disclosed BY DESIGN in G0 only
    if arm != 'g0':
        for pat in COHORT_SYNONYMS.get(true_c or '', []):
            find(pat, 'TRUE COHORT', harness_txt)
    # planted cohort: disclosed BY DESIGN on the mislead arms — that IS the manipulation
    if planted and not arm.startswith('g3'):
        for pat in COHORT_SYNONYMS.get(planted, []):
            find(pat, 'PLANTED COHORT', harness_txt)
    return hits


# (must_fire, label, agent-visible text, description). Both directions matter: a gate that stops
# firing is worthless, and a gate that fires on a correct run gets waived by hand until it is
# ignored. The by-design exemptions are the risky edit, so each is paired with the leak it must
# still catch — G0/G3 disclosure exempt, the TRUE cohort in G3 not exempt.
SELF_TEST = [
    (False, 'g0_lihc_s42', 'saved results/tcga/clean_lean/gpt55/_work/abc123/lihc_markers.tsv',
     'G0 agent filename with the TRUE cohort — G0 discloses it by definition'),
    (False, 'g3b_lusc_mislead_luad_s1',
     'saved results/tcga/clean_lean/gpt55/_work/de45/grouping_luad_final.json',
     'G3 agent filename with the PLANTED cohort — G3 discloses it by definition'),
    (True, 'g3b_lusc_mislead_luad_s1',
     'saved results/tcga/clean_lean/gpt55/_work/de45/grouping_lusc_final.json',
     'G3 path carrying the TRUE cohort — collapses the experiment'),
    (True, 'g2_lihc_s42', 'writing to results/tcga/clean/gpt55/g2_lihc_s42/grouping.json',
     'G2 path carrying the TRUE cohort — the original output_dir defect'),
    (True, 'g1_brca_s7', 'saved results/tcga/clean/gpt55/_work/x/brca_out.tsv',
     'G1 path carrying the TRUE cohort'),
    (True, 'g0_lihc_s42', 'output at results/tcga/clean/gpt55/_work/s42_run/f.tsv',
     'seed in a path — never disclosed in any arm'),
    (True, 'g0_lihc_s42', 'episode g0_lihc_s42 starting', 'episode label in harness text'),
    (True, 'g2_ov_s3', 'this is the mislead condition', 'the word mislead'),
]


def self_test() -> int:
    import tempfile
    print(f"  {'expect':>7} {'fired':>6}         case")
    bad = 0
    for must, label, text, desc in SELF_TEST:
        with tempfile.NamedTemporaryFile('w', suffix='.json', delete=False) as f:
            json.dump({'messages': [{'role': 'user', 'content': text}]}, f)
            p = f.name
        kinds = [k for k, _ in audit_episode(p, label, False)]
        os.unlink(p)
        ok = bool(kinds) == must
        bad += not ok
        print(f"  {str(must):>7} {str(bool(kinds)):>6}  {'ok  ' if ok else 'FAIL'}  {desc}")
    print('\n  SELF-TEST PASS' if not bad else f'\n  SELF-TEST FAILED — {bad} case(s)')
    return 1 if bad else 0


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('run_dirs', nargs='*')
    ap.add_argument('--all', action='store_true', help='the six standard runs')
    ap.add_argument('--verbose', action='store_true', help='print the offending text')
    ap.add_argument('--self-test', action='store_true',
                    help='assert the gate still fires on known leaks and not on by-design disclosure')
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    runs = args.run_dirs or ([
        'results/tcga/_superseded/pilot/ladder/gpt55_20260707', 'results/tcga/_superseded/pilot/lean/gpt55_20260721',
        'results/tcga/_superseded/pilot/ladder/sonnet5_20260713', 'results/tcga/_superseded/pilot/lean/sonnet5_20260722',
        'results/tcga/_superseded/pilot/ladder/gemini35flash_20260716', 'results/tcga/_superseded/pilot/lean/gemini35flash_20260722',
    ] if args.all else [])
    if not runs:
        ap.error('give a run dir or --all')

    grand = 0
    total_eps = 0
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
        total_eps += eps
        status = ('NO EPISODES' if eps == 0 else
                  'CLEAN' if not bad else f'{bad}/{eps} LEAKING')
        print(f"  {run:52} {eps:>4} eps   {status}")
        if kinds:
            print(f"       channels: {dict(kinds)}")
        if args.verbose:
            for lab, k, ctx in examples:
                print(f"       [{lab}] {k}: …{ctx[:150]}…")

    print()
    # An audit that passes because there was nothing to audit is the same failure shape as a
    # judge returning 0.0 on an API error: absence rendering as success. A crashed run leaves
    # episode DIRECTORIES but no episode JSONs, so without this check the gate reports PASS on a
    # run that never happened. Observed for real: the first smoke attempt died on an SSL error and
    # this function returned 0.
    if total_eps == 0:
        print("  FAIL — no episodes found. Nothing was audited.")
        print("  This is not a pass: a crashed run leaves directories but no episode JSONs.")
        print("  Check the run actually completed before reading any gate result.")
        return 1
    if grand:
        print(f"  FAIL — {grand} episode(s) leak identity to the agent.")
        print("  A run in this state cannot support a blinding claim. Fix and re-run.")
        return 1
    print(f"  PASS — {total_eps} episodes audited, no identity-bearing content reached the agent.")
    print("  NOTE: absence of these channels is necessary, not sufficient. Dataset SHAPE")
    print("  (cohort size, mutation-frequency fingerprint) remains recognisable by design.")
    return 0


if __name__ == '__main__':
    sys.exit(main())
