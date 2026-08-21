"""One loader for panel-reduced episode rows — the shape every paper script should consume.

WHY THIS EXISTS. Five generators each had their own copy of "glob the score files, join the
support and CoT artifacts, build a row". Under the pre-panel layout that was merely duplicated;
under a three-judge panel it is dangerous, because each copy would also need its own idea of how
to reduce three judges to one label — and any copy that skipped the question would silently read
whichever judge happened to sort first.

REDUCTION RULES (identical to what explore_exploit.py established):
  categorical  -> majority across judges, or None when the panel splits
  continuous   -> mean across judges, with the spread retained
  no-consensus -> a RESULT, counted, never folded into a majority or dropped silently

The seeded outcome components are identical across judges by construction, so a row's
`raw_scores` may be taken from any one of them; only `normalized`, `mechanism_grounding` and the
identity verdict actually vary.
"""
from __future__ import annotations

import glob
import json
import os
import statistics as st
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import judges_config as J
import runs_config
from g3_exposure import was_exposed

LEVELS = ['d1_partition', 'd2_identity', 'd3_mechanism']


def _read(p):
    return json.load(open(p)) if os.path.exists(p) else None


def mean(xs):
    xs = [x for x in xs if x is not None]
    return st.mean(xs) if xs else None


def load(wave=None, judges=None):
    """[(row dict)], Counter(missing). One row per episode, reduced across the panel."""
    judges = judges or J.tags()
    rows, missing = [], Counter()
    for model, prompt, run in runs_config.triples():
        if wave and prompt != wave:
            continue
        for epdir in sorted(glob.glob(f"{run}/*")):
            lab = os.path.basename(epdir)
            if not os.path.isdir(epdir) or lab.startswith(('_', '.')):
                continue
            if not os.path.exists(os.path.join(epdir, lab + '.json')):
                continue
            per = {}
            for tag in judges:
                v3, sup, cot = (_read(J.artifact_path(epdir, k, tag))
                                for k in ('outcome', 'support', 'cot'))
                if v3 is None and sup is None and cot is None:
                    missing[tag] += 1
                    continue
                per[tag] = (v3 or {}, sup or {}, cot or {})
            if not per:
                missing['episodes_with_no_judge'] += 1
                continue
            v3s = [v for v, _, _ in per.values()]
            sups = [s for _, s, _ in per.values()]
            cots = [c for _, _, c in per.values()]
            outs = [v.get('normalized') for v in v3s if v.get('normalized') is not None]
            parts = lab.split('_')
            r = dict(
                model=model, prompt=prompt, arm=parts[0], label=lab, dir=epdir,
                cohort=parts[1].upper(), seed=parts[-1],
                n_judges=len(per), judges=sorted(per),
                outcome=mean(outs),
                outcome_spread=(max(outs) - min(outs)) if len(outs) > 1 else 0.0,
                verdict=J.consensus([v.get('cohort_identity_verdict') for v in v3s]),
                verdict_split=(len({v.get('cohort_identity_verdict') for v in v3s}) > 1),
                deriv=J.consensus([c.get('identity_derivation') for c in cots]),
                # Raw per-judge votes, kept so agreement/unanimity can be computed downstream.
                # Under the old 3-passes-of-one-model panel this measured stochasticity; across
                # families it measures cross-family agreement, which is a different statistic
                # with the same shape — label it as such wherever it is reported.
                deriv_votes=[c.get('identity_derivation') for c in cots],
                verdict_votes=[v.get('cohort_identity_verdict') for v in v3s],
                rigor=J.consensus([c.get('validation_rigor') for c in cots]),
                support_score=mean([s.get('support_score') for s in sups]),
                raw_scores=(v3s[0].get('raw_scores') or {}),
                exposed=(was_exposed(os.path.join(epdir, lab + '.json'))
                         if parts[0].startswith('g3') else None))
            for lv in LEVELS:
                r[lv + '_strat'] = J.consensus(
                    [(s.get('levels', {}).get(lv) or {}).get('strategy') for s in sups])
                r[lv + '_sup'] = J.consensus(
                    [(s.get('levels', {}).get(lv) or {}).get('support') for s in sups])
            rows.append(r)
    return rows, missing


def require_complete(rows, missing, allow_partial=False):
    """Exit unless every episode carries the full panel. See explore_exploit for the rationale:
    a partial panel does not raise, it just shrinks denominators and prints a plausible table."""
    expected = len(J.tags())
    n_unjudged = missing.get('episodes_with_no_judge', 0)
    if not rows or n_unjudged:
        by = ", ".join(f"{k}={v}" for k, v in sorted(missing.items())) or "n/a"
        sys.exit(f"REFUSING: {len(rows)} episodes judged, {n_unjudged} unjudged ({by}).\n"
                 f"  Run scripts/run_judge.sh, then scripts/panel_status.py.")
    short = [r for r in rows if r['n_judges'] != expected]
    if short and not allow_partial:
        sys.exit(f"REFUSING: {len(short)}/{len(rows)} episodes lack the full {expected}-judge "
                 f"panel. Run scripts/panel_status.py for the shortfall.")
    return rows


