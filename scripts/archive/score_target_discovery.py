"""
LLM judge scorer for target discovery sessions.

Usage:
    python scripts/score_target_discovery.py results/0dad7055/td_aml_s42.json
    python scripts/score_target_discovery.py results/0dad7055/td_aml_s42.json --save
    python scripts/score_target_discovery.py results/0dad7055/td_aml_s42.json --skip-llm

Requires ANTHROPIC_API_KEY. The session JSON must have been saved with --save-log
during run_target_discovery.py.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


_DEFAULT_MODEL = "claude-sonnet-4-6"

_JUDGE_SYSTEM = """\
You are a computational biology peer reviewer evaluating a therapeutic target discovery submission.

CONTEXT: An LLM agent received anonymized population-scale cancer dependency and normal-tissue \
data (DepMap CRISPR, DepMap expression, GTEx, gnomAD) and was asked to identify and justify \
therapeutic target candidates for a specified cancer indication. Gene symbols were anonymized \
as GENE_XXXXX during analysis; the real symbols for the top candidates are revealed to you for scoring.

Score the submission on exactly 5 dimensions (0–2 each):

1. evidence_chain (0–2)
   0 = One or more key steps entirely missing (no selectivity check, OR no normal-tissue check, OR no tolerability check)
   1 = All steps are present but superficial — steps are mentioned without quantitative thresholds or justification
   2 = Each filtering step has an explicit quantitative criterion WITH stated rationale \
(e.g., CERES ≤ −0.5, GTEx < 10 TPM, gnomAD pLI < 0.5, selectivity Δ > 0.3)

2. cancer_selectivity (0–2)
   0 = No comparison of indication vs. other cancers; GTEx not referenced
   1 = Selectivity checked but qualitative; GTEx values mentioned but not used to filter candidates
   2 = Quantitative indication-vs-other-lineage contrast reported AND GTEx used to filter candidates with a stated threshold

3. tolerability_check (0–2)
   0 = gnomAD not consulted
   1 = gnomAD values (pLI/LOEUF) reported but not used as an explicit filter
   2 = gnomAD used as an explicit filter with a stated cutoff (e.g., pLI < 0.5) and a biological rationale

4. evidence_gaps (0–2)
   0 = No gaps stated, or only generic disclaimers ("further work is needed")
   1 = Specific gaps are named but not linked to experiments that would close them
   2 = Each major gap is explicitly named AND paired with a specific experiment that addresses it

5. roadmap_quality (0–2)
   0 = No roadmap, or only generic suggestions (e.g., "validate in animal models")
   1 = Roadmap present but at least one step is missing a model system, perturbation method, or measurement readout
   2 = Ordered roadmap where every step specifies: (a) model system, (b) genetic/pharmacological perturbation, and (c) measurement readout

