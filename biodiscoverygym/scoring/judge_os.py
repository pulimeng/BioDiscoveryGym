"""
OS discovery-specific LLM judges.

mechanism_grounding_os         — Phase 1, 3 pts. Checks [PRIOR]/[DATA] discipline,
                                 call-number provenance, and discovery-beyond-priors framing.
exam_mechanistic_integration_os — Phase 2, 2 pts. Checks Data Lock numeric citation,
                                 multi-modal integration, and [PRIOR]/[DATA] discipline in Q1-Q4.

For TCGA faithfulness-style judges, see judge.py (score_mechanism_grounding,
score_exam_mechanistic_integration).
"""
from __future__ import annotations

import json

from biodiscoverygym.scoring.judge import _judge_client   # shared provider-routing shim

_DEFAULT_MODEL = "deepseek-v4-pro"   # NEUTRAL judge (routes via _judge_client)


def _parse_json(text: str) -> dict:
    text = text.strip()
    if "```" in text:
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    return json.loads(text.strip())


# ──────────────────────────────────────────────────────────────────────────────
# mechanism_grounding_os  (Phase 1, weight 3)
# ──────────────────────────────────────────────────────────────────────────────

_MECHANISM_OS_SYSTEM = """\
You are an adversarial scientific peer reviewer evaluating a DISCOVERY
biomarker hypothesis from a small rare-cancer cohort. Your job is to find
reasons to WITHHOLD credit, not to be charitable.

The benchmark scores DATA-DRIVEN discovery, not literature recall. The agent
was instructed to label every mechanistic claim as either [PRIOR] (known
biology, predictable from training knowledge) or [DATA] (specific to this
cohort, derived from a computation in this session, with a call number and
statistical test as provenance).

Score on three axes (0–4 each):

1. prior_data_discipline (0–4): Are mechanistic claims labeled [PRIOR] or [DATA],
   and do [DATA] claims cite specific computations?
   4 = Every mechanistic claim is labeled, and every [DATA] claim cites a
       quantitative result (HR, p-value, fold-change, effect size) — not just
       a finding type
   3 = Most claims labeled; [DATA] claims tied to data findings but specific
       numeric values inconsistently cited
   2 = Labels present but applied inconsistently; many [DATA] claims could be
       predicted from priors alone
   1 = Labels mentioned occasionally with no consistent discipline
   0 = No [PRIOR]/[DATA] labeling; pure narrative

2. causal_chain_from_data (0–4): Does the causal chain follow from cited data,
   or is it inferred from textbook biology?
   4 = Each link in the chain has a data-derived anchor — specific effect size,
       p-value, or modality finding from THIS cohort — and the chain follows
       directly from those numbers
   3 = Chain mostly grounded in data with one step that is narrative
   2 = Endpoints have data citations but middle links are textbook-mechanistic
   1 = Pathway name + phenotype only; no internal mechanism grounded in data
   0 = Correlation stated as causation, or chain is pure recall

3. discovery_beyond_priors (0–4): Does the hypothesis identify something that
   would NOT be predicted from canonical biology of this cancer type?
   4 = Hypothesis explicitly contrasts a [DATA] finding with [PRIOR] expectations
       and cites data showing the divergence (e.g., "we expected RUNX2 to dominate
       but the residual axis is driven by X")
   3 = Hypothesis acknowledges canonical biology as background and adds at least
       one specific [DATA] claim not predicted by it
   2 = Hypothesis is mostly canonical with implicit novel claims
   1 = Hypothesis recapitulates known biology without identifying what is new
   0 = Pure textbook recall; no novel claim identifiable

Respond ONLY with valid JSON:
{
  "prior_data_discipline": <int 0-4>,
  "causal_chain_from_data": <int 0-4>,
  "discovery_beyond_priors": <int 0-4>,
  "total": <sum 0-12>,
  "discipline_note": "<one sentence on labeling — name what's missing>",
  "chain_note": "<one sentence on weakest causal link>",
  "discovery_note": "<one sentence on the most novel [DATA] claim, or its absence>"
}
"""


def score_mechanism_grounding_os(
    mechanism_hypothesis: str,
    pathway_evidence: list[str],
    top_genes: list[str],
    model: str = _DEFAULT_MODEL,
) -> tuple[float, dict]:
    if not mechanism_hypothesis:
        return 0.0, {"reason": "no hypothesis submitted"}
    try:
        client = _judge_client
        user_msg = (
            f"TOP GENES: {', '.join(top_genes[:15]) if top_genes else 'none'}\n\n"
            f"PATHWAY EVIDENCE: {'; '.join(pathway_evidence[:10]) if pathway_evidence else 'none'}\n\n"
            f"MECHANISM HYPOTHESIS:\n{mechanism_hypothesis}"
        )
        response = client.messages.create(
            model=model,
            max_tokens=512,
            system=_MECHANISM_OS_SYSTEM,
            messages=[{"role": "user", "content": user_msg}],
        )
        result = _parse_json(response.content[0].text)
        raw = float(result.get("total", 0))
        return float(raw / 12.0), result
    except Exception as e:
        return 0.0, {"error": str(e)}


