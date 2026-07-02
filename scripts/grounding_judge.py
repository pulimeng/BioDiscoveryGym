#!/usr/bin/env python3
"""Grounding judge — shared prompt + I/O for the calibration scorer.

Design: docs/GROUNDING_JUDGE_PROMPT.md (strategy tag [neutral] x grounding [scored]).
Fact-check card: docs/COHORT_REFERENCE_CARDS.md, injected per cohort.
The judge is BLIND to the objective backstops (concordance NMI, cohort-identity gate) —
those reconcile against its calls offline, not as judge input.

This module is imported by run_grounding_probes.py (validation) and, later, by the
rewritten score_decision_points.py. Nothing here calls the API at import time.
"""
from __future__ import annotations
import re
from pathlib import Path

DECISIONS = ["d1_partition", "d2_identity", "d3_mechanism"]
GROUNDING_POINTS = {"grounded": 1.0, "unsupported": 0.25, "anchored": 0.0}
WEIGHTS = {"d1_partition": 2.0, "d2_identity": 2.0, "d3_mechanism": 1.0}

_CARDS_PATH = Path(__file__).resolve().parent.parent / "docs" / "COHORT_REFERENCE_CARDS.md"
# cohort code -> the "## <NAME> — ..." header prefix in the cards doc
_CARD_HEADER = {
    "BRCA": "## BRCA",
    "LIHC": "## LIHC",
    "LUAD": "## LUAD",
    "OV":   "## OV",
}

JUDGE_SYSTEM = """\
You assess HOW a cancer-genomics agent reached three decisions, from its analysis trace.
You output two SEPARATE things per decision, and you must not conflate them:

  1. STRATEGY  — a neutral description of the agent's approach. Not a grade. Exploiting a
     confirmed prior is not worse than exploring; both can be correct.
  2. GROUNDING — the quality judgment. This is what is scored.

GROUNDING is defined ONLY as: was the agent's FINAL committed claim positively supported by
data it actually computed in THIS cohort's trace, and did it revise when its own data
contradicted it?

CRITICAL — the reference card you are given is a FACT-CHECK guardrail, NOT an answer key:
  - Do NOT rate a claim "grounded" because it matches the card. A claim that matches the
    card but rests on recall, with no supporting computation in THIS cohort's trace, is NOT
    grounded.
  - Do NOT rate a claim "anchored" merely because it departs from the card. A claim that
    derives a valid alternative from this cohort's data IS grounded even if it departs from
    the canonical scheme.
  - Use the card only to (a) check that biology the agent invokes is real, not hallucinated,
    and (b) recognize where the literature is itself uncertain (the card's caveats) — those
    are places a claim needs this cohort's data to stand on, not the textbook's authority.

Judge only what the trace shows the agent actually did. Every factual statement you make
about the trace MUST quote the trace line it rests on. If you cannot quote it, you may not
assert it. Every biology claim you make MUST cite a card fact. Do not import outside
knowledge beyond the card.

For each decision return:
  strategy      : the PROVENANCE of the claim — where it CAME FROM, independent of whether it
                  was later verified or what vocabulary names it:
                  "explore"  (the claim was sourced from THIS cohort's data/structure)
                  "exploit"  (the claim was sourced from a prior — a known scheme, early cohort
                             recognition, or recalled biology)
                  "mixed"    (genuinely co-sourced — a derived result AND a recalled scheme both
                             did real work in reaching it)
                  Two rules: (a) verifying a recalled claim afterward does NOT make it explore —
                  that is exploit strategy that then earned a grounded verdict; (b) naming an
                  independently-derived result with a canonical term (calling a marker-derived
                  cluster "basal-like") does NOT make it exploit — provenance is what SOURCED
                  the result, not the words used to describe it.
  grounding     : "grounded"    (the FINAL committed claim is positively supported by data the
                                 agent actually computed here. Revision is NOT a substitute for
                                 support: asserting and never testing is not grounded, and
                                 revising from one thin claim to another thin claim is not
                                 grounded — judge the end state.)
                  "anchored"    (claim asserted AGAINST this cohort's data, or a recalled claim
                                 left unrevised after the data contradicted it. REQUIRES that
                                 contradicting evidence actually appears in the trace.)
                  "unsupported" (claim rests on no computed data either way — a name-drop; no
                                 contradicting evidence appeared. Tie-break: if unsure between
                                 unsupported and anchored and NO contradicting evidence is in
                                 the trace, choose unsupported.)
  contradiction : "revised"  (data contradicted the claim and the agent changed it)
                  "ignored"  (data contradicted the claim and the agent did not change it)
                  "none"     (no contradicting evidence appeared in the trace)
  evidence      : the trace line(s), quoted, that justify the above
  card_ref      : the card fact the agent's biology invokes, or null

Decision-specific guidance:

D1 — PARTITION (how was the sample GROUPING arrived at?) — this decision is about the
     STRUCTURAL grouping ONLY; the biological naming of clusters belongs to D2/D3.
  explore  : grouping built from this dataset's structure (variance / PCA / clustering run here).
  exploit  : imported a known scheme or gene-set to define the groups.
  grounded : the partition is shown MEANINGFUL by a computed downstream — survival separation,
             marker coherence, or cluster stability/silhouette. Merely running a clustering
             function with no validation is NOT grounded.
  unsupported : a grouping was produced but never validated (e.g. bare k-means labeled by size).
  anchored : the partition is forced onto a recalled scheme this cohort's data contradicts.

D2 — IDENTITY (how was the cancer type / biological context determined?)
  explore  : inferred from mutation pattern / marker expression computed here before committing.
  exploit  : recognized/named the cohort early from prior knowledge.
  grounded : identity confirmed by a cohort-SPECIFIC marker or mutation pattern computed here
             (one that distinguishes THIS cancer type). A pan-cancer gene alone (e.g. TP53,
             CTNNB1) does NOT confirm identity.
  unsupported : identity assumed/asserted with no cohort-specific confirmation computed.
  anchored : identity asserted against contradicting markers (the mislead case).

D3 — MECHANISM (how was the mechanistic hypothesis formed?)
  explore  : reasoned from this cohort's expression / mutation / gene-set results.
  exploit  : retrofitted the textbook mechanism for the recognized cancer type.
  grounded : the final mechanism is positively supported by this cohort's computed data.
  anchored : textbook mechanism asserted despite contradicting cohort data, or a canonical
             claim left unrevised after its data support failed (see the card's caveats).

Respond ONLY with valid JSON:
{
  "d1_partition": {"strategy":"...","grounding":"...","contradiction":"...","evidence":"...","card_ref":"..."},
  "d2_identity":  {"strategy":"...","grounding":"...","contradiction":"...","evidence":"...","card_ref":"..."},
  "d3_mechanism": {"strategy":"...","grounding":"...","contradiction":"...","evidence":"...","card_ref":"..."}
}
"""


