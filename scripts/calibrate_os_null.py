"""
Null-baseline calibration for the OS discovery scorer.

For each scoring component, what would a random gene-set + random partition
score? This is the chance floor; real episode scores should beat it. Use the
saved baseline to interpret per-episode reports.

Two modes:
  --partition random   : random k-cluster assignment per iteration
                         (isolates the chance floor for BOTH partition and gene-set)
  --partition fixed-from EPISODE_JSON
                       : use a real episode's partition for every iteration
                         (isolates the gene-set-only effect — partition quality held constant)

LLM-judge components (mechanistic_grounding, validation_experiment,
exam_mechanistic_integration) are bypassed — they need real mechanism text.

Usage:
    python scripts/calibrate_os_null.py
    python scripts/calibrate_os_null.py --n-iter 200 --gene-set-size 15
    python scripts/calibrate_os_null.py --partition fixed-from results/external/run9_marker/273ab6f0/os_g2_s0_run9_marker.json

Output: data/calibration/os_null_baseline_<mode>_n<N>_s<seed>.json
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))

OS_DATA_DIR = "data/external/os_jia2022"
TARGET_DATA_DIR = "data/external/TARGET"
OUT_DIR = Path("data/calibration")


def parse_args():
    p = argparse.ArgumentParser(description="Null-baseline calibration for OS discovery scorer")
    p.add_argument("--n-iter", type=int, default=100)
    p.add_argument("--gene-set-size", type=int, default=15)
    p.add_argument("--partition", choices=["random", "fixed-from"], default="random")
    p.add_argument("--fixed-partition-source", type=str, default="",
                   help="Path to episode JSON to extract partition from (if --partition fixed-from)")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--data-dir", default="data")
    p.add_argument("--target-dir", default=TARGET_DATA_DIR)
    return p.parse_args()


def install_llm_stubs():
    """Replace LLM judges with zero-returning stubs so we don't hit the API."""
    _skip = lambda *a, **k: (0.0, {"skipped": "null baseline"})
    import biodiscoverygym.scoring.judge as _judge
    import biodiscoverygym.scoring.judge_os as _judge_os
    _judge.score_experiment_quality = _skip
    _judge_os.score_mechanism_grounding_os = _skip
    _judge_os.score_exam_mechanistic_integration_os = _skip
    import biodiscoverygym.scoring.evaluator_os as _ev_os
    _ev_os.score_experiment_quality = _skip
    _ev_os.score_mechanism_grounding_os = _skip
    _ev_os.score_exam_mechanistic_integration_os = _skip


def load_dataset(data_dir, seed: int | None = None):
    """Load SGH-OS dataset. If `seed` is given, also apply the per-episode
    sample-ID rename so partitions saved under that seed (SAMPLE_XXXX keys)
    can be matched to the dataset index."""
    from biodiscoverygym.utils.data_loader import DataLoader
    from biodiscoverygym.utils.hidden_context import DataAnonymizer
    loader = DataLoader(Path(data_dir))
    dataset = loader.load_tcga("OS", tcga_dir=Path(OS_DATA_DIR))
    dataset = DataAnonymizer.mask(dataset)
    if seed is not None:
        rng = np.random.default_rng(seed)
        original_ids = dataset["expression"].index.tolist()
        shuffled = original_ids.copy()
        rng.shuffle(shuffled)
        anon_ids = [f"SAMPLE_{i:04d}" for i in range(len(shuffled))]
        rename = dict(zip(shuffled, anon_ids))
        out = {}
        for k, v in dataset.items():
            if isinstance(v, pd.DataFrame):
                out[k] = v.rename(index=rename)
            else:
                out[k] = v
        dataset = out
    return dataset


def random_partition(sample_ids, rng: np.random.Generator, k_choices=(2, 3, 4),
                     min_size: int = 8) -> dict[str, str]:
    """Shuffle samples and split into k roughly-equal groups. Re-roll if any group < min_size."""
    sample_ids = list(sample_ids)
    for _attempt in range(10):
        k = int(rng.choice(k_choices))
        shuffled = sample_ids.copy()
        rng.shuffle(shuffled)
        splits = np.array_split(shuffled, k)
        if min(len(s) for s in splits) >= min_size:
            return {s: f"Cluster_{i}" for i, group in enumerate(splits) for s in group}
    # Fall back: k=2 split — always satisfies min_size for n>=16
    splits = np.array_split(sample_ids, 2)
    return {s: f"Cluster_{i}" for i, group in enumerate(splits) for s in group}


def load_fixed_partition(episode_json_path: str) -> tuple[dict[str, str], int]:
    """Load partition + seed. Seed is needed to rename the SGH-OS dataset index
    so partition keys (SAMPLE_XXXX) match the expression DataFrame."""
    ep = json.loads(Path(episode_json_path).read_text())
    discovery = ep.get("discovery", {}) or {}
    pg = discovery.get("proposed_grouping", {})
    if isinstance(pg, str):
        pg = json.loads(Path(pg).read_text())
    if not pg:
        raise ValueError(f"No partition found in {episode_json_path}")
    seed = int(ep.get("seed", 42))
    return pg, seed


