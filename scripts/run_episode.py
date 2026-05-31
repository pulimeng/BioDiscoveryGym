"""
Run a single BioDiscoveryGym episode with ClaudeAgent.

Usage:
    python scripts/run_episode.py --cohort BRCA
    python scripts/run_episode.py --cohort PRAD --seed 7 --model claude-opus-4-7
    python scripts/run_episode.py --cohort BRCA --max-tool-calls 100 --quiet

Requires ANTHROPIC_API_KEY in the environment.
Results are printed to stdout; the full conversation is NOT saved by default
(add --save-log to write a JSON trace).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

VALID_COHORTS = ["BRCA", "PRAD", "UCEC", "LUAD", "LIHC", "LUSC", "OV", "OS"]

# External cohorts not under data/tcga/ — map cohort name → data directory
EXTERNAL_COHORT_DIRS: dict[str, str] = {
    "OS": "data/external/os_jia2022",
}


def _serialize_messages(messages: list) -> list:
    """Convert SDK message objects to plain dicts for JSON serialization."""
    out = []
    for msg in messages:
        role = msg.get("role", "")
        content = msg.get("content", "")
        if isinstance(content, list):
            blocks = []
            for b in content:
                if isinstance(b, dict):
                    blocks.append(b)
                elif hasattr(b, "type") and b.type == "thinking":
                    # Preserve thinking blocks explicitly — model_dump may omit signature
                    blocks.append({
                        "type": "thinking",
                        "thinking": getattr(b, "thinking", ""),
                        "signature": getattr(b, "signature", ""),
                    })
                elif hasattr(b, "model_dump"):
                    blocks.append(b.model_dump())
                else:
                    blocks.append({"type": str(type(b)), "raw": str(b)})
            out.append({"role": role, "content": blocks})
        else:
            out.append({"role": role, "content": content})
    return out


def parse_args():
    p = argparse.ArgumentParser(description="Run a BioDiscoveryGym episode.")
    p.add_argument(
        "--cohort",
        required=True,
        choices=VALID_COHORTS,
        metavar="COHORT",
        help=f"Cancer cohort to run. One of: {', '.join(VALID_COHORTS)}",
    )
    p.add_argument("--seed", type=int, default=42, help="Random seed (default: 42)")
    p.add_argument(
        "--model",
        default="claude-sonnet-4-6",
        help="Anthropic model ID (default: claude-sonnet-4-6 ~$3/ep; use claude-opus-4-7 ~$15/ep for final runs)",
    )
    p.add_argument(
        "--max-tool-calls",
        type=int,
        default=100,
        help="Max tool calls for Phase 1 discovery before forcing submission (default: 100)",
    )
    p.add_argument(
        "--data-dir",
        default="data",
        help="Root data directory (default: data)",
    )
    p.add_argument(
        "--results-base",
        default=None,
        metavar="DIR",
        help=(
            "Root directory for episode output. Episode UUID subdir is created inside it. "
            "Defaults to results/cohort/external/ for external cohorts, results/cohort/ otherwise."
        ),
    )
    p.add_argument(
        "--mislead-cohort",
        metavar="COHORT",
        help="Inject wrong sample barcodes via a fake sample codebook (e.g. --mislead-cohort LUAD on a LIHC run).",
    )
    p.add_argument(
        "--sample-codebook-gate",
        type=int,
        default=25,
        help="Tool calls before the fake sample codebook is released (default: 25; use 0 to pre-reveal at start)",
    )
    p.add_argument(
        "--gene-codebook-gate",
        type=int,
        default=25,
        help="Tool calls before the gene codebook is released (default: 25; use 0 to pre-reveal at start)",
    )
    p.add_argument(
        "--thinking-budget",
        type=int,
        default=0,
        help="Extended thinking token budget per turn (default: 0 = off; try 2000–4000 for targeted runs)",
    )
    p.add_argument(
        "--no-examination",
        action="store_true",
        help="Skip the Examination stage (Data Lock + Q1-Q4) after submit_discovery. "
             "Use for cheap dev/debug runs only.",
    )
    p.add_argument(
        "--examination-max-calls",
        type=int,
        default=40,
        help="Max tool calls for Examination Q1-Q4 (default: 40)",
    )
    p.add_argument(
        "--data-lock-max-calls",
        type=int,
        default=20,
        help="Max tool calls for Examination Data Lock sweep (default: 20)",
    )
    p.add_argument(
        "--explicit-retrieval",
        action="store_true",
        help=(
            "Reveal the cohort name to the agent (explicit retrieval baseline). "
            "Forces --gene-codebook-gate 0. One run per cohort gives the G0 baseline."
        ),
    )
    p.add_argument(
        "--perturb",
        action="store_true",
        help=(
            "Load survival-inverted + mutation-swapped data (LIHC only). "
            "Run scripts/perturb_lihc.py first to build the perturbed files."
        ),
    )
    p.add_argument(
        "--primekg",
        action="store_true",
        help="Give the agent access to PrimeKG knowledge graph for mechanistic reasoning.",
    )
    p.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress per-turn agent log lines",
    )
    p.add_argument(
        "--save-log",
        metavar="PATH",
        help="Write episode result JSON to this file",
    )
    return p.parse_args()


def check_env():
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("Error: ANTHROPIC_API_KEY is not set.", file=sys.stderr)
        sys.exit(1)


def main():
    args = parse_args()
    check_env()

    from biodiscoverygym.episode import Episode
    from agents.claude_agent_cohort import ClaudeAgentCohort

    print(f"\n{'='*60}")
    print(f"  BioDiscoveryGym Episode")
    print(f"  Cohort : {args.cohort.upper()}")
    print(f"  Seed   : {args.seed}")
    print(f"  Model  : {args.model}")
    if args.explicit_retrieval:
        args.gene_codebook_gate = 0

    gene_gate_str = "pre-reveal" if args.gene_codebook_gate == 0 else f"gate={args.gene_codebook_gate}"
    if args.explicit_retrieval:
        mode = "explicit-retrieval(cohort+genes revealed)"
    elif args.gene_codebook_gate == 0:
        mode = "implicit-retrieval"
    else:
        mode = f"data-driven({gene_gate_str})"
    if args.mislead_cohort:
        sc_gate_str = "pre-reveal" if args.sample_codebook_gate == 0 else f"gate={args.sample_codebook_gate}"
        mode += f" + mislead({args.mislead_cohort}, {sc_gate_str})"
    if args.perturb:
        mode += " + PERTURBED(survival+mutations)"
    print(f"  Mode   : {mode}")
    print(f"{'='*60}\n")

    if args.no_examination:
        print(f"  Examination : DISABLED (--no-examination)\n")
    else:
        print(f"  Examination : Data Lock ({args.data_lock_max_calls} calls) + Q1-Q4 ({args.examination_max_calls} calls)\n")

    episode = Episode.from_cohort(
        cohort=args.cohort,
        seed=args.seed,
        data_dir=args.data_dir,
        anonymize_genes=True,
        perturb=args.perturb,
        tcga_dir=EXTERNAL_COHORT_DIRS.get(args.cohort.upper()),
        rename_clinical=not args.explicit_retrieval,  # G0: real values; G1/G2: categorical values remapped to CAT_X
    )

    agent = ClaudeAgentCohort(
        model=args.model,
        max_tool_calls=args.max_tool_calls,
        data_dir=args.data_dir,
        verbose=not args.quiet,
        gene_map=episode._gene_map,
        codebook_gate=args.gene_codebook_gate,
        mislead_cohort=args.mislead_cohort,
        sample_codebook_gate=args.sample_codebook_gate,
        explicit_cohort=args.cohort if args.explicit_retrieval else None,
        primekg=args.primekg,
        clinical_codebook=episode.dataset.get("clinical_codebook", {}),
        thinking_budget=args.thinking_budget,
        no_examination=args.no_examination,
        examination_max_calls=args.examination_max_calls,
        data_lock_max_calls=args.data_lock_max_calls,
    )

    if args.results_base:
        results_base = Path(args.results_base)
    elif args.cohort.upper() in EXTERNAL_COHORT_DIRS:
        results_base = Path("results") / "cohort" / "external"
    else:
        results_base = Path("results") / "cohort"
    result = episode.run(agent, results_base=results_base)

    # Print results
    print(f"\n{'='*60}")
    print(f"  Episode {episode.episode_id} complete")
    print(f"{'='*60}")
    print(f"  Wall time     : {result.wall_time_s:.1f}s")

    if result.discovery:
        pkg = result.discovery
        print(f"\n  Submission summary:")
        print(f"    Samples grouped   : {len(pkg.get('proposed_grouping', {}))}")
        print(f"    Top genes         : {pkg.get('top_genes', [])[:5]}")
        print(f"    Confidence        : {pkg.get('confidence', 'N/A')}")
    else:
        print("\n  No submission received.")

    if args.save_log:
        artifact_dir = Path(result.output_dir) if result.output_dir else Path(args.save_log).parent
        log_path = artifact_dir / Path(args.save_log).name

        serialized_messages = _serialize_messages(result.messages)

        out = {
            "episode_id": episode.episode_id,
            "cohort": args.cohort,
            "seed": args.seed,
            "model": args.model,
            "wall_time_s": result.wall_time_s,
            "cli": {
                "max_tool_calls": args.max_tool_calls,
                "gene_codebook_gate": args.gene_codebook_gate,
                "explicit_retrieval": args.explicit_retrieval,
                "mislead_cohort": args.mislead_cohort,
                "sample_codebook_gate": args.sample_codebook_gate,
                "perturb": args.perturb,
                "no_examination": args.no_examination,
                "examination_max_calls": args.examination_max_calls,
                "data_lock_max_calls": args.data_lock_max_calls,
            },
            "discovery": result.discovery,
            "observations": result.run_log.get("observations", []),
            "run_log": result.run_log,
            "messages": serialized_messages,
        }
        log_path.write_text(json.dumps(out, indent=2))
        print(f"\n  Saved JSON  → {log_path}")

        # Generate markdown report
        from biodiscoverygym.report import generate_markdown

        # Patch messages back as dicts for report generator
        result.messages = serialized_messages
        md = generate_markdown(
            result=result,
            episode_id=episode.episode_id,
            cohort=args.cohort,
            model=args.model,
            seed=args.seed,
        )
        md_path = log_path.with_suffix(".md")
        md_path.write_text(md)
        print(f"  Saved report → {md_path}")

    print()


if __name__ == "__main__":
    main()
