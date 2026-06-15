#!/usr/bin/env bash
# run_cohort.sh — single-cohort benchmark runner + scorer (OS, BRCA, etc.)
#
# Runs G0/G1/G2 episodes for one cohort across configurable seeds, then scores.
# For the full TCGA sweep (7 cohorts), use run_tcga.sh instead.
#
# Usage:
#   bash scripts/run_cohort.sh --tag run8 --cohort OS
#   bash scripts/run_cohort.sh --tag run8_opus --cohort OS --model claude-opus-4-7 --g2-seeds "0 1 7"
#   bash scripts/run_cohort.sh --tag brca_test --cohort BRCA --g0-seeds "42" --g1-seeds "" --g2-seeds ""
#   bash scripts/run_cohort.sh --smoke-test --cohort OS          # pipeline check: 1 seed/mode, 15 calls
#
# Required (unless --smoke-test):
#   --tag TAG           Run label, used as results subfolder name (e.g. run8)
#
# Optional:
#   --cohort COHORT     Cancer cohort (default: OS)
#   --model MODEL       Anthropic model ID (default: claude-sonnet-4-6)
#   --g0-seeds SEEDS    Space-separated seed list for G0 (default: "0 1 7")
#   --g1-seeds SEEDS    Space-separated seed list for G1 (default: "0 1 7")
#   --g2-seeds SEEDS    Space-separated seed list for G2 (default: "0 1 7")
#   --results-base DIR  Root output directory (default: results/external/ for OS,
#                       results/tcga/ for TCGA cohorts)
#   --max-tool-calls N  Phase 1 tool call budget (default: 100)
#   --no-examination    Disable Examination stage (dev/debug only)
#   --skip-score        Run episodes but skip scoring afterwards
#   --score-only        Skip running; score existing results in the output folder
#   --smoke-test        Pipeline check: 1 seed/mode (seed=42), max-tool-calls=15,
#                       no examination, output to results/[external/]smoke-test/

set -euo pipefail

# ── Defaults ─────────────────────────────────────────────────────────────────
TAG=""
COHORT="OS"
MODEL="claude-sonnet-4-6"
G0_SEEDS="0 1 7"
G1_SEEDS="0 1 7"
G2_SEEDS="0 1 7"
RESULTS_BASE=""
MAX_TOOL_CALLS=100
NO_EXAMINATION=0
SKIP_SCORE=0
SCORE_ONLY=0
SMOKE_TEST=0

# ── Argument parsing ──────────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
    case "$1" in
        --tag)            TAG="$2";              shift 2 ;;
        --cohort)         COHORT="$(echo "$2" | tr '[:lower:]' '[:upper:]')"; shift 2 ;;
        --model)          MODEL="$2";             shift 2 ;;
        --g0-seeds)       G0_SEEDS="$2";          shift 2 ;;
        --g1-seeds)       G1_SEEDS="$2";          shift 2 ;;
        --g2-seeds)       G2_SEEDS="$2";          shift 2 ;;
        --results-base)   RESULTS_BASE="$2";      shift 2 ;;
        --max-tool-calls) MAX_TOOL_CALLS="$2";    shift 2 ;;
        --no-examination) NO_EXAMINATION=1;  shift ;;
        --skip-score)     SKIP_SCORE=1;     shift ;;
        --score-only)     SCORE_ONLY=1;     shift ;;
        --smoke-test)     SMOKE_TEST=1;     shift ;;
        -h|--help)
            sed -n '2,32p' "$0" | sed 's/^# \{0,1\}//'
            exit 0 ;;
        *)
            echo "Unknown argument: $1" >&2
            echo "Run with --help for usage." >&2
            exit 1 ;;
    esac
done

# ── Smoke-test overrides ──────────────────────────────────────────────────────
if [[ $SMOKE_TEST -eq 1 ]]; then
    [[ -z "$TAG" ]] && TAG="smoke-test"
    G0_SEEDS="42"
    G1_SEEDS="42"
    G2_SEEDS="42"
    [[ $MAX_TOOL_CALLS -gt 15 ]] && MAX_TOOL_CALLS=15
    NO_EXAMINATION=1
fi

# ── Validation ────────────────────────────────────────────────────────────────
if [[ -z "$TAG" ]]; then
    echo "Error: --tag is required (or use --smoke-test to default to 'dry-run')." >&2
    echo "Example: bash scripts/run_cohort.sh --tag run7_unified --cohort OS" >&2
    exit 1
