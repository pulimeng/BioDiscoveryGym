"""
LLM judge components for BioDiscoveryGym v2 scoring.

mechanism_grounding — evaluates whether the hypothesis is coherent with
                      submitted genes/pathways and grounded in the data.
experiment_quality  — evaluates whether the proposed experiment is
                      specific, falsifiable, and executable.
"""
from __future__ import annotations

import json

import anthropic

_DEFAULT_MODEL = "claude-sonnet-4-6"

# ──────────────────────────────────────────────────────────────────────────────
# mechanism_grounding  (weight 2)
# ──────────────────────────────────────────────────────────────────────────────

_MECHANISM_SYSTEM = """\
You are a scientific peer reviewer evaluating a molecular discovery submission.

Score the MECHANISM GROUNDING of the submitted hypothesis on three axes:

1. Internal coherence (0–4): Does the mechanistic hypothesis logically follow
   from the submitted top genes and pathway evidence?
   4 = hypothesis directly names genes/pathways submitted and explains how they connect
   3 = hypothesis is consistent with submitted evidence but connection is implicit
   2 = hypothesis is plausible but submitted genes/pathways don't clearly support it
   1 = hypothesis and evidence are loosely related
   0 = hypothesis contradicts or ignores the submitted evidence

2. Data grounding (0–4): Does the hypothesis read like it was derived from data,
   or like a literature recall?
   4 = makes specific quantitative or directional claims traceable to data analysis
   3 = references data-derived findings (survival, mutations, expression patterns)
   2 = mentions data types used but claims are generic
   1 = could have been written without seeing any data
   0 = purely literature recall with no data reference

3. Mechanistic logic (0–4): Is a directional causal chain explicitly traced?
   4 = full chain with direction at each step (A activates B → B phosphorylates C → C drives phenotype X)
   3 = directional relationships stated but one link is missing or vague
   2 = two endpoints named with a plausible mechanism implied but chain not traced
   1 = pathway name + phenotype stated, no causal chain (e.g. "Hedgehog is involved in differentiation")
   0 = correlation stated as mechanism (e.g. "X correlates with poor survival therefore causes it")

Respond ONLY with valid JSON:
{
  "internal_coherence": <int 0-4>,
  "data_grounding": <int 0-4>,
  "mechanistic_logic": <int 0-4>,
  "total": <sum 0-12>,
  "coherence_note": "<one sentence>",
  "grounding_note": "<one sentence>",
  "logic_note": "<one sentence>"
}
"""


def score_mechanism_grounding(
    mechanism_hypothesis: str,
    pathway_evidence: list[str],
    top_genes: list[str],
    model: str = _DEFAULT_MODEL,
) -> tuple[float, dict]:
    if not mechanism_hypothesis:
        return 0.0, {"reason": "no hypothesis submitted"}
    try:
        client = anthropic.Anthropic()
        user_msg = (
            f"TOP GENES: {', '.join(top_genes[:15]) if top_genes else 'none'}\n\n"
            f"PATHWAY EVIDENCE: {'; '.join(pathway_evidence) if pathway_evidence else 'none'}\n\n"
            f"MECHANISM HYPOTHESIS:\n{mechanism_hypothesis}"
        )
        response = client.messages.create(
            model=model,
            max_tokens=512,
            system=_MECHANISM_SYSTEM,
            messages=[{"role": "user", "content": user_msg}],
        )
        result = _parse_json(response.content[0].text)
        raw = float(result.get("total", 0))
        score = float(raw / 12.0)  # normalize to 0-1 (3 axes × 4 pts)
        return score, result
    except Exception as e:
        return 0.0, {"error": str(e)}


# ──────────────────────────────────────────────────────────────────────────────
# experiment_quality  (weight 2)
# ──────────────────────────────────────────────────────────────────────────────

_EXPERIMENT_SYSTEM = """\
You are evaluating whether a proposed next experiment is scientifically actionable.

Score each criterion 0 or 1 (no partial credit):

(a) specific_model     — names a specific cell line, organoid, PDX, or animal model
                         (NOT "cancer cell lines" or "mouse model" — must be specific)
(b) specific_perturbation — names a specific genetic or pharmacological perturbation
                         (gene name + method: "CRISPR knockout of X", "inhibit Y with Z")
(c) specific_measurement — names a specific assay or readout
                         (e.g. "western blot for pAKT", "RNA-seq", "IC50 by CellTiter-Glo")
(d) quantitative_outcome — states an expected direction AND magnitude or threshold
                         (e.g. "≥2-fold reduction", "p<0.05 by log-rank", "IC50 drops below 1 µM")

Respond ONLY with valid JSON:
{
  "specific_model": <0 or 1>,
  "specific_perturbation": <0 or 1>,
  "specific_measurement": <0 or 1>,
  "quantitative_outcome": <0 or 1>,
  "total": <sum 0-4>,
  "notes": "<one sentence on the weakest criterion>"
}
"""


def score_experiment_quality(
    next_experiment: str,
    model: str = _DEFAULT_MODEL,
) -> tuple[float, dict]:
    if not next_experiment:
        return 0.0, {"reason": "no experiment proposed"}
    try:
        client = anthropic.Anthropic()
        response = client.messages.create(
            model=model,
            max_tokens=512,
            system=_EXPERIMENT_SYSTEM,
            messages=[{"role": "user", "content": f"PROPOSED EXPERIMENT:\n{next_experiment}"}],
        )
        result = _parse_json(response.content[0].text)
        raw = float(result.get("total", 0))
        score = float(raw / 4.0)  # normalize to 0-1
        return score, result
    except Exception as e:
        return 0.0, {"error": str(e)}


def _parse_json(text: str) -> dict:
    text = text.strip()
    if "```" in text:
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    return json.loads(text.strip())
