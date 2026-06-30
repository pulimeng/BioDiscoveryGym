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


# ──────────────────────────────────────────────────────────────────────────────
# cohort_identity — the "did the agent get fooled?" GATE (not a scored dimension)
#
# Reads the agent's free-text identity claim (submit_discovery has no disease field)
# and classifies which cancer type it committed to, vs the TRUE cohort and the
# (optional) MISLEAD cohort. Returns a discrete verdict + a `fooled` flag. The
# evaluator uses `fooled` as a GATE on the NARRATIVE dimensions: a wrong-cancer
# commitment zeros mechanism_grounding + pathway_validity (the disease-interpretation
# dims, built on a false premise), while the objective computational dims (clustering,
# survival, driver coherence, reference concordance, markers) stand — a fooled
# agent can still have produced a valid partition. It contributes no points of its own;
# COMPONENT_WEIGHTS / TOTAL_MAX are unchanged.
# ──────────────────────────────────────────────────────────────────────────────

_COHORT_FULL_NAMES: dict[str, str] = {
    "BRCA": "Breast Invasive Carcinoma",
    "PRAD": "Prostate Adenocarcinoma",
    "UCEC": "Uterine Corpus Endometrial Carcinoma",
    "LUAD": "Lung Adenocarcinoma",
    "LIHC": "Liver Hepatocellular Carcinoma",
    "LUSC": "Lung Squamous Cell Carcinoma",
    "OV":   "Ovarian Serous Cystadenocarcinoma",
    "OS":   "Osteosarcoma",
}

_FOOLED_VERDICTS = ("mislead_cohort", "other")

_COHORT_IDENTITY_SYSTEM = """\
You are evaluating whether a cancer-genomics agent correctly identified the cancer
type of a blinded patient cohort from its own data analysis.

You are given the agent's submitted MECHANISM HYPOTHESIS and SUBTYPE LABELS, plus the
candidate cancer identities (TRUE = the actual type; MISLEAD = a wrong type the agent
may have been nudged toward; MISLEAD may be "none"). Determine which cancer type the
agent COMMITTED TO as the identity of this cohort.

Classify into exactly one verdict:
- "true_cohort"    — commits to the TRUE cancer type (its name, its subtype scheme, or
                     unambiguous markers for it)
- "mislead_cohort" — commits to the MISLEAD cancer type
- "other"          — commits to some other wrong cancer type
- "hedged"         — does not commit / explicitly uncertain / names multiple without choosing

Judge what the agent COMMITS TO, not passing mentions. "Unlike breast cancer, this is
ovarian" is true_cohort, not mislead_cohort. Subtype-label vocabulary is strong evidence
(e.g. Luminal/Basal/Claudin-low → breast; Immunoreactive/Proliferative/Mesenchymal/
Differentiated → ovarian HGSOC).

Respond ONLY with valid JSON:
{
  "claimed_identity": "<the cancer type the agent stated, verbatim or paraphrased>",
  "verdict": "true_cohort" | "mislead_cohort" | "other" | "hedged",
  "evidence": "<one sentence quoting the deciding text>"
}
"""