fi

if [[ -z "${ANTHROPIC_API_KEY:-}" ]]; then
    echo "Error: ANTHROPIC_API_KEY is not set." >&2
    exit 1
fi

# ── Resolve results base ──────────────────────────────────────────────────────
EXTERNAL_COHORTS="OS"   # space-separated list of non-TCGA cohorts
if [[ -z "$RESULTS_BASE" ]]; then
    if [[ " $EXTERNAL_COHORTS " == *" $COHORT "* ]]; then
        RESULTS_BASE="results/external/${TAG}"
    else
        RESULTS_BASE="results/${TAG}"
    fi
else
    RESULTS_BASE="${RESULTS_BASE}/${TAG}"
fi

# ── Build extra flags ─────────────────────────────────────────────────────────
EXTRA_FLAGS="--max-tool-calls ${MAX_TOOL_CALLS}"
[[ $NO_EXAMINATION -eq 1 ]] && EXTRA_FLAGS="$EXTRA_FLAGS --no-examination"

# ── Summary ───────────────────────────────────────────────────────────────────
echo ""
echo "============================================================"
if [[ $SMOKE_TEST -eq 1 ]]; then
echo "  BioDiscoveryGym  *** SMOKE TEST ***"
else
echo "  BioDiscoveryGym Benchmark Run"
fi
echo "  Tag     : ${TAG}"
echo "  Cohort  : ${COHORT}"
echo "  Model   : ${MODEL}"
echo "  G0 seeds: ${G0_SEEDS:-"(none)"}"
echo "  G1 seeds: ${G1_SEEDS:-"(none)"}"
echo "  G2 seeds: ${G2_SEEDS:-"(none)"}"
echo "  Max calls: ${MAX_TOOL_CALLS} (Phase 1)"
echo "  Exam    : $([ $NO_EXAMINATION -eq 1 ] && echo disabled || echo enabled)"
echo "  Output  : ${RESULTS_BASE}/"
[[ $SMOKE_TEST -eq 1 ]] && echo "  Mode    : SMOKE TEST — 1 seed/mode, budget=15, no exam"
echo "============================================================"
echo ""

# ── Episode runner ────────────────────────────────────────────────────────────
run_episode() {
    local mode="$1"
    local seed="$2"
    local mode_args="$3"
    local cohort_lower
    cohort_lower="$(echo "$COHORT" | tr '[:upper:]' '[:lower:]')"
    local label="${cohort_lower}_${mode}_s${seed}_${TAG}"

    echo "------------------------------------------------------------"
    echo "  ${mode} | seed=${seed}"
    echo "------------------------------------------------------------"

    local cmd="python scripts/run_episode.py \
        --cohort ${COHORT} \
        --seed ${seed} \
        --model ${MODEL} \
        --quiet \
        --results-base ${RESULTS_BASE} \
        ${EXTRA_FLAGS} \
        ${mode_args} \
        --save-log ${label}.json"

    eval "$cmd"
    echo ""
}

# ── Run episodes ─────────────────────────────────────────────────────────────
if [[ $SCORE_ONLY -eq 0 ]]; then
    if [[ -n "$G0_SEEDS" ]]; then
        echo "=== G0: explicit retrieval ==="
        for seed in $G0_SEEDS; do
            run_episode "g0" "$seed" "--explicit-retrieval"
        done
    fi

    if [[ -n "$G1_SEEDS" ]]; then
        echo "=== G1: implicit retrieval (gene codebook pre-revealed) ==="
        for seed in $G1_SEEDS; do
            run_episode "g1" "$seed" "--gene-codebook-gate 0"
        done
    fi

    if [[ -n "$G2_SEEDS" ]]; then
        echo "=== G2: data-driven (gene codebook gate: 12 for OS, 8 for TCGA) ==="
        for seed in $G2_SEEDS; do
            run_episode "g2" "$seed" ""
        done
    fi
fi

# ── Score ─────────────────────────────────────────────────────────────────────
if [[ $SKIP_SCORE -eq 0 ]]; then
    echo ""
    echo "============================================================"
    echo "  Scoring all episodes in ${RESULTS_BASE}"
    echo "============================================================"
    bash scripts/score_all_os.sh "${RESULTS_BASE}"
fi

echo ""
echo "============================================================"
echo "  Done. Results: ${RESULTS_BASE}/"
echo "============================================================"