Respond ONLY with valid JSON matching this schema exactly:
{
  "evidence_chain": <int 0-2>,
  "cancer_selectivity": <int 0-2>,
  "tolerability_check": <int 0-2>,
  "evidence_gaps": <int 0-2>,
  "roadmap_quality": <int 0-2>,
  "total": <int 0-10>,
  "evidence_chain_note": "<one sentence explaining the score>",
  "cancer_selectivity_note": "<one sentence explaining the score>",
  "tolerability_check_note": "<one sentence explaining the score>",
  "evidence_gaps_note": "<one sentence explaining the score>",
  "roadmap_quality_note": "<one sentence explaining the score>",
  "overall_note": "<2-3 sentences on the overall quality of the reasoning>"
}
"""


def _parse_json(text: str) -> dict:
    text = text.strip()
    # strip markdown code fences if present
    if "```" in text:
        parts = text.split("```")
        for part in parts:
            if part.startswith("json"):
                text = part[4:].strip()
                break
            elif "{" in part:
                text = part.strip()
                break
    return json.loads(text.strip())


def _deanonymize(text: str, gene_map: dict[str, str]) -> str:
    """Replace all GENE_XXXXX tokens in text with their real symbols."""
    def replace(m):
        tok = m.group(0)
        return gene_map.get(tok, tok)
    return re.sub(r"GENE_\d{5}", replace, text)


def _format_submission_for_judge(
    indication: str,
    submission: dict,
    gene_map: dict[str, str],
) -> str:
    """Build the user-facing prompt for the LLM judge."""
    deanon = lambda s: _deanonymize(s, gene_map) if isinstance(s, str) else s

    top = submission.get("top_candidates", [])
    top_real = [f"{c} ({gene_map.get(c, c)})" for c in top]

    reasoning = deanon(submission.get("reasoning_chain", ""))

    comp_ev = submission.get("computational_evidence", [])
    ce_lines = []
    for ev in comp_ev:
        if isinstance(ev, dict):
            gene_id = ev.get("gene_id", ev.get("candidate", ""))
            real = gene_map.get(gene_id, gene_id)
            ce_lines.append(
                f"- {gene_id} ({real}): dep={ev.get('dependency_summary','')}, "
                f"sel={ev.get('selectivity_evidence','')}, "
                f"tol={ev.get('tolerability_evidence','')}"
            )
        else:
            ce_lines.append(f"- {deanon(str(ev))}")
    comp_ev_text = "\n".join(ce_lines) if ce_lines else "(none)"

    gaps = submission.get("evidence_gaps", [])
    gaps_text = "\n".join(f"- {deanon(g)}" for g in gaps) if gaps else "(none)"

    roadmap = submission.get("experimental_roadmap", [])
    roadmap_text = "\n".join(f"{i+1}. {deanon(r)}" for i, r in enumerate(roadmap)) if roadmap else "(none)"

    mech = deanon(submission.get("mechanism_hypothesis", ""))
    conf = submission.get("confidence", "")

    parts = [
        f"INDICATION: {indication}",
        f"\nTOP CANDIDATES: {', '.join(top_real)}",
        f"\nMECHANISM HYPOTHESIS: {mech}",
        f"CONFIDENCE: {conf}",
        f"\n--- REASONING CHAIN ---\n{reasoning}",
        f"\n--- COMPUTATIONAL EVIDENCE ---\n{comp_ev_text}",
        f"\n--- EVIDENCE GAPS ---\n{gaps_text}",
        f"\n--- EXPERIMENTAL ROADMAP ---\n{roadmap_text}",
    ]
    return "\n".join(parts)


def score_submission(
    indication: str,
    submission: dict,
    gene_map: dict[str, str],
    model: str = _DEFAULT_MODEL,
) -> tuple[dict, float]:
    """Call the LLM judge. Returns (result_dict, wall_time_s)."""
    import anthropic
    t0 = time.time()
    client = anthropic.Anthropic()
    user_msg = _format_submission_for_judge(indication, submission, gene_map)
    response = client.messages.create(
        model=model,
        max_tokens=1024,
        system=_JUDGE_SYSTEM,
        messages=[{"role": "user", "content": user_msg}],
    )
    wall = time.time() - t0
    result = _parse_json(response.content[0].text)
    # enforce total = sum of the five dimensions
    dims = ["evidence_chain", "cancer_selectivity", "tolerability_check",
            "evidence_gaps", "roadmap_quality"]
    computed_total = sum(int(result.get(d, 0)) for d in dims)
    result["total"] = computed_total
    return result, wall


def _pretty_print(result: dict, indication: str, session_path: str, model: str) -> None:
    dims = ["evidence_chain", "cancer_selectivity", "tolerability_check",
            "evidence_gaps", "roadmap_quality"]
    w = 58
    print(f"\n{'='*w}")
    print(f"  Target Discovery Score Report")
    print(f"  Session  : {session_path}")
    print(f"  Indication: {indication}")
    print(f"  Judge    : {model}")
    print(f"{'='*w}")
    for d in dims:
        score = result.get(d, 0)
        note  = result.get(f"{d}_note", "")
        bar   = "■" * score + "□" * (2 - score)
        print(f"  {d:<22} [{bar}] {score}/2  {note}")
    print(f"  {'─'*54}")
    print(f"  {'TOTAL':<22}         {result.get('total',0)}/10")
    print(f"\n  Overall: {result.get('overall_note','')}")
    print(f"{'='*w}\n")


def parse_args():
    p = argparse.ArgumentParser(
        description="Score a target discovery session with an LLM judge."
    )
    p.add_argument("session_json", help="Path to session result JSON (from run_target_discovery.py)")
    p.add_argument(
        "--model",
        default=_DEFAULT_MODEL,
        help=f"LLM judge model (default: {_DEFAULT_MODEL})",
    )
    p.add_argument(
        "--skip-llm",
        action="store_true",
        help="Skip LLM call, return zero scores (for testing).",
    )
    p.add_argument(
        "--save",
        action="store_true",
        help="Save score report as <session>_scores.json alongside the session file.",
    )
    return p.parse_args()


def main():
    args = parse_args()
    session_path = Path(args.session_json)
    if not session_path.exists():
        print(f"Error: {session_path} not found", file=sys.stderr)
        sys.exit(1)

    session = json.loads(session_path.read_text())
    indication  = session.get("indication", "unknown")
    submission  = session.get("submission", {})
    gene_map    = session.get("gene_map", {})
    agent_model = session.get("model", "unknown")

    if not submission:
        print("Error: no 'submission' found in session JSON.", file=sys.stderr)
        sys.exit(1)
    if not gene_map:
        print("Warning: no 'gene_map' in session JSON — candidates stay anonymized.", file=sys.stderr)

    print(f"\nScoring session: {session_path}")
    print(f"  Indication : {indication}")
    print(f"  Agent model: {agent_model}")
    print(f"  Judge model: {args.model}")

    if args.skip_llm:
        dims = ["evidence_chain", "cancer_selectivity", "tolerability_check",
                "evidence_gaps", "roadmap_quality"]
        result = {d: 0 for d in dims}
        result["total"] = 0
        for d in dims:
            result[f"{d}_note"] = "skipped"
        result["overall_note"] = "LLM scoring skipped (--skip-llm)."
        wall = 0.0
    else:
        if not __import__("os").environ.get("ANTHROPIC_API_KEY"):
            print("Error: ANTHROPIC_API_KEY is not set.", file=sys.stderr)
            sys.exit(1)
        result, wall = score_submission(indication, submission, gene_map, model=args.model)
        print(f"  Wall time  : {wall:.1f}s")

    _pretty_print(result, indication, str(session_path), args.model)

    if args.save:
        out_path = session_path.parent / (session_path.stem + "_scores.json")
        payload = {
            "session_id": session.get("session_id", session_path.stem),
            "session_path": str(session_path),
            "indication": indication,
            "agent_model": agent_model,
            "judge_model": args.model,
            "scores": result,
            "wall_time_s": wall,
        }
        out_path.write_text(json.dumps(payload, indent=2))
        print(f"Saved → {out_path}")


if __name__ == "__main__":
    main()