# ──────────────────────────────────────────────────────────────────────────────
# exam_mechanistic_integration_os  (Phase 2, weight 2)
# ──────────────────────────────────────────────────────────────────────────────

_EXAM_INTEGRATION_OS_SYSTEM = """\
You are an adversarial evaluator of multi-modal mechanistic reasoning in a
DISCOVERY biomarker examination. The agent submitted a Data Lock with
quantitative results and then answered Q1–Q4 examination questions. Your job
is to find reasons to WITHHOLD credit, not to be charitable.

Score on three axes (0–4 each):

1. data_lock_citation (0–4): Do the Q1–Q4 answers cite specific numeric values
   from the Data Lock report (not invented numbers, not qualitative claims)?
   4 = ≥6 specific values cited across the answers (HRs, p-values, fold-changes,
       beta values, mutation frequencies) with each citation traceable to the
       Data Lock content
   3 = 4–5 values cited with Data Lock attribution
   2 = 2–3 values cited; remaining claims qualitative
   1 = 1 value cited or qualitative references to "the data shows" without numbers
   0 = Purely qualitative; no numeric anchor
   STRICT: "p<0.05" or "significantly different" without the actual value scores ≤1.

2. multi_modal_integration (0–4): Are findings from multiple modalities
   (expression, methylation, CNA, mutation, clinical) woven into one coherent
   causal picture with explicit cross-modal links?
   4 = ≥3 modalities each contribute a specific finding AND are explicitly
       connected to a single causal model (e.g., "methylation at cg##### inversely
       correlates with X expression, which is highest in the worst-prognosis
       cluster where CNA Y is enriched")
   3 = 2 modalities integrated into one chain; a third mentioned but not woven in
   2 = Multiple modalities mentioned with shared conclusion but no explicit
       mechanistic link
   1 = Modalities listed separately ("methylation showed... mutations showed...")
       with no integration
   0 = Single modality, or modalities cited contradict each other
   STRICT: Naming modalities in separate paragraphs is NOT integration — score ≤1.

3. prior_data_labeling (0–4): Are [PRIOR] and [DATA] labels used in the answers
   to separate known biology from cohort-specific findings, and are they applied
   correctly (canonical claims as [PRIOR], computed findings as [DATA])?
   4 = Labels used throughout Q1–Q4 with correct calibration; agent acknowledges
       PRIOR expectations and contrasts them with DATA findings
   3 = Labels used in most claims with mostly correct application
   2 = Labels used in some answers; calibration inconsistent
   1 = Labels mentioned occasionally; no discipline
   0 = No labeling, or labels applied so inconsistently they convey no signal

Respond ONLY with valid JSON:
{
  "data_lock_citation": <int 0-4>,
  "multi_modal_integration": <int 0-4>,
  "prior_data_labeling": <int 0-4>,
  "total": <sum 0-12>,
  "citation_note": "<one sentence on numeric citation strength>",
  "integration_note": "<one sentence on weakest cross-modal link or lack thereof>",
  "labeling_note": "<one sentence on labeling discipline — name what's miscalibrated>"
}
"""


def score_exam_mechanistic_integration_os(
    phase2_answers: list[str],
    data_lock_report: str = "",
    model: str = _DEFAULT_MODEL,
) -> tuple[float, dict]:
    if not phase2_answers:
        return 0.0, {"reason": "no Phase 2 answers found"}
    try:
        client = _judge_client
        # Sample each answer block independently (cap per answer) so the judge
        # always sees the start of every Q regardless of how long Q4 is.
        PER_Q = 2000
        segments = [
            (a[:PER_Q] + "\n[truncated]") if len(a) > PER_Q else a
            for a in phase2_answers
        ]
        answers_window = "\n\n---\n\n".join(segments)
        commit_summary = data_lock_report[:1200] if data_lock_report else "(not provided)"
        user_msg = (
            f"DATA LOCK REPORT (first 1200 chars):\n{commit_summary}\n\n"
            f"Q1–Q4 EXAMINATION ANSWERS:\n{answers_window}"
        )
        response = client.messages.create(
            model=model,
            max_tokens=512,
            system=_EXAM_INTEGRATION_OS_SYSTEM,
            messages=[{"role": "user", "content": user_msg}],
        )
        result = _parse_json(response.content[0].text)
        raw = float(result.get("total", 0))
        return float(raw / 12.0), result
    except Exception as e:
        return 0.0, {"error": str(e)}
