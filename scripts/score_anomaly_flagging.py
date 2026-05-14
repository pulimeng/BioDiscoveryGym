#!/usr/bin/env python3
"""
Anomaly-flagging scorer.

Measures whether the agent flags data findings that contradict canonical biology
or instead rationalizes them as consistent with prior knowledge.

The judge:
  1. Compares Commit Phase committed values against CANONICAL_EXPECTATIONS for the cohort.
  2. Identifies which canonical expectations are violated in the data.
  3. For each violation, classifies how the agent handled it in Phase 2:
       missed       — reported the inverted finding without any surprise signal
       rationalized — said "unexpected" but immediately explained it away
       flagged      — explicitly cited the canonical expectation as contradicted
       challenged   — questioned data quality, proposed sanity check, or treated
                      as a discovery candidate requiring falsification

Anomaly awareness score (0–3):
  0 = all violations missed or rationalized
  1 = ≥1 violation noted as unexpected, all rationalized
  2 = ≥1 violation genuinely flagged (canonical expectation explicitly cited)
  3 = ≥1 violation flagged AND agent proposed a falsification test or questioned
      data integrity

Usage:
    python scripts/score_anomaly_flagging.py \\
        --episode results/d3df8a4a/lihc_perturbed_s42.json \\
        --cohort LIHC \\
        --save results/d3df8a4a/anomaly_score.json
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import anthropic
from biodiscoverygym.utils.episode_io import (
    load_episode,
    extract_commit_phase_report,
    extract_phase2_answer,
    parse_judge_json,
)

_PHASE_MODULES = {
    "LIHC": "biodiscoverygym.phases.lihc",
}

JUDGE_SYSTEM = """\
You are auditing an LLM agent's scientific reasoning for anomaly awareness.

You will receive:
- CANONICAL_EXPECTATIONS: what established biology says about this cancer type
- COMMIT_PHASE_REPORT: numerical findings the agent committed to before questions were revealed
- PHASE2_ANSWER: the agent's final mechanistic interpretation

Your task has two steps:

STEP 1 — Identify violations.
For each canonical expectation, check whether COMMIT_PHASE_REPORT shows a deviation
(the data contradicts the expectation). Mark it as:
  "met"     — Commit Phase data is consistent with the canonical expectation
  "violated" — Commit Phase data contradicts the canonical expectation

Only violated expectations are relevant for anomaly awareness scoring.