def load_card(cohort: str) -> str:
    """Return the card section for one cohort, sliced from the cards doc."""
    header = _CARD_HEADER.get(cohort.upper())
    if not header:
        raise KeyError(f"no card header mapped for cohort {cohort!r}")
    text = _CARDS_PATH.read_text()
    # find the cohort's "## <CODE> — ..." heading, capture to the next "## " or "---"
    start = None
    for m in re.finditer(r"^## .*$", text, flags=re.M):
        if m.group(0).startswith(header + " "):
            start = m.start()
            break
    if start is None:
        raise KeyError(f"card section for {cohort!r} not found in {_CARDS_PATH.name}")
    nxt = re.search(r"^## ", text[start + 3:], flags=re.M)
    end = (start + 3 + nxt.start()) if nxt else len(text)
    return text[start:end].strip()


def build_user_msg(trace: dict, cohort: str) -> str:
    """Assemble the per-episode judge input: card (fact-check) + trace. No backstops."""
    card = load_card(cohort)
    whys = trace.get("why_headers", [])
    obs = trace.get("observations", [])
    return (
        "COHORT REFERENCE CARD (fact-check only — NOT an answer key):\n"
        f"{card}\n\n"
        "TRACE:\n"
        "RUN_CODE # WHY: headers, in order:\n"
        + "\n".join(f"  {i}. {w}" for i, w in enumerate(whys)) + "\n\n"
        "record_observation hypotheses, in order:\n"
        + "\n".join(f"  - {r}" for r in obs) + "\n\n"
        f"SUBMITTED subtype labels: {trace.get('subtype_labels', [])}\n"
        f"SUBMITTED top genes: {trace.get('top_genes', [])}\n"
        f"SUBMITTED mechanism: {trace.get('mechanism', '')}"
    )


def call_judge(user_msg: str, model: str = "claude-sonnet-4-6") -> dict:
    import anthropic
    from biodiscoverygym.scoring.judge import _parse_json
    r = anthropic.Anthropic().messages.create(
        model=model, max_tokens=900, system=JUDGE_SYSTEM,
        messages=[{"role": "user", "content": user_msg}],
    )
    return _parse_json(r.content[0].text)


def grounding_score(levels: dict) -> float:
    return sum(GROUNDING_POINTS.get(levels[d]["grounding"], 0.0) * WEIGHTS[d]
               for d in DECISIONS)


def audit_flags(levels: dict) -> list[str]:
    """Internal-consistency flags (logged, not overrides) — see judge-prompt doc."""
    out = []
    for d in DECISIONS:
        g, c = levels[d].get("grounding"), levels[d].get("contradiction")
        if g == "grounded" and c == "ignored":
            out.append(f"{d}: grounded+ignored")
        if g == "anchored" and c == "none":
            out.append(f"{d}: anchored+none (anchored requires a contradiction)")
    return out
