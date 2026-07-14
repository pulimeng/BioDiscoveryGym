#!/usr/bin/env python3
"""Support judge — shared prompt + I/O for the calibration scorer.

Design: docs/SUPPORT_JUDGE_PROMPT.md (strategy tag [neutral] x support [scored]).
Fact-check card: docs/COHORT_REFERENCE_CARDS.md, injected per cohort.
The judge is BLIND to the objective backstops (concordance NMI, cohort-identity gate) —
those reconcile against its calls offline, not as judge input.

This module is imported by run_support_probes.py (validation) and, later, by the
rewritten score_decision_points.py. Nothing here calls the API at import time.
"""
from __future__ import annotations
import re
from pathlib import Path

DECISIONS = ["d1_partition", "d2_identity", "d3_mechanism"]
SUPPORT_POINTS = {"grounded": 1.0, "unsupported": 0.25, "anchored": 0.0}
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
  2. SUPPORT — the quality judgment. This is what is scored.

SUPPORT is defined ONLY as: was the agent's FINAL committed claim positively supported by
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
  support     : "grounded"    (the FINAL committed claim is positively supported by data the
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
  recall_type : (D2 ONLY) a finer typology of HOW identity was handled — an orthogonal label you
                assign for EVERY episode (honest, blinded, or mislead). Choose exactly one:
                "grounded_recall"  : NAMED the disease from prior knowledge AND backed it with a
                                     cohort-specific marker/mutation computed HERE (the efficient-
                                     expert move). Pairs with support=grounded.
                "derived"          : INFERRED identity from this cohort's computed drivers/markers
                                     rather than recalling a name first. Pairs with support=grounded.
                "bare_assertion"   : NAMED a specific disease but never computed anything to confirm
                                     it. Pairs with support=unsupported.
                "no_identification": never engaged disease identity AT ALL — worked only with generic
                                     "cluster 0/1" / "molecular subtypes", proposed no cancer type.
                                     Pairs with support=unsupported. (Distinct from bare_assertion:
                                     no disease name was even offered.)
                "wrong_disease"    : committed to an identity this cohort's data contradicts — the
                                     recalled/mislead cancer asserted against markers. Pairs with
                                     support=anchored.
                CONSISTENCY (required): grounded_recall/derived → support=grounded; wrong_disease →
                support=anchored; bare_assertion/no_identification → support=unsupported.

D3 — MECHANISM (how was the mechanistic hypothesis formed?)
  explore  : reasoned from this cohort's expression / mutation / gene-set results.
  exploit  : retrofitted the textbook mechanism for the recognized cancer type.
  grounded : the final mechanism is positively supported by this cohort's computed data.
  anchored : textbook mechanism asserted despite contradicting cohort data, or a canonical
             claim left unrevised after its data support failed (see the card's caveats).

Record your verdict by calling the record_support tool, with strategy / support /
contradiction / evidence / card_ref for each of d1_partition, d2_identity, d3_mechanism —
PLUS recall_type for d2_identity. Keep evidence to ONE short phrase (a brief quote or
paraphrase) — no line breaks, no long excerpts.
"""

_ENUMS = {
    "strategy": ["explore", "exploit", "mixed"],
    "support": ["grounded", "unsupported", "anchored"],
    "contradiction": ["revised", "ignored", "none"],
}
# D2-only: finer identity-handling typology (judge-emitted so it's auditable, not a regex).
RECALL_TYPES = ["grounded_recall", "derived", "bare_assertion", "no_identification", "wrong_disease"]
# recall_type -> the support level it must co-occur with (consistency backstop, see audit_flags)
_RECALL_SUPPORT = {"grounded_recall": "grounded", "derived": "grounded", "wrong_disease": "anchored",
                   "bare_assertion": "unsupported", "no_identification": "unsupported"}
_DECISION_SCHEMA = {
    "type": "object",
    "properties": {
        "strategy": {"type": "string", "enum": _ENUMS["strategy"]},
        "support": {"type": "string", "enum": _ENUMS["support"]},
        "contradiction": {"type": "string", "enum": _ENUMS["contradiction"]},
        "evidence": {"type": "string", "description": "one short quoted phrase or paraphrase from the trace; no line breaks"},
        "card_ref": {"type": "string", "description": "the card fact invoked, or empty string"},
    },
    "required": ["strategy", "support", "contradiction", "evidence"],
}
# d2_identity carries an extra recall_type field; d1/d3 use the base schema.
_D2_SCHEMA = {
    "type": "object",
    "properties": {**_DECISION_SCHEMA["properties"],
                   "recall_type": {"type": "string", "enum": RECALL_TYPES,
                                   "description": "identity-handling typology; see D2 guidance"}},
    "required": _DECISION_SCHEMA["required"] + ["recall_type"],
}
_SUPPORT_TOOL = {
    "name": "record_support",
    "description": "Record the per-decision strategy (neutral), support (scored), and contradiction verdicts.",
    "input_schema": {
        "type": "object",
        "properties": {d: (_D2_SCHEMA if d == "d2_identity" else _DECISION_SCHEMA) for d in DECISIONS},
        "required": DECISIONS,
    },
}


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


def _is_complete(v: dict) -> bool:
    """All three decisions present with their required sub-fields, plus recall_type on d2.
    DeepSeek (tool_choice='auto') doesn't enforce the schema, so we validate + retry ourselves —
    this is what a missing 'd2_identity' (or any dropped decision) failed on before."""
    if not isinstance(v, dict):
        return False
    for d in DECISIONS:
        dd = v.get(d)
        if not isinstance(dd, dict) or not all(dd.get(k) for k in _DECISION_SCHEMA["required"]):
            return False
    return bool((v.get("d2_identity") or {}).get("recall_type"))


def call_judge(user_msg: str, model: str = "deepseek-v4-pro") -> dict:
    """Force the verdict through tool-use (valid JSON + enum-checked levels). Routes by model
    so the judge can be a NEUTRAL family not in the benchmarked set (self-preference bias):
    claude* -> Anthropic; deepseek*/gpt*/o* -> OpenAI-compatible (DeepSeek endpoint for deepseek*)."""
    ml = model.lower()
    if ml.startswith("claude") or "claude" in ml:
        return _judge_anthropic(user_msg, model)
    return _judge_openai_compatible(user_msg, model)


def _judge_anthropic(user_msg: str, model: str) -> dict:
    import anthropic
    r = anthropic.Anthropic().messages.create(
        model=model, max_tokens=2500, system=JUDGE_SYSTEM,
        tools=[_SUPPORT_TOOL],
        tool_choice={"type": "tool", "name": "record_support"},
        messages=[{"role": "user", "content": user_msg}],
    )
    for b in r.content:
        if getattr(b, "type", None) == "tool_use" and b.name == "record_support":
            return b.input
    raise ValueError(f"no record_support tool_use in response (stop_reason={r.stop_reason})")


def _judge_openai_compatible(user_msg: str, model: str) -> dict:
    """DeepSeek (the neutral judge) + OpenAI, via the OpenAI SDK with forced tool-calling.
    DeepSeek is served at api.deepseek.com and is OpenAI-compatible incl. tool calls."""
    import openai, json, os
    ml = model.lower()
    if ml.startswith("deepseek"):
        client = openai.OpenAI(base_url="https://api.deepseek.com",
                               api_key=os.environ.get("DEEPSEEK_API_KEY"))
        # V4 Pro is a thinking model: forced tool_choice is rejected in thinking mode, so use
        # "auto" (the prompt instructs it to call record_support). The budget must cover BOTH
        # the reasoning AND the tool-call JSON — too small and the args truncate mid-string
        # ("Unterminated string" on json.loads). Start generous, and if the response is still
        # cut off (finish_reason="length") retry once with a bigger budget.
        tok_key, base_tokens, retry_tokens = "max_tokens", 16000, 32000
        tool_choice = "auto"
    else:                                       # openai gpt/o-series
        client = openai.OpenAI()
        tok_key, base_tokens, retry_tokens = "max_completion_tokens", 4000, 8000
        tool_choice = {"type": "function", "function": {"name": "record_support"}}
    tool = {"type": "function", "function": {
        "name": "record_support", "description": _SUPPORT_TOOL["description"],
        "parameters": _SUPPORT_TOOL["input_schema"]}}

    def _call(max_toks):
        return client.chat.completions.create(
            model=model,
            messages=[{"role": "system", "content": JUDGE_SYSTEM},
                      {"role": "user", "content": user_msg}],
            tools=[tool], tool_choice=tool_choice, **{tok_key: max_toks})

    def _parse(r):
        msg = r.choices[0].message
        if getattr(msg, "tool_calls", None):
            return json.loads(msg.tool_calls[0].function.arguments)
        # fallback: model emitted text instead of a tool call — extract the JSON verdict
        from biodiscoverygym.scoring.judge import _parse_json
        return _parse_json(msg.content or "")

    # Retry on BOTH failure modes of the thinking model at tool_choice="auto":
    #   (a) truncation → finish_reason="length" → bump the budget
    #   (b) incomplete/omitted decision (e.g. missing d2_identity) → verdict fails _is_complete
    last = None
    for attempt in range(3):
        r = _call(base_tokens if attempt == 0 else retry_tokens)
        if r.choices[0].finish_reason == "length":     # truncated → retry bigger
            r = _call(retry_tokens)
        try:
            v = _parse(r)
        except Exception:                              # malformed/truncated JSON → reroll
            v = None
        if _is_complete(v):
            return v
        last = v
    raise ValueError(f"{model} judge returned an incomplete verdict after 3 attempts "
                     f"(missing a decision or recall_type); got keys={list((last or {}).keys())}")


def support_score(levels: dict) -> float:
    return sum(SUPPORT_POINTS.get(levels[d]["support"], 0.0) * WEIGHTS[d]
               for d in DECISIONS)


def audit_flags(levels: dict) -> list[str]:
    """Internal-consistency flags (logged, not overrides) — see judge-prompt doc."""
    out = []
    for d in DECISIONS:
        g, c = levels[d].get("support"), levels[d].get("contradiction")
        if g == "grounded" and c == "ignored":
            out.append(f"{d}: grounded+ignored")
        if g == "anchored" and c == "none":
            out.append(f"{d}: anchored+none (anchored requires a contradiction)")
    # recall_type must co-occur with the support level the rubric ties it to (identity only)
    d2 = levels.get("d2_identity") or {}
    rt, sup = d2.get("recall_type"), d2.get("support")
    if rt and _RECALL_SUPPORT.get(rt) and _RECALL_SUPPORT[rt] != sup:
        out.append(f"d2_identity: recall_type={rt} inconsistent with support={sup} "
                   f"(expected {_RECALL_SUPPORT[rt]})")
    return out
