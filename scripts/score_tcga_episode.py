"""
Post-hoc TCGA scoring for a completed BioDiscoveryGym episode.

Faithfulness rubric — scores whether the agent derived the known TCGA subtype
biology through data-driven reasoning vs prior recall. Runs all v2 components
AND extracts an agent trace from the raw message log.

Usage:
    python scripts/score_tcga_episode.py path/to/episode.json --cohort BRCA --save
    python scripts/score_tcga_episode.py path/to/episode.json --cohort LUAD --save --skip-llm

Outputs (with --save):
    <episode>_v3scores.json   — score components + weighted total + trace summary
    <episode>_v3trace.json    — full per-call trace (reasoning + tool calls)
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from biodiscoverygym.scoring.judge import (DEFAULT_JUDGE_MODEL, is_benchmarked_family,
                                           required_key_env)

sys.path.insert(0, str(Path(__file__).parent.parent))


def parse_args():
    p = argparse.ArgumentParser(description="Score a BioDiscoveryGym v3 episode post-hoc.")
    p.add_argument("episode_json", help="Path to episode result JSON (from --save-log)")
    p.add_argument("--cohort", default=None,
                   help="Cohort name (e.g. BRCA). Reads from episode JSON if omitted.")
    p.add_argument("--data-dir", default="data", help="Root data directory (default: data)")
    p.add_argument("--save", action="store_true", help="Save score + trace JSON files")
    p.add_argument("--judge-tag", default=None,
                   help="judge tag naming the output directory: "
                        "<episode>/scoring/<tag>/v3scores.json. Defaults to the panel tag "
                        "matching --llm-model.")
    p.add_argument("--llm-model", default=DEFAULT_JUDGE_MODEL,
                   help="judge model for outcome LLM components (NEUTRAL family). "
                        "deepseek-v4-pro (default) / claude-* / gpt-*")
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


def _tag_for(model, tag=None):
    """Panel tag for an output directory; falls back to the tag whose model matches."""
    import judges_config as _J
    if tag:
        return tag
    for t, m, _ in _J.PANEL:
        if m == model:
            return t
    raise SystemExit(f"no panel tag for model {model!r}; pass --judge-tag explicitly "
                     f"(known tags: {_J.tags()})")


def main():
    args = parse_args()

    # Fail-fast guard: missing judge API key silently zeros all LLM judges and looks
    # like a low real score. Which key depends on the judge model (neutral by default).
    import os
    _need = required_key_env(args.llm_model)
    if is_benchmarked_family(args.llm_model):
        print(f"\n  !! NEUTRALITY WARNING: judge model {args.llm_model} belongs to a family UNDER\n"
              f"     EVALUATION in this benchmark (gpt / claude / gemini). Self-preference is\n"
              f"     available to it, so its labels are not a neutral measurement. Use a neutral\n"
              f"     judge (nemotron-3-super, laguna, qwen*, deepseek*) for anything reported.\n",
              file=sys.stderr)
    if not args.skip_llm and not os.environ.get(_need):
        print(f"ERROR: {_need} is not set (judge model = {args.llm_model}).", file=sys.stderr)
        print("  This script invokes LLM judges that materially affect the score.", file=sys.stderr)
        print(f"  Either: export {_need}=...   OR  --skip-llm   (computational components only)",
              file=sys.stderr)
        sys.exit(1)

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
    # Mislead cohort (G3 arms) drives the cohort-identity gate: if the agent committed
    # to this wrong cancer type, the whole discovery is zeroed.
    mislead_cohort: str | None = (episode.get("cli") or {}).get("mislead_cohort")

    print(f"\n{'='*60}")
    print(f"  BioDiscoveryGym v3 Scorer (scores + trace)")
    print(f"  Cohort   : {cohort}")
    print(f"  Seed     : {seed}")
    print(f"  Messages : {len(messages)}")
    print(f"  Skip LLM : {args.skip_llm}")
    print(f"{'='*60}\n")

    data_dir = Path(args.data_dir)

    _EXTERNAL_COHORT_DIRS: dict[str, str] = {}

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

    print(f"  Samples : {len(expression)}, genes : {expression.shape[1]}")

    # Resolve grouping from file path if needed
    pg = discovery.get("proposed_grouping", {})
    if isinstance(pg, str):
        try:
            pg = json.loads(Path(pg).read_text())
        except Exception:
            pg = {}
    if not pg:
        # Recovery: the agent computed a grouping but passed a wrong/empty path to
        # submit_discovery (it sometimes hallucinates the output dir), so the saved
        # submission has an empty proposed_grouping. Fall back to the canonical
        # grouping.json the agent wrote into the episode dir — the work it actually did.
        fallback = episode_path.parent / "grouping.json"
        if fallback.exists():
            try:
                pg = json.loads(fallback.read_text())
                print(f"  [recovered] empty proposed_grouping → loaded {len(pg)} samples from {fallback.name}")
            except Exception:
                pass
    discovery["proposed_grouping"] = pg

    if args.skip_llm:
        import biodiscoverygym.scoring.judge as _judge
        _judge.score_mechanism_grounding = lambda *a, **k: (0.0, {"skipped": True})
        _judge.score_experiment_quality = lambda *a, **k: (0.0, {"skipped": True})
        _judge.score_exam_experiment_depth = lambda *a, **k: (0.0, {"skipped": True})
        _judge.score_exam_mechanistic_integration = lambda *a, **k: (0.0, {"skipped": True})
        # cohort-identity judge stub: no `fooled` flag → gate never fires under --skip-llm
        _judge.score_cohort_identity = lambda *a, **k: (0.0, {"verdict": "skipped"})
        import biodiscoverygym.scoring.evaluator_v2 as _ev2
        _ev2.score_mechanism_grounding = _judge.score_mechanism_grounding
        _ev2.score_experiment_quality = _judge.score_experiment_quality
        _ev2.score_exam_experiment_depth = _judge.score_exam_experiment_depth
        _ev2.score_exam_mechanistic_integration = _judge.score_exam_mechanistic_integration
        _ev2.score_cohort_identity = _judge.score_cohort_identity

    from biodiscoverygym.scoring import EvaluatorV3

    evaluator = EvaluatorV3(data_dir=data_dir, llm_model=args.llm_model)

    print("\nRunning v2 scoring + trace extraction...")
    score_report, trace_report = evaluator.score_and_trace(
        discovery=discovery,
        expression=expression,
        metadata=metadata,
        mutation=mutation,
        sample_id_map=sample_id_map,
        cohort=cohort,
        messages=messages,
        run_log=run_log or None,
        mislead_cohort=mislead_cohort,
    )

    print(f"\n{score_report.pretty_print()}")
    print(f"\n{trace_report.pretty_print()}")
    print(f"\n  Scoring wall time: {score_report.wall_time_s:.1f}s")

    # ---- refuse to persist a partially-measured episode --------------------------------------
    # Every LLM judge returns `0.0, {"error": ...}` on failure, so a failed judge is
    # indistinguishable from a dimension the agent genuinely scored zero on. That is how a
    # DeepSeek 402 once wrote mechanism_grounding=0.000 across 75 episodes and produced a
    # plausible-looking "the small model collapses" finding (docs/DATA_INTEGRITY_AUDIT.md).
    #
    # The distinction already exists in the data: legitimate zeros carry {"reason": ...},
    # failures carry {"error": ...}. Nothing read it. So: if ANY component failed, do not write a
    # score file and exit non-zero. score_all_tcga.sh already collects failures and tells the user
    # to re-run — that safety net existed the whole time and was bypassed only because scoring
    # reported success. This lets it work.
    # ZERO COMPONENTS is its own failure, and the loop below cannot see it: it looks for
    # components carrying an error, and an empty result has no components to carry one. That is how
    # a re-score of g3a_ov_mislead_brca_s7 wrote a second placeholder — 0 components, normalized
    # 0.0, wall_time 4e-06 — and printed "Saved". An episode with no partition is legitimate (the
    # agent submitted no grouping); a score FILE that records nothing about it is not.
    if not (score_report.raw_scores or {}):
        no_group = "no_grouping" in (score_report.diagnostics or {})
        verdict = score_report.cohort_identity_verdict
        print("\n  !! NO COMPONENTS SCORED.", file=sys.stderr)
        if no_group:
            print("     The episode submitted an EMPTY proposed_grouping, so every "
                  "partition-dependent", file=sys.stderr)
            print(f"     component is unscorable. Identity verdict = {verdict!r} "
                  f"(judged from the mechanism text).", file=sys.stderr)
            print("     Saving anyway BECAUSE the identity verdict is real; downstream code must "
                  "treat", file=sys.stderr)
            print("     `raw_scores == {}` as UNSCORED, never as a zero.", file=sys.stderr)
        else:
            print("     No empty-grouping diagnostic either — this is an unexplained empty result.",
                  file=sys.stderr)
            print("     NOT saving; re-run and investigate.", file=sys.stderr)
            return 1

    failed = []
    for comp, diag in (score_report.diagnostics or {}).items():
        if isinstance(diag, dict) and diag.get("error"):
            # FULL error text. Truncating to 120 chars cut a provider error off mid-message
            # — "Error code: 403 - {'type': 'virtual_key_blocked', ... 'message': 'V" — which
            # names the failure class but discards the sentence that says what to DO about it.
            # An error report that has to be re-derived by re-running the failure is not a report.
            failed.append((comp, str(diag["error"])))
    if failed:
        print("\n  !! SCORING INCOMPLETE — not saving. Failed component(s):", file=sys.stderr)
        for comp, err in failed:
            print(f"       {comp}: {err}", file=sys.stderr)
        print("  A failed judge returns 0.0, which is indistinguishable from a real zero, so this",
              file=sys.stderr)
        print("  episode is left UNSCORED rather than saved with a fabricated number.", file=sys.stderr)
        print("  Re-run once the cause is resolved (batch runner retries unscored episodes).",
              file=sys.stderr)
        sys.exit(1)

    if args.save:
        stem = episode_path.stem
        import judges_config as _J
        _tag = _tag_for(args.llm_model, args.judge_tag)
        _sdir = Path(_J.scoring_dir(str(episode_path.parent), _tag))
        _sdir.mkdir(parents=True, exist_ok=True)
        scores_path = _sdir / _J.ARTIFACTS["outcome"]
        # The trace summary is derived but judge-INDEPENDENT (pure trace statistics, no model
        # call), so it lives at the scoring root rather than under a judge, where filing it
        # would imply a judge produced it.
        trace_path = Path(_J.scoring_dir(str(episode_path.parent))) / _J.TRACE_FILE

        combined_scores = score_report.to_dict()
        combined_scores["trace_summary"] = {
            k: v for k, v in trace_report.to_dict().items() if k != "calls"
        }
        # PROVENANCE. Two fields in this file are LLM-derived — mechanism_grounding (a scored
        # component) and cohort_identity (the gate whose verdict IS the false-label adoption
        # result) — and nothing recorded which model produced them. Judge attribution in the
        # reports was being derived from the CoT summaries, a DIFFERENT artifact by a possibly
        # different model. Record it where it is used.
        combined_scores["judge_model"] = (None if args.skip_llm else args.llm_model)
        combined_scores["llm_components"] = ["mechanism_grounding", "cohort_identity"]
        # allow_nan=False: emit STRICT JSON or fail loudly. Python's json module writes bare
        # NaN/Infinity by default, which no strict parser accepts — three clean-run score
        # files shipped unparseable before this. A score file a consumer cannot read is a
        # broken artifact, and this turns that into an exception at write time.
        scores_path.write_text(json.dumps(combined_scores, indent=2, allow_nan=False))

        trace_path.write_text(json.dumps(trace_report.to_dict(), indent=2, allow_nan=False))

        print(f"\n  Saved → {scores_path}")
        print(f"  Saved → {trace_path}")

    print()


if __name__ == "__main__":
    main()
