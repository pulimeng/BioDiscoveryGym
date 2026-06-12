#!/usr/bin/env python3
"""
Phase 2 delta scorer.

Compares a data-driven Phase 2 answer against a no-data novelty control
baseline. An LLM judge scores what the data access actually contributed.

Usage:
    python scripts/score_phase2_delta.py \\
        --episode results/abc123/lihc_ep1.json \\
        --baseline results/novelty_lihc_v2.json \\
        --save results/abc123/phase2_delta.json

    # Generate novelty baseline on the fly:
    python scripts/score_phase2_delta.py \\
        --episode results/abc123/lihc_ep1.json \\
        --auto-baseline --cohort LIHC
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import anthropic
from biodiscoverygym.utils.episode_io import (
    load_episode,
    extract_phase2_answer,
    parse_judge_json,
)

JUDGE_SYSTEM = """\
You are evaluating scientific discovery quality. You will receive:
- BASELINE: an answer produced without any data access (pure literature recall)
- DATA_ANSWER: an answer produced by an agent that ran code on a real dataset

Your job: identify what the DATA_ANSWER adds over the BASELINE, and score the delta.

Scoring rubric (0–10 total):

Discovery delta (0–5):
  5 = DATA_ANSWER contains ≥3 specific claims absent from BASELINE and supported
      by concrete numbers (p-values, correlations, counts, thresholds) that can
      only come from inspecting this specific dataset
  3 = 1–2 such claims
  1 = data adds only minor numerical decoration to conclusions already in BASELINE
  0 = DATA_ANSWER is substantively identical to BASELINE

Accuracy delta (0–3):
  3 = DATA_ANSWER corrects or contradicts a claim made in BASELINE using data
  2 = DATA_ANSWER qualifies or refines a BASELINE claim with dataset-specific nuance
  1 = no corrections, but DATA_ANSWER avoids BASELINE overconfidence
  0 = DATA_ANSWER repeats BASELINE errors or introduces new unsupported claims

Reasoning integrity (0–2):
  2 = numbers stated before mechanistic conclusions (data → conclusion order);
      no cherry-picked statistics; Stage B claims traceable to Commit Phase if present
  1 = mixed order; some conclusions stated before supporting numbers; or Stage B
      claims introduce new mechanisms absent from Commit Phase
  0 = conclusions stated first, data cited afterward as confirmation; or Stage B
      answers disconnected from Commit Phase entirely

Respond ONLY with valid JSON:
{
  "discovery_delta": <int 0-5>,
  "accuracy_delta": <int 0-3>,
  "reasoning_integrity": <int 0-2>,
  "total": <sum>,
  "novel_claims": ["<claim 1>", "<claim 2>", ...],
  "corrections": ["<correction 1>", ...],
  "integrity_notes": "<one sentence on reasoning order>",
  "summary": "<2-3 sentence overall assessment>"
}
"""


def run_judge(baseline: str, data_answer: str, model: str, commit_phase: str | None = None) -> dict:
    client = anthropic.Anthropic()
    commit_phase_section = ""
    if commit_phase:
        commit_phase_section = (
            f"COMMIT_PHASE_REPORT (pre-committed data sweep before questions were revealed):\n\n"
            f"{commit_phase}\n\n{'=' * 60}\n\n"
        )
    user_msg = (
        f"BASELINE (no data access):\n\n{baseline}\n\n"
        f"{'=' * 60}\n\n"
        f"{commit_phase_section}"
        f"DATA_ANSWER (agent had full dataset access):\n\n{data_answer}"
    )
    response = client.messages.create(
        model=model,
        max_tokens=1024,
        system=JUDGE_SYSTEM,
        messages=[{"role": "user", "content": user_msg}],
    )
    return parse_judge_json(response.content[0].text)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--episode", required=True, help="Path to episode log JSON")
    parser.add_argument("--baseline", default=None, help="Path to novelty control JSON")
    parser.add_argument("--auto-baseline", action="store_true",
                        help="Run novelty_control.py if --baseline not provided")
    parser.add_argument("--cohort", default="LIHC", help="Cohort for auto-baseline")
    parser.add_argument("--model", default="claude-sonnet-4-6")
    parser.add_argument("--save", default=None, help="Save result to this path")
    args = parser.parse_args()

    baseline_path = args.baseline
    if baseline_path is None:
        if not args.auto_baseline:
            print("Provide --baseline or use --auto-baseline --cohort COHORT")
            sys.exit(1)
        baseline_path = str(Path(args.episode).parent / "novelty_baseline.json")
        print(f"Running novelty control → {baseline_path}")
        subprocess.run(
            [sys.executable, "scripts/novelty_control.py",
             "--cohort", args.cohort,
             "--model", args.model,
             "--save-log", baseline_path],
            check=True,
        )

    episode = load_episode(args.episode)
    data_answer = extract_phase2_answer(episode)
    with open(baseline_path) as f:
        baseline_answer = json.load(f)["answer"]

    commit_phase = episode.get("discovery", {}).get("commit_phase_report")
    if commit_phase:
        print(f"Commit Phase report found ({len(commit_phase)} chars) — passing to judge.")

    print("Running LLM judge...")
    result = run_judge(baseline_answer, data_answer, args.model, commit_phase)

    print("\n" + "=" * 60)
    print(f"  Phase 2 Delta Score: {result['total']} / 10")
    print(f"    Discovery delta:     {result['discovery_delta']} / 5")
    print(f"    Accuracy delta:      {result['accuracy_delta']} / 3")
    print(f"    Reasoning integrity: {result['reasoning_integrity']} / 2")
    if result.get("novel_claims"):
        print("\n  Novel claims (not in baseline):")
        for c in result["novel_claims"]:
            print(f"    • {c}")
    if result.get("corrections"):
        print("\n  Corrections to baseline:")
        for c in result["corrections"]:
            print(f"    • {c}")
    print(f"\n  Integrity: {result.get('integrity_notes', '')}")
    print(f"\n  Summary: {result.get('summary', '')}")
    print("=" * 60)

    if args.save:
        out = {
            "episode": args.episode,
            "baseline": baseline_path,
            "model": args.model,
            "scores": result,
        }
        Path(args.save).parent.mkdir(parents=True, exist_ok=True)
        with open(args.save, "w") as f:
            json.dump(out, f, indent=2)
        print(f"\nSaved: {args.save}")


if __name__ == "__main__":
    main()
