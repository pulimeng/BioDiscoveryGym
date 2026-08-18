"""Single source of truth for the JUDGE PANEL — who judges, and into which filename.

DESIGN CHANGE (2026-08-18). The panel was 3 passes of ONE model, which measured the judge's
own stochasticity (62% unanimity) and said nothing about family bias. It is now ONE pass by
each of THREE families. That swaps the axis being estimated:

    old: 3 x nemotron          -> "is this judge self-consistent?"     (stochasticity)
    new: nemotron/laguna/qwen  -> "do independent families agree?"     (cross-family robustness)

The new axis is the one a reviewer challenges, but the trade is real and must be stated in the
paper: with one pass per judge, judge noise and judge disagreement are no longer separable, and
cross-family exact agreement was only ~67% on the n=42 pilot check — so expect materially more
no-consensus episodes than the 3-pass design produced. `consensus()` returns None for those;
they must be REPORTED, never silently dropped, or the panel quietly becomes a filter that keeps
only the easy episodes.

WHY A TABLE. Judge identity previously lived in filenames alone: the CoT artifact recorded
`judge_model`, the support and outcome artifacts recorded NOTHING (all 570 clean-run support
files carry judge_model=None), and report generators inferred the judge for the whole run by
reading the CoT summaries — a different artifact, possibly a different model. One roster here,
one suffix convention, provenance written into every artifact.

THE UNSUFFIXED FILES ARE NOT UNTAGGED DATA. `_supportscores.json` / `_v3scores.json` /
`_cotsummary.json` predate this change. They were almost certainly produced by nemotron-3-super
(the default since 24bc72e, which precedes the clean run), but nothing in them SAYS so, and this
project's rule is that a value you inferred is not a value you recorded. They are therefore
tagged `unrecorded`, not `nemotron`. Decide explicitly whether to reuse them as the nemotron
lane or regenerate; do not let a default decide it.
"""
from __future__ import annotations

import os
import sys

# Import the model id rather than restating it. This file first carried its own
# os.environ.get('BDG_QWEN_MODEL', 'qwen36-27b-fp8') default, which went stale the moment the
# id was confirmed against /v1/models as "Qwen/Qwen3.6-27B-FP8" — the roster and the router
# then disagreed about which model the qwen lane meant, silently.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from biodiscoverygym.scoring.judge import QWEN_MODEL as _QWEN_MODEL  # noqa: E402

# (tag, model id, description). The tag becomes the filename suffix and the reporting label.
PANEL = [
    ('nemotron', 'nemotron-3-super', 'NVIDIA Nemotron, St. Jude bifrost gateway'),
    ('laguna',   'laguna',           'Laguna, St. Jude bifrost gateway'),
    ('qwen',     _QWEN_MODEL, 'Qwen, St. Jude AIE serving platform'),
]

# artifact kind -> filename inside the episode's scoring/<judge>/ directory.
ARTIFACTS = {
    'cot':     'cotsummary.json',      # summarize_cot.py      identity_derivation, rigor
    'support': 'supportscores.json',   # score_support.py      d1/d2/d3 strategy + support
    'outcome': 'v3scores.json',        # score_tcga_episode.py mechanism_grounding + gate
}

# Legacy flat filenames, kept ONLY so the migration can find and remove them.
LEGACY_ARTIFACTS = {
    'cot':     ['_cotsummary.json', '_cotsummary_j2.json', '_cotsummary_j3.json'],
    'support': ['_supportscores.json'],
    'outcome': ['_v3scores.json'],
}

LEGACY_TAG = 'unrecorded'

# ── Episode directory layout ──────────────────────────────────────────────────────────────
# An episode directory used to flatten three different provenances into one namespace:
# harness inputs (codebook, gene_map), the AGENT's own analysis outputs (pca_plot.png,
# de_results.csv), and SCORER outputs. Two consequences, both real:
#
#   1. Episode discovery was a glob plus a blocklist of substrings guessed to appear in
#      non-episode filenames ("scores", "trace", "summary", "codebook", "gene_map",
#      "grouping"). That is a guess about names an agent might invent, and agents do invent
#      them — grouping_stage2.json, proposed_grouping.json, grouping_stage2_blinded.json all
#      exist in the clean run. A directory boundary replaces a guess with a fact.
#   2. Removing one judge's artifacts meant pattern-matching filenames rather than deleting a
#      directory.
#
# Harness files stay at the episode root; everything the agent wrote goes to outputs/; every
# scorer artifact goes to scoring/, split by judge so a judge's whole contribution is one
# directory. _v3trace.json sits at scoring/ root because it is derived but judge-INDEPENDENT
# (pure trace statistics, no model call) — filing it under a judge would imply otherwise.
OUTPUTS_DIR = 'outputs'
SCORING_DIR = 'scoring'
TRACE_FILE = 'v3trace.json'

# Files the HARNESS writes. Everything else that is not a scorer artifact is agent-created.
HARNESS_FILES = {'codebook.json', 'gene_map.json', 'sample_codebook.json',
                 'grouping.json', 'grouping_blinded_k5.json'}


def scoring_dir(episode_dir: str, tag: str | None = None) -> str:
    """<episode>/scoring[/<tag>] — the judge's directory, or the scoring root."""
    base = os.path.join(episode_dir, SCORING_DIR)
    return base if tag is None else os.path.join(base, tag)


def artifact_path(episode_dir: str, kind: str, tag: str, *, create: bool = False) -> str:
    """Full path to one judge's artifact of one kind for one episode.

    `create=True` makes the judge directory. Writers should pass it: the atomic-write pattern
    used by these scorers opens `<path>.part` first, which fails with a bare FileNotFoundError
    naming the .part file if the directory is absent — an error that reads like a corrupt
    temp-file bug rather than a missing directory.
    """
    if kind not in ARTIFACTS:
        raise ValueError(f"unknown artifact kind {kind!r}; expected one of {sorted(ARTIFACTS)}")
    d = scoring_dir(episode_dir, tag)
    if create:
        os.makedirs(d, exist_ok=True)
    return os.path.join(d, ARTIFACTS[kind])


def outputs_dir(episode_dir: str) -> str:
    return os.path.join(episode_dir, OUTPUTS_DIR)


def tags() -> list[str]:
    return [t for t, _, _ in PANEL]


def model_for(tag: str) -> str:
    for t, m, _ in PANEL:
        if t == tag:
            return m
    raise ValueError(f"unknown judge tag {tag!r}; expected one of {tags()}")


def consensus(votes: list, *, min_votes: int = 2):
    """Majority label across judges, or None when the panel does not reach one.

    None is a RESULT, not a missing value. With three distinct families a 1/1/1 split is a real
    outcome and means the construct is not robustly measurable for that episode; folding those
    into a majority, or dropping them, both overstate agreement. Callers must count them.
    """
    votes = [v for v in votes if v is not None]
    if len(votes) < min_votes:
        return None
    from collections import Counter
    (top, n), = Counter(votes).most_common(1)
    if sum(1 for v in votes if v == top) * 2 <= len(votes):
        return None                      # no strict majority (e.g. 1/1/1, or 1/1)
    return top