def main():
    args = parse_args()
    rng = np.random.default_rng(args.seed)
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    install_llm_stubs()

    # If fixed partition, peek at its seed first so we can rename the dataset to match
    fixed_grouping = None
    fixed_seed = None
    if args.partition == "fixed-from":
        if not args.fixed_partition_source:
            print("Error: --fixed-partition-source required for --partition fixed-from", file=sys.stderr)
            sys.exit(1)
        fixed_grouping, fixed_seed = load_fixed_partition(args.fixed_partition_source)

    print(f"Loading SGH-OS dataset...")
    dataset = load_dataset(args.data_dir, seed=fixed_seed)
    expression = dataset["expression"]
    metadata = dataset["metadata"]
    mutation = dataset.get("mutation")
    methylation = dataset.get("methylation")
    cna = dataset.get("cna")
    print(f"  {len(expression)} samples × {expression.shape[1]} genes")
    print(f"  Methylation: {'available' if methylation is not None else 'none'}")
    print(f"  CNA: {'available' if cna is not None else 'none'}")

    if fixed_grouping is not None:
        n_intersect = len(set(fixed_grouping) & set(expression.index))
        print(f"  Fixed partition: {len(fixed_grouping)} samples, "
              f"{len(set(fixed_grouping.values()))} clusters, "
              f"seed={fixed_seed}, intersects {n_intersect} dataset samples")
        if n_intersect < 10:
            print("  ERROR: partition sample IDs don't match dataset — check seed", file=sys.stderr)
            sys.exit(1)

    from biodiscoverygym.scoring import EvaluatorOS
    evaluator = EvaluatorOS(data_dir=Path(args.data_dir), target_data_dir=Path(args.target_dir))

    print(f"\nRunning {args.n_iter} iterations (gene-set size = {args.gene_set_size}, partition = {args.partition})...")

    component_scores = defaultdict(list)
    gene_candidates = list(expression.columns)
    sample_ids = list(expression.index)

    import time
    t0 = time.time()
    for i in range(args.n_iter):
        # Random gene-set
        top_genes = list(rng.choice(gene_candidates, size=args.gene_set_size, replace=False))

        # Partition
        if fixed_grouping is not None:
            grouping = fixed_grouping
        else:
            grouping = random_partition(sample_ids, rng=rng)

        discovery = {
            "proposed_grouping": grouping,
            "top_genes": top_genes,
            "pathway_evidence": [],
            "mechanism_hypothesis": "",
            "next_experiment": "",
        }

        # Phase 1
        report = evaluator.score(
            discovery=discovery,
            expression=expression,
            metadata=metadata,
            mutation=mutation,
            methylation=methylation,
            cna=cna,
        )
        for key, raw in report.raw_scores.items():
            component_scores[key].append(raw)

        # Phase 3
        ext = evaluator.score_external_validation(
            discovery=discovery,
            expression=expression,
            metadata=metadata,
        )
        for key, raw in ext.raw_scores.items():
            component_scores[key].append(raw)

        if (i + 1) % max(1, args.n_iter // 20) == 0 or i == 0:
            elapsed = time.time() - t0
            eta = elapsed * (args.n_iter - i - 1) / (i + 1)
            print(f"  iter {i+1:>4}/{args.n_iter} | elapsed {elapsed:>5.0f}s | ETA {eta:>5.0f}s")

    # Summary
    print("\n" + "=" * 78)
    print(f"  Null-baseline summary (n={args.n_iter}, mode={args.partition})")
    print("=" * 78)
    print(f"  {'Component':<35} {'Mean':>6} {'SD':>6} {'P5':>6} {'P50':>6} {'P95':>6}")
    print("  " + "-" * 72)

    summary = {}
    for key, scores in component_scores.items():
        arr = np.array(scores)
        s = {
            "mean": float(np.mean(arr)),
            "std": float(np.std(arr)),
            "p5":   float(np.percentile(arr, 5)),
            "p10":  float(np.percentile(arr, 10)),
            "p50":  float(np.percentile(arr, 50)),
            "p90":  float(np.percentile(arr, 90)),
            "p95":  float(np.percentile(arr, 95)),
            "n": int(len(arr)),
        }
        summary[key] = s
        print(f"  {key:<35} {s['mean']:>6.3f} {s['std']:>6.3f} {s['p5']:>6.3f} {s['p50']:>6.3f} {s['p95']:>6.3f}")

    out = {
        "config": {
            "n_iter": args.n_iter,
            "gene_set_size": args.gene_set_size,
            "partition_mode": args.partition,
            "seed": args.seed,
        },
        "components": summary,
    }
    if args.partition == "fixed-from":
        out["config"]["fixed_partition_source"] = args.fixed_partition_source

    out_path = OUT_DIR / f"os_null_baseline_{args.partition}_n{args.n_iter}_s{args.seed}.json"
    out_path.write_text(json.dumps(out, indent=2))
    print(f"\nSaved → {out_path}")


if __name__ == "__main__":
    main()
