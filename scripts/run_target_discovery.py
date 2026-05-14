"""
Run a target discovery session with ClaudeAgentTarget.

The agent receives anonymized DepMap + GTEx + gnomAD data and must:
  1. Identify selective cancer dependencies
  2. Filter by normal tissue expression (GTEx)
  3. Check human tolerability (gnomAD constraint)
  4. Propose mechanism
  5. State evidence gaps explicitly
  6. Propose ordered experimental roadmap

No criteria are given — the agent must derive its own filtering logic.

Usage:
    python scripts/run_target_discovery.py
    python scripts/run_target_discovery.py --seed 7 --model claude-opus-4-7
    python scripts/run_target_discovery.py --max-tool-calls 80 --save-log results/td_s42.json

Requires ANTHROPIC_API_KEY in the environment.
Also requires gnomAD data — run: python scripts/download_gnomad.py
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--model", default="claude-sonnet-4-6")
    p.add_argument("--max-tool-calls", type=int, default=50)
    p.add_argument("--data-dir", default="data")
    p.add_argument(
        "--indication",
        default="cancer",
        help="Indication to target (e.g. 'Acute Myeloid Leukemia', 'non-small cell lung cancer'). "
             "Passed verbatim into the agent system prompt. Default: 'cancer' (pan-cancer mode).",
    )
    p.add_argument(
        "--phase2",
        action="store_true",
        help="After submit_target_discovery, inject validation design questions (V1–V4). "
             "Agent answers with genes still anonymized.",
    )
    p.add_argument(
        "--phase2-max-calls",
        type=int,
        default=20,
        help="Max tool calls for Phase 2 validation design (default: 20)",
    )
    p.add_argument(
        "--phase3",
        action="store_true",
        help="After Phase 1 (or Phase 2), reveal real gene names and run MOA check (R1–R4). "
             "Agent calls revise_submission with pathway database context.",
    )
    p.add_argument(
        "--phase3-max-calls",
        type=int,
        default=20,
        help="Max tool calls for Phase 3 revelation (default: 20)",
    )
    p.add_argument("--quiet", action="store_true")
    p.add_argument("--save-log", metavar="PATH", default=None)
    return p.parse_args()


def _serialize_messages(messages: list) -> list:
    out = []
    for msg in messages:
        role = msg.get("role", "")
        content = msg.get("content", "")
        if isinstance(content, list):
            blocks = []
            for b in content:
                if isinstance(b, dict):
                    blocks.append(b)
                elif hasattr(b, "model_dump"):
                    blocks.append(b.model_dump())
                else:
                    blocks.append({"type": str(type(b)), "raw": str(b)})
            out.append({"role": role, "content": blocks})
        else:
            out.append({"role": role, "content": content})
    return out


def main():
    args = parse_args()

    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("Error: ANTHROPIC_API_KEY is not set.", file=sys.stderr)
        sys.exit(1)

    from agents.claude_agent_target import ClaudeAgentTarget
    from biodiscoverygym.executor_target import TargetDiscoveryExecutor
    from biodiscoverygym.phases.target_discovery import format_validation_prompt

    session_id = str(uuid.uuid4())[:8]

    results_dir = Path("results") / session_id
    results_dir.mkdir(parents=True, exist_ok=True)

    print(f"\n{'='*60}")
    print(f"  Target Discovery Session")
    print(f"  Session : {session_id}")
    print(f"  Seed    : {args.seed}")
    print(f"  Model      : {args.model}")
    print(f"  Indication : {args.indication}")
    print(f"  Budget     : {args.max_tool_calls} tool calls")
    if args.phase2:
        print(f"  Phase 2    : validation design (max {args.phase2_max_calls} calls)")
    if args.phase3:
        print(f"  Phase 3    : gene revelation + MOA check (max {args.phase3_max_calls} calls)")
    print(f"{'='*60}\n")

    print("Loading datasets...")
    executor = TargetDiscoveryExecutor(
        data_dir=args.data_dir,
        output_dir=results_dir,
        seed=args.seed,
    )
    ns = executor.namespace
    crispr = ns.get("depmap_crispr")
    expr   = ns.get("depmap_expr")
    gtex   = ns.get("gtex_median")
    gnomad = ns.get("gnomad")

    print(f"  DepMap CRISPR : {crispr.shape if crispr is not None else 'NOT FOUND'}")
    print(f"  DepMap expr   : {expr.shape if expr is not None else 'NOT FOUND'}")
    print(f"  GTEx median   : {gtex.shape if gtex is not None else 'NOT FOUND'}")
    print(f"  gnomAD        : {gnomad.shape if gnomad is not None else 'NOT FOUND (run download_gnomad.py)'}")
    print()

    phase2_prompt = format_validation_prompt() if args.phase2 else None

    agent = ClaudeAgentTarget(
        model=args.model,
        max_tool_calls=args.max_tool_calls,
        data_dir=args.data_dir,
        verbose=not args.quiet,
        indication=args.indication,
        phase2_prompt=phase2_prompt,
        phase2_max_calls=args.phase2_max_calls,
        phase3=args.phase3,
        phase3_max_calls=args.phase3_max_calls,
    )

    t0 = time.time()
    submission, revision, messages = agent.run(session_id, output_dir=results_dir, executor=executor)
    elapsed = time.time() - t0

    print(f"\n{'='*60}")
    print(f"  Session {session_id} complete ({elapsed:.0f}s)")
    print(f"{'='*60}")

    if submission:
        print(f"  Top candidates : {submission.get('top_candidates', [])}")
        print(f"  Confidence     : {submission.get('confidence', 'N/A')}")
        gaps = submission.get("evidence_gaps", [])
        roadmap = submission.get("experimental_roadmap", [])
        print(f"  Evidence gaps  : {len(gaps)} stated")
        print(f"  Roadmap steps  : {len(roadmap)} proposed")
    else:
        print("  No submission made.")

    if revision:
        print(f"\n  [Phase 3 Revision]")
        print(f"  Revised candidates : {revision.get('revised_candidates', [])}")
        print(f"  Ranking changed    : {revision.get('ranking_changed')}")
        moa = revision.get("moa_assessment", [])
        print(f"  MOA assessments    : {len(moa)} genes evaluated")
        hits = revision.get("indication_compound_hits", [])
        print(f"  PRISM hits         : {len(hits)} selective compounds identified")

    if args.save_log:
        # Session log (no gene_map — kept separate for clean de-anonymization)
        out = {
            "session_id": session_id,
            "seed": args.seed,
            "model": args.model,
            "indication": args.indication,
            "wall_time_s": round(elapsed, 1),
            "submission": submission,
            "revision": revision if revision else None,
            "messages": _serialize_messages(messages),
        }
        log_path = results_dir / Path(args.save_log).name
        log_path.write_text(json.dumps(out, indent=2))
        print(f"\n  Saved → {log_path}")

        # Gene map stored in a separate evaluation directory, outside the agent's output_dir.
        # This prevents any accidental exposure during replay or analysis.
        eval_dir = Path("results") / "_evaluation"
        eval_dir.mkdir(parents=True, exist_ok=True)
        gene_map_path = eval_dir / f"{session_id}_gene_map.json"
        gene_map_path.write_text(json.dumps(executor.gene_map, indent=2))
        print(f"  Gene map → {gene_map_path}  (evaluation use only)")

    print()


if __name__ == "__main__":
    main()