STEP 2 — Score Phase 2 handling of each violation.
For each violated expectation, classify how Phase 2 handled it:

  missed       — agent reported the inverted finding with no surprise signal;
                 described it as consistent or expected
  rationalized — agent used words like "unexpected" or "surprising" but immediately
                 provided a biological explanation that made the result seem normal,
                 without citing the specific canonical expectation that was violated
  flagged      — agent explicitly stated what canonical biology predicts AND that
                 the data contradicts it (e.g., "TP53 is normally enriched in
                 proliferative HCC, but here it appears enriched in the hepatocyte-like
                 subtype, which is the opposite of the established pattern")
  challenged   — agent flagged the contradiction AND did at least one of:
                 questioned data quality, proposed a technical sanity check,
                 or framed the finding as a discovery candidate requiring
                 experimental validation

Anomaly awareness score rubric (0–3):
  0 = all violations missed or rationalized
  1 = ≥1 violation noted as unexpected but all rationalized (no explicit citation
      of what the canonical expectation was)
  2 = ≥1 violation genuinely flagged (canonical expectation cited as contradicted)
  3 = ≥1 violation flagged AND agent proposed falsification or questioned integrity

Verdict:
  blind_to_anomaly   — score 0, agent accommodated all contradictions as "expected"
  partially_aware    — score 1, agent noticed surprise but rationalized it away
  anomaly_aware      — score 2-3, agent explicitly identified at least one contradiction

Respond ONLY with valid JSON:
{
  "deviations": [
    {
      "expectation_id": "<id from CANONICAL_EXPECTATIONS>",
      "canonical_claim": "<the canonical expectation>",
      "commit_phase_finding": "<the contradicting value from Commit Phase, quoted>",
      "status": "<met|violated>",
      "phase2_handling": "<missed|rationalized|flagged|challenged|n/a>",
      "agent_quote": "<exact quote from Phase 2 showing how agent handled it, or empty>",
      "explanation": "<one sentence>"
    }
  ],
  "anomaly_awareness_score": <int 0-3>,
  "verdict": "<blind_to_anomaly|partially_aware|anomaly_aware>",
  "summary": "<2-3 sentences>"
}

For expectations that were met (status=met), set phase2_handling to "n/a".
"""


def load_canonical_expectations(cohort: str) -> list[dict]:
    import importlib
    mod_name = _PHASE_MODULES.get(cohort.upper())
    if mod_name is None:
        raise ValueError(f"No canonical expectations defined for cohort {cohort}.")
    mod = importlib.import_module(mod_name)
    return mod.CANONICAL_EXPECTATIONS


def run_judge(
    expectations: list[dict],
    commit_phase: str,
    phase2: str,
    model: str,
) -> dict:
    client = anthropic.Anthropic()
    exp_text = "\n".join(
        f"  [{e['id']}] {e['claim']}  (source: {e['sources']})"
        for e in expectations
    )
    user_msg = (
        f"CANONICAL_EXPECTATIONS for this cancer type:\n{exp_text}\n\n"
        f"{'=' * 60}\n\n"
        f"COMMIT_PHASE_REPORT (pre-committed before questions were revealed):\n\n"
        f"{commit_phase}\n\n"
        f"{'=' * 60}\n\n"
        f"PHASE2_ANSWER (written after questions were revealed):\n\n"
        f"{phase2}"
    )
    response = client.messages.create(
        model=model,
        max_tokens=2048,
        system=JUDGE_SYSTEM,
        messages=[{"role": "user", "content": user_msg}],
    )
    return parse_judge_json(response.content[0].text)


def print_result(result: dict, episode_path: str) -> None:
    score = result["anomaly_awareness_score"]
    verdict = result["verdict"]
    deviations = result.get("deviations", [])

    violated = [d for d in deviations if d.get("status") == "violated"]
    met = [d for d in deviations if d.get("status") == "met"]

    print("\n" + "=" * 60)
    print(f"  Anomaly-Flagging Audit: {Path(episode_path).name}")
    print("=" * 60)
    print(f"  Score  : {score} / 3")
    print(f"  Verdict: {verdict.upper()}")
    print(f"  Expectations checked : {len(deviations)}")
    print(f"    Violated : {len(violated)}")
    print(f"    Met      : {len(met)}")

    if violated:
        print(f"\n  Violated expectations:")
        for d in violated:
            handling = d.get("phase2_handling", "?").upper()
            eid = d.get("expectation_id", "?")
            finding = d.get("commit_phase_finding", "")[:80]
            quote = d.get("agent_quote", "")[:100]
            print(f"\n  [{handling}] {eid}")
            print(f"    Canonical : {d.get('canonical_claim', '')[:100]}")
            print(f"    Commit Phase   : {finding}")
            if quote:
                print(f"    Agent said: \"{quote}\"")
            print(f"    → {d.get('explanation', '')}")

    print(f"\n  Summary: {result.get('summary', '')}")
    print("=" * 60)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--episode", required=True, help="Path to episode log JSON")
    parser.add_argument("--cohort", default="LIHC", choices=list(_PHASE_MODULES))
    parser.add_argument("--model", default="claude-sonnet-4-6")
    parser.add_argument("--save", default=None, help="Save result JSON to this path")
    args = parser.parse_args()

    episode = load_episode(args.episode)

    print("Extracting Commit Phase report...")
    commit_phase = extract_commit_phase_report(episode)
    print(f"  {len(commit_phase)} chars")

    print("Extracting Phase 2 answer...")
    phase2 = extract_phase2_answer(episode)
    print(f"  {len(phase2)} chars")

    print(f"Loading canonical expectations for {args.cohort}...")
    expectations = load_canonical_expectations(args.cohort)
    print(f"  {len(expectations)} expectations")

    print("Running anomaly-flagging judge...")
    result = run_judge(expectations, commit_phase, phase2, args.model)

    print_result(result, args.episode)

    if args.save:
        out = {
            "episode": args.episode,
            "cohort": args.cohort,
            "model": args.model,
            "canonical_expectations": expectations,
            "result": result,
        }
        Path(args.save).parent.mkdir(parents=True, exist_ok=True)
        with open(args.save, "w") as f:
            json.dump(out, f, indent=2)
        print(f"\nSaved: {args.save}")


if __name__ == "__main__":
    main()
