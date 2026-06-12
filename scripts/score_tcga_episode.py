"""
Post-hoc v3 scoring for a completed BioDiscoveryGym episode.

Runs all v2 score components AND extracts an agent trace (reasoning + tool calls)
from the raw message log. No new scored components — trace is descriptive only.

Usage:
    python scripts/score_episode_v3.py path/to/episode.json --cohort BRCA --save
    python scripts/score_episode_v3.py path/to/episode.json --cohort OS --save --skip-llm

Outputs (with --save):
    <episode>_v3scores.json   — same structure as v2, plus 'trace' field
    <episode>_v3trace.json    — full per-call trace (reasoning + tool calls)
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))


def parse_args():
    p = argparse.ArgumentParser(description="Score a BioDiscoveryGym v3 episode post-hoc.")
    p.add_argument("episode_json", help="Path to episode result JSON (from --save-log)")
    p.add_argument("--cohort", default=None,
                   help="Cohort name (e.g. BRCA, OS). Reads from episode JSON if omitted.")
    p.add_argument("--data-dir", default="data", help="Root data directory (default: data)")
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
    episode_path = Path(args.episode_json)
    if not episode_path.exists():
        print(f"Error: {episode_path} not found", file=sys.stderr)
        sys.exit(1)

    episode = json.loads(episode_path.read_text())
    cohort: str = (args.cohort or episode.get("cohort", "")).upper()
    if not cohort:
        print("Error: --cohort not provided and not found in episode JSON.", file=sys.stderr)
        sys.exit(1)
    seed: int = int(episode.get("seed", 42))
    discovery: dict = episode.get("discovery") or {}
    messages: list[dict] = episode.get("messages", [])
    run_log: dict = episode.get("run_log", {})

    print(f"\n{'='*60}")
    print(f"  BioDiscoveryGym v3 Scorer (scores + trace)")
    print(f"  Cohort   : {cohort}")
    print(f"  Seed     : {seed}")
    print(f"  Messages : {len(messages)}")
    print(f"  Skip LLM : {args.skip_llm}")
    print(f"{'='*60}\n")

    data_dir = Path(args.data_dir)

    _EXTERNAL_COHORT_DIRS = {"OS": "data/external/os_jia2022"}

    print("Loading dataset...")
    from biodiscoverygym.utils.data_loader import DataLoader
    from biodiscoverygym.utils.hidden_context import DataAnonymizer

    loader = DataLoader(data_dir)
    tcga_dir = (
        Path(_EXTERNAL_COHORT_DIRS[cohort])
        if cohort in _EXTERNAL_COHORT_DIRS
        else data_dir / "tcga" / cohort.lower()
    )
    dataset = loader.load_tcga(cohort, tcga_dir=tcga_dir)
    anon_dataset = DataAnonymizer.mask(dataset)

    sample_id_map = reconstruct_sample_id_map(anon_dataset["expression"], seed)
    anon_dataset = apply_sample_rename(anon_dataset, sample_id_map)

    expression = anon_dataset.get("expression")
    metadata = anon_dataset.get("metadata")
    mutation = anon_dataset.get("mutation")
    rppa = anon_dataset.get("rppa")

    print(f"  Samples : {len(expression)}, genes : {expression.shape[1]}")

    # Resolve grouping from file path if needed
    pg = discovery.get("proposed_grouping", {})
    if isinstance(pg, str):
        try:
            pg = json.loads(Path(pg).read_text())
        except Exception:
            pg = {}
    discovery["proposed_grouping"] = pg

    if args.skip_llm:
        import biodiscoverygym.scoring.judge as _judge
        _judge.score_mechanism_grounding = lambda *a, **k: (0.0, {"skipped": True})
        _judge.score_experiment_quality = lambda *a, **k: (0.0, {"skipped": True})
        _judge.score_exam_experiment_depth = lambda *a, **k: (0.0, {"skipped": True})
        _judge.score_exam_mechanistic_integration = lambda *a, **k: (0.0, {"skipped": True})
        import biodiscoverygym.scoring.evaluator_v2 as _ev2
        _ev2.score_mechanism_grounding = _judge.score_mechanism_grounding
        _ev2.score_experiment_quality = _judge.score_experiment_quality
        _ev2.score_exam_experiment_depth = _judge.score_exam_experiment_depth
        _ev2.score_exam_mechanistic_integration = _judge.score_exam_mechanistic_integration

    from biodiscoverygym.scoring import EvaluatorV3

    evaluator = EvaluatorV3(data_dir=data_dir, llm_model=args.llm_model)

    print("\nRunning v2 scoring + trace extraction...")
    score_report, trace_report = evaluator.score_and_trace(
        discovery=discovery,
        expression=expression,
        metadata=metadata,
        mutation=mutation,
        rppa=rppa,
        sample_id_map=sample_id_map,
        cohort=cohort,
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