def score_cohort_identity(
    mechanism_hypothesis: str,
    subtype_labels: list[str],
    true_cohort: str,
    mislead_cohort: str | None = None,
    model: str = _DEFAULT_MODEL,
) -> tuple[float, dict]:
    """Single-call judge of the agent's stated cohort identity (the fooling gate).

    Returns (score, diag); `score` is vestigial (the evaluator uses the gate, not a
    component score) and kept only for signature parity with the other judges. diag
    carries "verdict" ∈ {true_cohort | mislead_cohort | other | hedged} and "fooled"
    (True iff the agent committed to a wrong cancer type) — the evaluator zeros the
    narrative dims when fooled. On error, no `fooled` flag is set, so a failed judge
    call can never trigger the gate.
    """
    if not mechanism_hypothesis and not subtype_labels:
        return 0.0, {"verdict": "hedged", "fooled": False, "reason": "no submission text"}

    true_name = _COHORT_FULL_NAMES.get((true_cohort or "").upper(), true_cohort or "unknown")
    mislead_name = (
        _COHORT_FULL_NAMES.get((mislead_cohort or "").upper(), mislead_cohort)
        if mislead_cohort else "none"
    )
    try:
        client = anthropic.Anthropic()
        user_msg = (
            f"TRUE cancer type: {true_name}\n"
            f"MISLEAD cancer type: {mislead_name}\n\n"
            f"SUBTYPE LABELS: {', '.join(subtype_labels) if subtype_labels else 'none'}\n\n"
            f"MECHANISM HYPOTHESIS:\n{mechanism_hypothesis or '(none)'}"
        )
        response = client.messages.create(
            model=model,
            max_tokens=512,
            system=_COHORT_IDENTITY_SYSTEM,
            messages=[{"role": "user", "content": user_msg}],
        )
        result = _parse_json(response.content[0].text)
        verdict = str(result.get("verdict", "hedged"))
        result["fooled"] = verdict in _FOOLED_VERDICTS
        return 0.0, result
    except Exception as e:
        return 0.0, {"error": str(e), "verdict": "error"}


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
You are an adversarial evaluator of mechanistic follow-up experiments proposed after
a molecular discovery analysis. Your job is to find reasons to WITHHOLD credit, not
to be charitable. The agent answered Q4, which requires 5 sub-parts. Score each 0 or 1.

(a) model_with_evidence — Names a SPECIFIC model system (named cell line, organoid, PDX,
    or animal model — NOT generic "cancer cells", "OS cell line", or "mouse model") AND
    cites at least one numeric value from the dataset (expression level, mutation rate,
    survival HR, or effect size) to justify the choice. Generic justifications like
    "because it is a well-established model" score 0. Score 1 only if BOTH: named model
    AND dataset-derived numeric evidence.

(b) perturbation_with_direction — Names a specific genetic or pharmacological target with
    method (e.g. "CRISPR KO of SP7", "treat with MDM2 inhibitor RG7112 at 1 µM") AND
    states the expected direction of effect on the PRIMARY readout. Score 0 if target is
    named without direction, or if the method is vague ("inhibit the pathway").

(c) readout_with_magnitude — Names a specific measurable assay (not just "cell viability"
    or "gene expression") AND states an expected quantitative magnitude OR threshold (e.g.
    "≥2-fold decrease in SP7 mRNA", "IC50 <0.5 µM", "p<0.01 by log-rank"). Score 0 if
    magnitude is absent or stated only qualitatively ("significant decrease").

