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

# (tag, model id, description). The tag becomes the filename suffix and the reporting label.
PANEL = [
    ('nemotron', 'nemotron-3-super', 'NVIDIA Nemotron, St. Jude bifrost gateway'),
    ('laguna',   'laguna',           'Laguna, St. Jude bifrost gateway'),
    ('qwen',     os.environ.get('BDG_QWEN_MODEL', 'qwen36-27b-fp8'),
                 'Qwen, St. Jude AIE serving platform'),
]

# artifact kind -> filename stem. `{tag}` is '' for the legacy unsuffixed files.
ARTIFACTS = {
    'cot':     '_cotsummary{tag}.json',    # summarize_cot.py     identity_derivation, rigor
    'support': '_supportscores{tag}.json',  # score_support.py     d1/d2/d3 strategy + support
    'outcome': '_v3scores{tag}.json',       # score_tcga_episode.py mechanism_grounding + gate
}

LEGACY_TAG = 'unrecorded'


def suffix(kind: str, tag: str | None) -> str:
    """Filename suffix for an artifact kind and judge tag. tag=None -> the legacy unsuffixed file."""
    if kind not in ARTIFACTS:
        raise ValueError(f"unknown artifact kind {kind!r}; expected one of {sorted(ARTIFACTS)}")
    return ARTIFACTS[kind].format(tag='' if tag is None else f'_{tag}')


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