# ── Layout helpers for scripts that glob artifacts directly ──────────────────────────────────
# The report generators find files by globbing and then derive sibling paths by string surgery
# (`sp.replace('_supportscores.json', '_v3scores.json')`). That worked when every artifact was a
# suffix on the episode stem in one flat directory. Under scoring/<judge>/<kind>.json the stem
# is gone from the filename and the judge is a directory, so the surgery silently produces paths
# that do not exist — and a glob that matches nothing returns [], which reads as "no data" rather
# than "wrong path". These make the relationship explicit instead.

def artifact_glob(run_dir: str, kind: str, tag: str = '*') -> str:
    """Glob pattern for one artifact kind across a run directory. tag='*' spans all judges."""
    return os.path.join(run_dir, '*', J.SCORING_DIR, tag, J.ARTIFACTS[kind])


def episode_dir_of(artifact_path: str) -> str:
    """<ep>/scoring/<tag>/<kind>.json  ->  <ep>"""
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(artifact_path))))


def label_of(artifact_path: str) -> str:
    return os.path.basename(episode_dir_of(artifact_path))


def episode_json_of(artifact_path: str) -> str:
    d = episode_dir_of(artifact_path)
    return os.path.join(d, os.path.basename(d) + '.json')


def sibling(artifact_path: str, kind: str, tag: str | None = None) -> str:
    """Another artifact for the SAME episode, optionally from a different judge."""
    d = episode_dir_of(artifact_path)
    if tag is None:
        tag = os.path.basename(os.path.dirname(os.path.abspath(artifact_path)))
    return J.artifact_path(d, kind, tag)


def load_all_judges(episode_dir: str, kind: str) -> dict:
    """{tag: parsed artifact} for one episode and kind, judges that have one."""
    out = {}
    for tag in J.tags():
        p = J.artifact_path(episode_dir, kind, tag)
        if os.path.exists(p):
            out[tag] = json.load(open(p))
    return out


# ── Emptiness guards for report generators ───────────────────────────────────────────────────
# Every HTML generator was silently broken by the layout move, and three of the five did not
# fail — they rendered a complete, styled page in which every number was zero ("0 episodes
# each"). An empty glob returns [], and [] formats fine: nothing in those scripts ever asserted
# how many episodes it expected to find. The two that did crash only did so incidentally, by
# dividing by an empty collection.
#
# These make the expectation explicit. `expected_episodes` counts episode DIRECTORIES, which
# exist independently of any judge artifact, so it is a ground truth the loaders can be checked
# against rather than a number derived from the same broken glob.

def expected_episodes(run_dir: str) -> int:
    """Episodes present on disk in a run directory, judged or not."""
    n = 0
    for e in glob.glob(os.path.join(run_dir, '*')):
        lab = os.path.basename(e)
        if os.path.isdir(e) and not lab.startswith(('_', '.')) \
           and os.path.exists(os.path.join(e, lab + '.json')):
            n += 1
    return n


def require_loaded(n_loaded: int, run_dir: str, what: str, *, tolerate_partial: bool = False):
    """Refuse to build a report from nothing, or from a fraction, without saying so.

    A report is a claim about a dataset. Rendering one from zero episodes states that claim
    about nothing at all, and every generator here did exactly that after the layout changed.
    """
    want = expected_episodes(run_dir)
    if want and n_loaded == 0:
        sys.exit(f"REFUSING to build a report: loaded 0 {what} from {run_dir}, "
                 f"which holds {want} episodes.\n"
                 f"  This is a path/layout mismatch, not an empty dataset. Reporting zeros here\n"
                 f"  would render a complete-looking page describing nothing.")
    if want and n_loaded < want and not tolerate_partial:
        sys.exit(f"REFUSING to build a report: loaded {n_loaded}/{want} {what} from {run_dir}.\n"
                 f"  A partial load silently shrinks every denominator below. Run\n"
                 f"  scripts/panel_status.py, or pass tolerate_partial where a gap is expected.")
    return n_loaded


def require_data(n: int, what: str, run_dir: str = '', expected: int | None = None) -> int:
    """Exit loudly when a loader found nothing (or fewer rows than expected).

    Every HTML generator was broken by the layout move and only two of them noticed — and those
    two only because they happened to divide by an empty collection. The other three rendered a
    complete, styled page in which every number was zero: an empty glob returns [], and []
    formats fine. Nothing asserted "I expect 570 episodes", so nothing could tell the difference
    between a run with no data and a run that found no data.

    Call this immediately after loading, before any formatting.
    """
    where = f" under {run_dir}" if run_dir else ""
    if n == 0:
        sys.exit(f"REFUSING: found 0 {what}{where}.\n"
                 f"  A report over zero episodes renders as a page of zeros, not as an error.\n"
                 f"  Check BDG_RUNS and that the panel has been run "
                 f"(scripts/panel_status.py).")
    if expected is not None and n < expected:
        print(f"  WARNING: {n} {what}{where}, expected {expected} — the report below covers a "
              f"SUBSET and every denominator in it is short.", file=sys.stderr)
    return n