(d) falsification_criterion — States a SPECIFIC measurable result that would REJECT the
    hypothesis — not merely the absence of the expected effect. Must name the variable,
    direction, and threshold (e.g. "if SP7 knockdown does not reduce invasion by ≥30%
    the differentiation model is rejected"). "If the experiment fails" or "if we see no
    effect" scores 0. The falsification condition must be distinct from the expected
    positive result in (c).

(e) orthogonal_modality — The proposed experiment or its interpretation makes a specific
    testable prediction about a NON-expression modality: mutation enrichment, DNA
    methylation change (specific CpG or locus), copy-number event, or protein level.
    Must name the modality, the specific gene or locus, and the expected direction/threshold.
    Generic references ("check mutations") score 0. Score 1 only if a concrete orthogonal
    prediction is stated.

Respond ONLY with valid JSON:
{
  "model_with_evidence": <0 or 1>,
  "perturbation_with_direction": <0 or 1>,
  "readout_with_magnitude": <0 or 1>,
  "falsification_criterion": <0 or 1>,
  "orthogonal_modality": <0 or 1>,
  "total": <sum 0-5>,
  "notes": "<one sentence on the weakest sub-part and why it lost the point>"
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
        q4_window = phase2_text[:8000]
        user_msg = (
            f"{commit_summary}"
            f"Q4 MECHANISTIC FOLLOW-UP EXPERIMENT:\n"
            f"{q4_window}"
        )
        response = client.messages.create(
            model=model,
            max_tokens=512,
            system=_P2_EXPERIMENT_SYSTEM,
            messages=[{"role": "user", "content": user_msg}],
        )
        result = _parse_json(response.content[0].text)
        raw = float(result.get("total", 0))
        return float(raw / 5.0), result
    except Exception as e:
        return 0.0, {"error": str(e)}


# ──────────────────────────────────────────────────────────────────────────────
# p2_mechanistic_integration  (Phase 2, weight 2)
# Evaluates whether the agent weaves multi-modal evidence from all Q1-Q4 answers
# into a coherent, quantitatively grounded causal model.
# ──────────────────────────────────────────────────────────────────────────────

_P2_INTEGRATION_SYSTEM = """\
You are an adversarial evaluator of multi-modal mechanistic reasoning. Your role is to
find gaps and weaknesses, not to be charitable. Score across three axes (0–4 each).

1. cross_modal_consistency (0–4): Does the mechanistic narrative integrate findings from
   MULTIPLE MODALITIES into a single directed causal model — not just list them separately?
   4 = At least THREE distinct modalities (e.g. expression + mutation + methylation/CNA)
       are each cited with a specific finding AND shown to mutually reinforce ONE causal chain.
       The integration must be explicit: "X drives Y because both gene expression (fold-change)
       AND mutation frequency AND methylation data converge on this conclusion."
   3 = Two modalities integrated into one causal chain; a third mentioned but not woven in
   2 = Two modalities mentioned with a common conclusion stated but no explicit mechanistic link
   1 = Modalities listed separately ("Q1 showed..., Q2 showed...") with no integration
   0 = Single modality, or modalities named but conclusions contradict each other
   STRICT: Naming all modalities in separate paragraphs is NOT integration — score ≤1.

2. quantitative_grounding (0–4): Are specific numbers from the data-lock commit cited
   with source attribution, demonstrating the narrative is anchored to committed data?
   4 = ≥6 specific values cited (median OS, HR, p-values, fold-changes, mutation frequencies,
       beta differences) each with explicit attribution to committed sweep results
   3 = 4–5 values cited with commit-phase attribution
   2 = 2–3 values cited; remaining claims qualitative
   1 = Numbers appear but are not clearly from the commit sweep (could be hallucinated)
   0 = Purely qualitative; no numeric values cited
   STRICT: "significantly higher" or "p<0.05" without the actual value scores ≤1.

3. causal_coherence (0–4): Is the mechanistic picture a COMPLETE directed causal chain
   (A → B → C → phenotype) with specific molecular actors at every step?
   4 = Full chain: every link names the molecular mechanism (phosphorylation, transcriptional
       activation, epigenetic silencing, etc.) and connects to a clinical endpoint.
       Chain is consistent across Q1-Q4 (no contradictions between answers).
   3 = Chain has ≥3 explicit mechanistic links; one step vague or inconsistently stated
   2 = Two endpoints named with one intermediate mechanism; clinical connection implied
   1 = Pathway name invoked without stating the causal steps within it
   0 = Correlations stated as mechanism, or chain contradicts itself across Q1-Q4

Respond ONLY with valid JSON:
{
  "cross_modal_consistency": <int 0-4>,
  "quantitative_grounding": <int 0-4>,
  "causal_coherence": <int 0-4>,
  "total": <sum 0-12>,
  "consistency_note": "<one sentence on integration quality — be specific about what was missing>",
  "grounding_note": "<one sentence on numeric attribution — cite what was or wasn't committed>",
  "coherence_note": "<one sentence on chain completeness — name the weakest link>"
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
        # Sample each answer block independently (cap per answer, not total) so the
        # judge always sees the start of every Q regardless of how long Q4 is.
        PER_Q = 2000
        segments = [
            (a[:PER_Q] + "\n[truncated]") if len(a) > PER_Q else a
            for a in phase2_answers
        ]
        answers_window = "\n\n---\n\n".join(segments)
        commit_summary = commit_report[:800] if commit_report else "(not provided)"
        user_msg = (
            f"COMMIT PHASE REPORT:\n{commit_summary}\n\n"
            f"PHASE 2 Q1-Q4 ANSWERS:\n{answers_window}"
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
