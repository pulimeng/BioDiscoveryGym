"""
Run a v2 target discovery session with ClaudeAgentTarget.

v2 gives the agent an objective (find a target with a definable patient population)
without specifying an analytical pipeline. The agent must design its own methodology.

Key differences from v1:
  - No staged prompt — methodology is part of the evaluation
  - Submit tool requires patient biomarker + cell-line stratification + TCGA frequency
  - Phase 2 validation focuses on clinical translation, resistance, and kill criteria
  - Scored on methodological depth, not just logical chain

Usage:
    python scripts/run_target_discovery_v2.py
    python scripts/run_target_discovery_v2.py --indication "Osteosarcoma" --phase2 --phase3
    python scripts/run_target_discovery_v2.py --model claude-opus-4-7 --max-tool-calls 80

Requires ANTHROPIC_API_KEY in the environment.
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
    p.add_argument("--max-tool-calls", type=int, default=80,
                   help="v2 needs more calls for multivariate analysis — default 80 vs v1's 50")
    p.add_argument("--data-dir", default="data")
    p.add_argument(
        "--indication",
        default="cancer",
        help="Indication to target. Passed verbatim into the agent prompt.",
    )
    p.add_argument(
        "--phase2",
        action="store_true",
        help="After submission, inject v2 validation questions (biomarker clinical translation, "
             "cohort design, resistance, kill criteria).",
    )
    p.add_argument("--phase2-max-calls", type=int, default=20)
    p.add_argument(
        "--phase3",
        action="store_true",
        help="After Phase 2, reveal real gene names and run MOA check + drug landscape.",
    )
    p.add_argument("--phase3-max-calls", type=int, default=20)
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
    from biodiscoverygym.phases.target_discovery_v2 import (
        TASK_PROMPT_V2, SUBMIT_TOOL_V2, format_validation_prompt_v2,
    )

    session_id = str(uuid.uuid4())[:8]
    results_dir = Path("results") / session_id
    results_dir.mkdir(parents=True, exist_ok=True)

    print(f"\n{'='*60}")
    print(f"  Target Discovery Session — v2 (open-ended)")
    print(f"  Session    : {session_id}")
    print(f"  Seed       : {args.seed}")
    print(f"  Model      : {args.model}")
    print(f"  Indication : {args.indication}")
    print(f"  Budget     : {args.max_tool_calls} tool calls")
    if args.phase2:
        print(f"  Phase 2    : clinical translation + resistance (max {args.phase2_max_calls} calls)")
    if args.phase3:
        print(f"  Phase 3    : gene revelation + MOA + drug landscape (max {args.phase3_max_calls} calls)")
    print(f"{'='*60}\n")

    print("Loading datasets...")
    executor = TargetDiscoveryExecutor(
        data_dir=args.data_dir,
        output_dir=results_dir,
        seed=args.seed,
    )
    ns = executor.namespace
    crispr = ns.get("depmap_crispr")
    tcga   = ns.get("tcga_expr")
    gtex   = ns.get("gtex_median")
    gnomad = ns.get("gnomad")

    print(f"  DepMap CRISPR : {crispr.shape if crispr is not None else 'NOT FOUND'}")
    print(f"  TCGA expr     : {tcga.shape if tcga is not None else 'NOT FOUND'}")
    print(f"  GTEx median   : {gtex.shape if gtex is not None else 'NOT FOUND'}")
    print(f"  gnomAD        : {gnomad.shape if gnomad is not None else 'NOT FOUND'}")
    print()

    phase2_prompt = format_validation_prompt_v2() if args.phase2 else None

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
        task_prompt=TASK_PROMPT_V2,
        submit_tool=SUBMIT_TOOL_V2,
    )

    t0 = time.time()
    submission, revision, messages = agent.run(session_id, output_dir=results_dir, executor=executor)
    elapsed = time.time() - t0

    print(f"\n{'='*60}")
    print(f"  Session {session_id} complete ({elapsed:.0f}s)")
    print(f"{'='*60}")

    if submission:
        print(f"  Target             : {submission.get('target')}")
        bm = submission.get("patient_biomarker", {})
        print(f"  Biomarker          : {bm.get('feature_type')} — {bm.get('description','')[:80]}")
        val = submission.get("biomarker_cell_line_validation", {})
        print(f"  Cell line split    : {val.get('n_positive_lines')} pos / {val.get('n_negative_lines')} neg  "
              f"effect={val.get('effect_size')}  p={val.get('p_value')}")
        pop = submission.get("patient_population_estimate", {})
        print(f"  Patient population : {pop.get('n_biomarker_positive')}/{pop.get('n_patients_total')} "
              f"({pop.get('frequency_percent')}%) in {pop.get('tcga_cohort')}")
        print(f"  Confidence         : {submission.get('confidence')}")
        print(f"  Evidence gaps      : {len(submission.get('evidence_gaps', []))} stated")
    else:
        print("  No submission made.")

    if revision:
        print(f"\n  [Phase 3 Revision]")
        print(f"  Revised candidates : {revision.get('revised_candidates', [])}")
        print(f"  Ranking changed    : {revision.get('ranking_changed')}")
        hits = revision.get("indication_compound_hits", [])
        print(f"  PRISM hits         : {len(hits)} selective compounds identified")

    if args.save_log:
        out = {
            "session_id": session_id,
            "version": "v2",
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

        eval_dir = Path("results") / "_evaluation"
        eval_dir.mkdir(parents=True, exist_ok=True)
        gene_map_path = eval_dir / f"{session_id}_gene_map.json"
        gene_map_path.write_text(json.dumps(executor.gene_map, indent=2))
        print(f"  Gene map → {gene_map_path}")

    print()


if __name__ == "__main__":
    main()
