"""
Post-hoc OS discovery scoring for a completed BioDiscoveryGym episode.

Discovery rubric for SGH-OS (Jia et al. 2022) — scores whether the agent found
prognostic biomarkers beyond what the paper reports. Three phases:
  Phase 1 — structural + computational (15 pts)
  Phase 2 — post-submission Examination (3 pts)
  Phase 3 — TARGET-OS external validation (5 pts)
Grand total: 23 pts. All components implemented; LLM-judge components
(mechanistic_grounding, validation_experiment, exam_mechanistic_integration)
can be bypassed with --skip-llm for fast no-API-cost scoring.

Usage:
    python scripts/score_os_episode.py path/to/episode.json --save
    python scripts/score_os_episode.py path/to/episode.json --save --skip-llm

Outputs (with --save):
    <episode>_v3scores.json   — full report including phase 1/2/3 + trace summary
    <episode>_v3trace.json    — full per-call trace
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))

OS_COHORT = "OS"
OS_DATA_DIR = "data/external/os_jia2022"
TARGET_DATA_DIR = "data/external/TARGET"


def parse_args():
    p = argparse.ArgumentParser(description="Score a BioDiscoveryGym OS discovery episode.")
    p.add_argument("episode_json", help="Path to episode result JSON (from --save-log)")
    p.add_argument("--data-dir", default="data", help="Root data directory (default: data)")
    p.add_argument("--target-dir", default=TARGET_DATA_DIR,
                   help="TARGET-OS data directory for Phase 3 external validation")
    p.add_argument("--save", action="store_true", help="Save score + trace JSON files")
    p.add_argument("--llm-model", default="claude-sonnet-4-6")
    p.add_argument("--skip-llm", action="store_true",
                   help="Skip LLM judge components — faster, no API cost")
    return p.parse_args()


def reconstruct_sample_id_map(expression: pd.DataFrame, seed: int) -> dict[str, str]:
    rng = np.random.default_rng(seed)
    original_ids = expression.index.tolist()
    shuffled = original_ids.copy()
    rng.shuffle(shuffled)
    anon_ids = [f"SAMPLE_{i:04d}" for i in range(len(shuffled))]
    return dict(zip(anon_ids, shuffled))


def apply_sample_rename(dataset: dict, sample_id_map: dict) -> dict:
    rename = {orig: anon for anon, orig in sample_id_map.items()}
    result = {}
    for key, val in dataset.items():
        if isinstance(val, pd.DataFrame):
            result[key] = val.rename(index=rename)
        else:
            result[key] = val
    return result


def main():
    args = parse_args()

    # Fail-fast guard: missing API key would silently zero 7 of 23 LLM-judged
    # points (mechanistic_grounding 3 + validation_experiment 2 + exam_mechanistic_integration 2).
    # Components catch the AuthenticationError defensively and return 0 — useful
    # for batch resilience but a footgun for one-off scoring runs.
    import os
    if not args.skip_llm and not os.environ.get("ANTHROPIC_API_KEY"):
        print("ERROR: ANTHROPIC_API_KEY is not set.", file=sys.stderr)
        print("  This script invokes 3 LLM judges (~7 of 23 pts).", file=sys.stderr)
        print("  Either:", file=sys.stderr)
        print("    export ANTHROPIC_API_KEY=sk-...    # to run judges", file=sys.stderr)
        print("    OR pass --skip-llm                  # to score computational components only", file=sys.stderr)
        sys.exit(1)

    episode_path = Path(args.episode_json)
    if not episode_path.exists():
        print(f"Error: {episode_path} not found", file=sys.stderr)
        sys.exit(1)

    episode = json.loads(episode_path.read_text())
    seed: int = int(episode.get("seed", 42))
    discovery: dict = episode.get("discovery") or {}
    messages: list[dict] = episode.get("messages", [])
    run_log: dict = episode.get("run_log", {})

    print(f"\n{'='*60}")
    print(f"  BioDiscoveryGym OS Discovery Scorer")
    print(f"  Cohort   : {OS_COHORT}")
    print(f"  Seed     : {seed}")
    print(f"  Messages : {len(messages)}")
    print(f"  Skip LLM : {args.skip_llm}")
    print(f"{'='*60}\n")

    data_dir = Path(args.data_dir)

    print("Loading SGH-OS dataset...")
    from biodiscoverygym.utils.data_loader import DataLoader
    from biodiscoverygym.utils.hidden_context import DataAnonymizer

    loader = DataLoader(data_dir)
    dataset = loader.load_tcga(OS_COHORT, tcga_dir=Path(OS_DATA_DIR))
    anon_dataset = DataAnonymizer.mask(dataset)

    sample_id_map = reconstruct_sample_id_map(anon_dataset["expression"], seed)
    anon_dataset = apply_sample_rename(anon_dataset, sample_id_map)

    expression = anon_dataset.get("expression")
    metadata = anon_dataset.get("metadata")
    mutation = anon_dataset.get("mutation")
    methylation = anon_dataset.get("methylation")
    cna = anon_dataset.get("cna")

    print(f"  Samples : {len(expression)}, genes : {expression.shape[1]}")
    print(f"  Methylation : {'available' if methylation is not None else 'none'}")
    print(f"  CNA         : {'available' if cna is not None else 'none'}")
    print(f"  Mutation    : {'available' if mutation is not None else 'none'}")

    # Resolve grouping from file path if needed
    pg = discovery.get("proposed_grouping", {})
    if isinstance(pg, str):
        try:
            pg = json.loads(Path(pg).read_text())
        except Exception:
            pg = {}
    discovery["proposed_grouping"] = pg

    if args.skip_llm:
        _skip = lambda *a, **k: (0.0, {"skipped": True})
        import biodiscoverygym.scoring.judge as _judge
        import biodiscoverygym.scoring.judge_os as _judge_os
        import biodiscoverygym.scoring.evaluator_os as _ev_os
        _judge.score_experiment_quality = _skip
        _judge_os.score_mechanism_grounding_os = _skip
        _judge_os.score_exam_mechanistic_integration_os = _skip
        _ev_os.score_experiment_quality = _skip
        _ev_os.score_mechanism_grounding_os = _skip
        _ev_os.score_exam_mechanistic_integration_os = _skip

    from biodiscoverygym.scoring import EvaluatorOS

    evaluator = EvaluatorOS(
        data_dir=data_dir,
        llm_model=args.llm_model,
        target_data_dir=Path(args.target_dir),
    )

    print("\nRunning OS scoring (Phase 1 + 2 + 3) + trace extraction...")
    score_report, trace_report = evaluator.score_full(
        discovery=discovery,
        expression=expression,
        metadata=metadata,
        mutation=mutation,
        methylation=methylation,
        cna=cna,
        messages=messages,
        run_log=run_log or None,
    )

    print(f"\n{score_report.pretty_print()}")
    print(f"\n{trace_report.pretty_print()}")
    print(f"\n  Scoring wall time: {score_report.wall_time_s:.1f}s")

    if args.save:
        stem = episode_path.stem
        scores_path = episode_path.parent / f"{stem}_v3scores.json"
        trace_path = episode_path.parent / f"{stem}_v3trace.json"

        combined_scores = score_report.to_dict()
        combined_scores["trace_summary"] = {
            k: v for k, v in trace_report.to_dict().items() if k != "calls"
        }
        scores_path.write_text(json.dumps(combined_scores, indent=2))

        trace_path.write_text(json.dumps(trace_report.to_dict(), indent=2))

        print(f"\n  Saved → {scores_path}")
        print(f"  Saved → {trace_path}")

    print()


if __name__ == "__main__":
    main()
