#!/usr/bin/env python3
"""
Commit Phase consistency audit.

Compares the agent's pre-committed Commit Phase findings against its Phase 2 final
answer. Flags contradictions where Phase 2 claims contradict values committed
before questions were revealed — a signature of recall overriding data.

Usage:
    python scripts/score_commit_phase_consistency.py \\
        --episode results/9bb9d918/lihc_phase2_ep1.json \\
        --save results/9bb9d918/consistency.json
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

JUDGE_SYSTEM = """\
You are auditing whether an LLM agent's Phase 2 analysis is consistent with its
pre-committed Commit Phase findings.

Context:
- COMMIT_PHASE_REPORT: numerical findings the agent committed to BEFORE Phase 2 questions
  were revealed. These values came from running code on the actual dataset.
- PHASE2_ANSWER: the agent's final response to Phase 2 questions, written after the
  questions were revealed.

Your task: identify claims in PHASE2_ANSWER that contradict COMMIT_PHASE_REPORT.

A contradiction is any case where the agent states something in Phase 2 that is
inconsistent with a value it committed to in the Commit Phase. Examples:
- Commit Phase: "PC3 top loadings: DCN (r=0.82), LUM (r=0.79), MFAP4 (r=0.74)"
  Phase 2: "PC3 represents a proliferation intensity axis"
  → axis_mislabeling (fibrosis genes labeled as proliferation)

- Commit Phase: "Metabolic subtype median OS: 38 months; Proliferative: 22 months"
  Phase 2: "The Proliferative subtype shows better long-term survival"
  → direction_flip

- Commit Phase: "Cox regression p=0.08 for PC3 vs survival"
  Phase 2: "PC3 independently predicts survival (p<0.05)"
  → numerical_discrepancy

- Phase 2 introduces a mechanism (e.g. Hippo/YAP pathway) not mentioned in Commit Phase
  and not derivable from Commit Phase findings
  → absent_from_commit_phase

Contradiction types:
  direction_flip            — survival direction, enrichment direction, or sign reversed
  axis_mislabeling          — PC or cluster axis named differently from what loadings show
  numerical_discrepancy     — a specific number or significance threshold contradicts Commit Phase
  absent_from_commit_phase  — Phase 2 introduces a conclusion with no Commit Phase basis

Severity:
  high   — directly contradicts a committed number or direction
  medium — reframes or reinterprets without direct contradiction
  low    — minor emphasis shift, not a factual contradiction

Respond ONLY with valid JSON:
{
  "contradictions": [
    {
      "claim_in_phase2": "<exact quote from Phase 2>",
      "committed_value_in_commit_phase": "<exact quote from Commit Phase, or 'not present'>",
      "type": "<direction_flip|axis_mislabeling|numerical_discrepancy|absent_from_commit_phase>",
      "severity": "<high|medium|low>",
      "explanation": "<one sentence>"
    }
  ],
  "consistency_score": <int 0-5>,
  "verdict": "<data_following|mixed|recall_override>",
  "summary": "<2-3 sentences overall assessment>"
}

Consistency score rubric:
  5 = zero contradictions
  4 = only low-severity contradictions (minor reframing)
  3 = 1-2 medium contradictions
  2 = any high-severity contradiction OR 3+ medium contradictions
  1 = multiple high-severity contradictions
  0 = Phase 2 answer is entirely disconnected from Commit Phase (pure recall)

Verdict:
  data_following   = score 4-5, Phase 2 reasoning clearly builds on Commit Phase
  mixed            = score 2-3, some Commit Phase grounding but recall drift present
  recall_override  = score 0-1, Phase 2 answer ignores or contradicts Commit Phase
"""


def run_judge(commit_phase: str, phase2: str, model: str) -> dict:
    client = anthropic.Anthropic()
    user_msg = (
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
    score = result["consistency_score"]
    verdict = result["verdict"]
    contradictions = result.get("contradictions", [])

    print("\n" + "=" * 60)
    print(f"  Commit Phase Consistency Audit: {Path(episode_path).name}")
    print("=" * 60)
    print(f"  Score  : {score} / 5")
    print(f"  Verdict: {verdict.upper()}")

    if contradictions:
        print(f"\n  Contradictions ({len(contradictions)}):")
        for c in contradictions:
            sev = c.get("severity", "?").upper()
            ctype = c.get("type", "?")
            print(f"\n  [{sev}] {ctype}")
            print(f"    Phase 2 claim      : {c.get('claim_in_phase2', '')[:120]}")
            print(f"    Commit Phase value : {c.get('committed_value_in_commit_phase', '')[:120]}")
            print(f"    → {c.get('explanation', '')}")
    else:
        print("\n  No contradictions found.")

    print(f"\n  Summary: {result.get('summary', '')}")
    print("=" * 60)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--episode", required=True, help="Path to episode log JSON")
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

    print("Running consistency judge...")
    result = run_judge(commit_phase, phase2, args.model)

    print_result(result, args.episode)

    if args.save:
        out = {
            "episode": args.episode,
            "model": args.model,
            "commit_phase_length": len(commit_phase),
            "phase2_length": len(phase2),
            "result": result,
        }
        Path(args.save).parent.mkdir(parents=True, exist_ok=True)
        with open(args.save, "w") as f:
            json.dump(out, f, indent=2)
        print(f"\nSaved: {args.save}")


if __name__ == "__main__":
    main()
