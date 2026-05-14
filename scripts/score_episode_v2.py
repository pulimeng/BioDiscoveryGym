"""
Post-hoc v2 scoring for a completed BioDiscoveryGym episode.

Usage:
    python scripts/score_episode_v2.py path/to/episode.json
    python scripts/score_episode_v2.py path/to/episode.json --data-dir data --save

The episode JSON must have been saved with --save-log during run_episode.py.
Reconstructs the dataset from TCGA files using the same cohort + seed so that
sample_id_map matches the one used during the episode.

Gene names are always restored to real symbols for scoring (gene anonymization
is always-on during episodes), so marker_evidence scores correctly against
real gene names that the agent submitted after Stage 5 codebook translation.
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
    p = argparse.ArgumentParser(description="Score a BioDiscoveryGym v2 episode post-hoc.")
    p.add_argument("episode_json", help="Path to episode result JSON (from --save-log)")
    p.add_argument("--data-dir", default="data", help="Root data directory (default: data)")
    p.add_argument(
        "--save",
        action="store_true",
        help="Save v2 score report as <episode>_v2scores.json alongside input file",
    )
    p.add_argument(
        "--llm-model",
        default="claude-sonnet-4-6",
        help="Model for LLM judge components (default: claude-sonnet-4-6)",
    )
    p.add_argument(
        "--skip-llm",
        action="store_true",
        help="Skip LLM judge components (mechanism_grounding, experiment_quality) — faster, no API cost",
    )
    return p.parse_args()


def reconstruct_sample_id_map(expression: pd.DataFrame, seed: int) -> dict[str, str]:
    """
    Replay Episode._anonymize_sample_ids to get {SAMPLE_XXXX: original_barcode}.
    Must match episode.py exactly.
    """
    rng = np.random.default_rng(seed)
    original_ids = expression.index.tolist()
    shuffled = original_ids.copy()
    rng.shuffle(shuffled)
    anon_ids = [f"SAMPLE_{i:04d}" for i in range(len(shuffled))]
    return dict(zip(anon_ids, shuffled))  # SAMPLE_XXXX → original


def apply_sample_rename(dataset: dict, sample_id_map: dict) -> dict:
    """Rename DataFrame indices from original barcodes to SAMPLE_XXXX."""
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
    cohort: str = episode.get("cohort", "").upper()
    seed: int = int(episode.get("seed", 42))
    discovery: dict = episode.get("discovery") or {}

    if not cohort:
        print("Error: 'cohort' field missing from episode JSON", file=sys.stderr)
        sys.exit(1)
    if not discovery:
        print("Warning: no discovery in episode JSON — all scores will be 0", file=sys.stderr)

    print(f"\n{'='*60}")
    print(f"  BioDiscoveryGym v2 Post-hoc Scorer")
    print(f"  Cohort   : {cohort}")
    print(f"  Seed     : {seed}")
    print(f"  Episode  : {episode_path.name}")
    print(f"  Skip LLM : {args.skip_llm}")
    print(f"{'='*60}\n")

    data_dir = Path(args.data_dir)

    # --- Reconstruct dataset (real gene names, SAMPLE_XXXX indices) ---
    print("Loading dataset from TCGA files...")
    from biodiscoverygym.utils.data_loader import DataLoader
    from biodiscoverygym.utils.hidden_context import DataAnonymizer

    loader = DataLoader(data_dir)
    dataset = loader.load_tcga(
        cohort,
        tcga_dir=data_dir / "tcga" / cohort.lower(),
    )
    # Strip leaky columns but keep real gene names
    anon_dataset = DataAnonymizer.mask(dataset)

    # Reconstruct sample_id_map from the original (pre-shuffle) expression index
    sample_id_map = reconstruct_sample_id_map(anon_dataset["expression"], seed)

    # Apply SAMPLE_XXXX renaming to all DataFrames
    anon_dataset = apply_sample_rename(anon_dataset, sample_id_map)

    expression: pd.DataFrame = anon_dataset.get("expression")
    metadata: pd.DataFrame = anon_dataset.get("metadata")
    mutation: pd.DataFrame | None = anon_dataset.get("mutation")
    rppa: pd.DataFrame | None = anon_dataset.get("rppa")

    print(f"  Samples  : {len(expression)}")
    print(f"  Genes    : {expression.shape[1]}")
    print(f"  Mutation : {'yes' if mutation is not None else 'no'}")
    print(f"  RPPA     : {'yes' if rppa is not None else 'no'}")

    # --- Ensure proposed_grouping is a dict (may be a file path in older logs) ---
    pg = discovery.get("proposed_grouping", {})
    if isinstance(pg, str):
        try:
            pg = json.loads(Path(pg).read_text())
        except Exception:
            pg = {}
    discovery["proposed_grouping"] = pg

    # --- Run v2 evaluator ---
    if args.skip_llm:
        # Patch judge to return zeros without API call
        import biodiscoverygym.scoring.judge as _judge
        _judge.score_mechanism_grounding = lambda *a, **k: (0.0, {"skipped": True})
        _judge.score_experiment_quality = lambda *a, **k: (0.0, {"skipped": True})
        import biodiscoverygym.scoring.evaluator_v2 as _ev2
        _ev2.score_mechanism_grounding = _judge.score_mechanism_grounding
        _ev2.score_experiment_quality = _judge.score_experiment_quality

    from biodiscoverygym.scoring import EvaluatorV2

    evaluator = EvaluatorV2(data_dir=data_dir, llm_model=args.llm_model)

    print("\nRunning v2 scoring components...")
    report = evaluator.score(
        discovery=discovery,
        expression=expression,
        metadata=metadata,
        mutation=mutation,
        rppa=rppa,
        sample_id_map=sample_id_map,
        cohort=cohort,
    )

    print(f"\n{report.pretty_print()}")
    print(f"\n  Scoring wall time: {report.wall_time_s:.1f}s")

    if args.save:
        out_path = episode_path.with_suffix("").with_suffix("") \
            if episode_path.name.endswith(".json") \
            else episode_path
        out_path = episode_path.parent / (episode_path.stem + "_v2scores.json")
        out_path.write_text(json.dumps(report.to_dict(), indent=2))
        print(f"\n  Saved → {out_path}")

    print()


if __name__ == "__main__":
    main()
