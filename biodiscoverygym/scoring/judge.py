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


# ──────────────────────────────────────────────────────────────────────────────
# p2_experiment_depth  (Phase 2, weight 2)
# Scores Q4: structured experiment with 4 mandatory sub-parts, each stricter
# than Phase 1's experiment_quality (which only checks the brief next_experiment field).
# ──────────────────────────────────────────────────────────────────────────────

_P2_EXPERIMENT_SYSTEM = """\
You are evaluating the quality of a mechanistic follow-up experiment proposed after
a molecular discovery analysis. The agent answered Q4, which requires 4 mandatory
sub-parts. Score each 0 or 1 (no partial credit).

(a) model_with_evidence — Names a SPECIFIC model system (cell line, organoid, PDX,
    or animal model — not generic "cancer cells" or "mouse model") AND cites evidence
    from the dataset (expression, mutation rate, RPPA, or survival) to justify the choice.
    Score 1 only if BOTH: specific model named AND dataset evidence explicitly cited.

(b) perturbation_with_direction — Names a specific genetic or pharmacological target
    (gene + method: "CRISPR KO of X", "treat with inhibitor Y at Z µM") AND states the
    expected direction of effect on the readout. Score 1 only if BOTH: specific target
    named AND expected direction stated.

(c) readout_with_magnitude — Names a specific measurable assay or readout, AND states
    an expected magnitude or direction of change (e.g. "≥2-fold decrease", "p<0.05",
    "IC50 <1 µM"). Score 1 only if BOTH: assay named AND expected change stated.

(d) falsification_criterion — States a concrete result that would REJECT the hypothesis.
    Must be a specific measurable condition. "If the experiment fails" is not sufficient.
    Score 1 if an explicit falsification criterion is stated.

Respond ONLY with valid JSON:
{
  "model_with_evidence": <0 or 1>,
  "perturbation_with_direction": <0 or 1>,
  "readout_with_magnitude": <0 or 1>,
  "falsification_criterion": <0 or 1>,
  "total": <sum 0-4>,
  "notes": "<one sentence identifying the weakest sub-part>"
}
"""


def score_exam_experiment_depth(
    phase2_text: str,
    commit_report: str = "",
    model: str = _DEFAULT_MODEL,
) -> tuple[float, dict]:
    if not phase2_text:
        return 0.0, {"reason": "no Phase 2 answer text found"}
    try:
        client = anthropic.Anthropic()
        commit_summary = f"COMMIT REPORT (first 500 chars):\n{commit_report[:500]}\n\n" if commit_report else ""
        user_msg = (
            f"{commit_summary}"
            f"Q4 MECHANISTIC FOLLOW-UP EXPERIMENT (extract from Phase 2 answers below):\n"
            f"{phase2_text[:4000]}"
        )
        response = client.messages.create(
            model=model,
            max_tokens=512,
            system=_P2_EXPERIMENT_SYSTEM,
            messages=[{"role": "user", "content": user_msg}],
        )
        result = _parse_json(response.content[0].text)
        raw = float(result.get("total", 0))
        return float(raw / 4.0), result
    except Exception as e:
        return 0.0, {"error": str(e)}


# ──────────────────────────────────────────────────────────────────────────────
# p2_mechanistic_integration  (Phase 2, weight 2)
# Evaluates whether the agent weaves multi-modal evidence from all Q1-Q4 answers
# into a coherent, quantitatively grounded causal model.
# ──────────────────────────────────────────────────────────────────────────────

_P2_INTEGRATION_SYSTEM = """\
You are evaluating how well a molecular discovery agent integrates multi-modal evidence
into a mechanistic narrative across Phase 2 follow-up questions (Q1 survival,
Q2 mutations, Q3 cross-modal, Q4 experiment).

Score on three axes (0–4 each):

1. cross_modal_consistency (0–4): Does the mechanistic story weave findings from
   multiple modalities into a single coherent model?
   4 = All four modalities (survival, mutations, RPPA/cross-modal, within-subtype)
       explicitly cited and logically connected in one causal narrative
   3 = Three modalities cited and connected
   2 = Two modalities connected; others mentioned but not integrated
   1 = Modalities listed separately with no integration
   0 = Single modality only, or modalities contradict each other

2. quantitative_grounding (0–4): Are specific numbers from the commit phase cited
   in Q1-Q4, demonstrating that the narrative is data-anchored?
   4 = ≥4 specific numeric values cited (e.g. median OS, log-rank p, OR, RPPA p)
       with explicit reference to committed data
   3 = 2-3 numbers cited with some commit-phase cross-referencing
   2 = 1-2 numbers cited; most answers are qualitative
   1 = Numbers present but not tied to the committed data sweep
   0 = No quantitative values cited

3. causal_coherence (0–4): Is the mechanistic picture a directed causal chain
   (A → B → C → phenotype), not just a list of associated findings?
   4 = Full directed chain with specific molecular actors, consistent across Q1-Q4
   3 = Directional relationships stated between most steps; one link vague
   2 = Two endpoints named with a mechanism implied but chain not traced
   1 = Pathway names cited without causal steps (e.g. "Wnt is activated")
   0 = Correlations stated as mechanism (e.g. "X correlates with poor survival")

Respond ONLY with valid JSON:
{
  "cross_modal_consistency": <int 0-4>,
  "quantitative_grounding": <int 0-4>,
  "causal_coherence": <int 0-4>,
  "total": <sum 0-12>,
  "consistency_note": "<one sentence>",
  "grounding_note": "<one sentence>",
  "coherence_note": "<one sentence>"
}
"""


def score_exam_mechanistic_integration(
    phase2_answers: list[str],
    commit_report: str = "",
    model: str = _DEFAULT_MODEL,
) -> tuple[float, dict]:
    if not phase2_answers:
        return 0.0, {"reason": "no Phase 2 answers found"}
    try:
        client = anthropic.Anthropic()
        answers_text = "\n\n---\n\n".join(phase2_answers)
        commit_summary = commit_report[:800] if commit_report else "(not provided)"
        user_msg = (
            f"COMMIT PHASE REPORT:\n{commit_summary}\n\n"
            f"PHASE 2 Q1-Q4 ANSWERS:\n{answers_text[:4000]}"
        )
        response = client.messages.create(
            model=model,
            max_tokens=512,
            system=_P2_INTEGRATION_SYSTEM,
            messages=[{"role": "user", "content": user_msg}],
        )
        result = _parse_json(response.content[0].text)
        raw = float(result.get("total", 0))
        return float(raw / 12.0), result
    except Exception as e:
        return 0.0, {"error": str(e)}
