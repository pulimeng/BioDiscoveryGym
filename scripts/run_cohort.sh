#!/usr/bin/env bash
# run_cohort.sh — single-cohort benchmark runner + scorer (OS, BRCA, etc.)
#
# Runs G0/G1/G2 episodes for one cohort across configurable seeds, then scores.
# For the full TCGA sweep (7 cohorts), use run_tcga.sh instead.
#
# Usage:
#   bash scripts/run_cohort.sh --tag run5_clinAnon --cohort OS
#   bash scripts/run_cohort.sh --tag run6_opus --cohort OS --model claude-opus-4-7 --g2-seeds "0 1 7"
#   bash scripts/run_cohort.sh --tag brca_test --cohort BRCA --g0-seeds "42" --g1-seeds "" --g2-seeds ""
#
# Required:
#   --tag TAG           Run label, used as results subfolder name (e.g. run5_clinAnon)
#
# Optional:
#   --cohort COHORT     Cancer cohort (default: OS)
#   --model MODEL       Anthropic model ID (default: claude-sonnet-4-6)
#   --g0-seeds SEEDS    Space-separated seed list for G0 (default: "0 1 7")
#   --g1-seeds SEEDS    Space-separated seed list for G1 (default: "0 1 7 42 123")
#   --g2-seeds SEEDS    Space-separated seed list for G2 (default: "0 1 7 42 123")
#   --results-base DIR  Root output directory (default: results/cohort/external for OS,
#                       results/cohort for TCGA cohorts)
#   --max-tool-calls N  Phase 1 tool call budget (default: 100)
#   --no-examination    Disable Examination stage (dev/debug only)
#   --skip-score        Run episodes but skip scoring afterwards
#   --score-only        Skip running; score existing results in the output folder
#   --dry-run           Print commands without executing them

set -euo pipefail

# ── Defaults ─────────────────────────────────────────────────────────────────
TAG=""
COHORT="OS"
MODEL="claude-sonnet-4-6"
G0_SEEDS="0 1 7"
G1_SEEDS="0 1 7 42 123"
G2_SEEDS="0 1 7 42 123"
RESULTS_BASE=""
MAX_TOOL_CALLS=100
NO_EXAMINATION=0
SKIP_SCORE=0
SCORE_ONLY=0
DRY_RUN=0

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
        --dry-run)        DRY_RUN=1;        shift ;;
        -h|--help)
            sed -n '2,30p' "$0" | sed 's/^# \{0,1\}//'
            exit 0 ;;
        *)
            echo "Unknown argument: $1" >&2
            echo "Run with --help for usage." >&2
            exit 1 ;;
    esac
done

# ── Validation ────────────────────────────────────────────────────────────────
if [[ -z "$TAG" ]]; then
    echo "Error: --tag is required." >&2
    echo "Example: bash scripts/run_cohort.sh --tag run5_clinAnon --cohort OS" >&2
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
        RESULTS_BASE="results/task_a/external/${TAG}"
    else
        RESULTS_BASE="results/task_a/${TAG}"
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
echo "  BioDiscoveryGym Benchmark Run"
echo "  Tag     : ${TAG}"
echo "  Cohort  : ${COHORT}"
echo "  Model   : ${MODEL}"
echo "  G0 seeds: ${G0_SEEDS:-"(none)"}"
echo "  G1 seeds: ${G1_SEEDS:-"(none)"}"
echo "  G2 seeds: ${G2_SEEDS:-"(none)"}"
echo "  Max calls: ${MAX_TOOL_CALLS} (Phase 1)"
echo "  Exam    : $([ $NO_EXAMINATION -eq 1 ] && echo disabled || echo enabled)"
echo "  Output  : ${RESULTS_BASE}/<uuid>/"
[[ $DRY_RUN -eq 1 ]] && echo "  Mode    : DRY RUN — no episodes will run"
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

    if [[ $DRY_RUN -eq 1 ]]; then
        echo "  [dry-run] $cmd"
    else
        eval "$cmd"
    fi
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
        echo "=== G2: data-driven (gene codebook gated at call 25) ==="
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
    if [[ $DRY_RUN -eq 1 ]]; then
        echo "  [dry-run] bash scripts/score_all_withMeth.sh ${RESULTS_BASE}"
    else
        bash scripts/score_all_withMeth.sh "${RESULTS_BASE}"
    fi
fi

echo ""
echo "============================================================"
echo "  Done. Results: ${RESULTS_BASE}/"
echo "============================================================"
