#!/usr/bin/env bash
# Task A — full benchmark runner
# 67 runs: G0 (7) + G1 (21) + G2 (21) + G3 (18)
# ~$201 total on claude-sonnet-4-6 at ~$3/ep
#
# Usage:
#   bash taskA.sh              # run all groups
#   bash taskA.sh --dry-run    # print commands only, no API calls
#   bash taskA.sh --group G2   # run one group only (G0 / G1 / G2 / G3)
#
# Resume-safe: skips any run whose output file already exists.
# Logs saved to results/task_a/{group}_{cohort}_{seed}.json

set -euo pipefail

# ── Config ────────────────────────────────────────────────────────────────────
SCRIPT="python scripts/run_episode.py"
MODEL="${TASK_A_MODEL:-claude-sonnet-4-6}"  # override: TASK_A_MODEL=claude-opus-4-7 bash taskA.sh
MAX_CALLS=100
OUT_DIR="results/task_a"
COHORTS=(BRCA PRAD UCEC LUAD LIHC LUSC OV)
SEEDS=(42 7 123)

# G3 mislead pairs: "TRUE_COHORT:MISLEAD_AS"
# Add remaining 4 pairs here when finalized.
G3_PAIRS=(
    "OV:BRCA"
    "LUAD:LIHC"
    # "?:?"   TBD
    # "?:?"   TBD
    # "?:?"   TBD
    # "?:?"   TBD
)

# ── Args ──────────────────────────────────────────────────────────────────────
DRY_RUN=false
RUN_GROUP=""

for arg in "$@"; do
    case "$arg" in
        --dry-run) DRY_RUN=true ;;
        --group) ;;           # handled below with shift
        G0|G1|G2|G3) RUN_GROUP="$arg" ;;
    esac
done

# Re-parse for --group VALUE form
while [[ $# -gt 0 ]]; do
    case "$1" in
        --group) RUN_GROUP="${2:-}"; shift 2 ;;
        *) shift ;;
    esac
done

# ── Helpers ───────────────────────────────────────────────────────────────────
mkdir -p "$OUT_DIR"

run_episode() {
    local label="$1"; shift
    local out="$OUT_DIR/${label}.json"

    if [[ -f "$out" ]]; then
        echo "  SKIP  $label (already exists)"
        return
    fi

    echo "  RUN   $label"
    if [[ "$DRY_RUN" == "true" ]]; then
        echo "        $SCRIPT $* --save-log $out"
        return
    fi

    $SCRIPT "$@" --model "$MODEL" --max-tool-calls "$MAX_CALLS" \
        --quiet --save-log "$out"
}

check_key() {
    if [[ -z "${ANTHROPIC_API_KEY:-}" ]]; then
        echo "Error: ANTHROPIC_API_KEY is not set." >&2
        exit 1
    fi
}

# ── Groups ────────────────────────────────────────────────────────────────────

run_g0() {
    echo ""
    echo "=== G0: Explicit retrieval (7 runs, seed 42 only) ==="
    for cohort in "${COHORTS[@]}"; do
        run_episode "g0_${cohort,,}_s42" \
            --cohort "$cohort" --seed 42 --explicit-retrieval
    done
}

run_g1() {
    echo ""
    echo "=== G1: Implicit retrieval — gate=0, cohort hidden (21 runs) ==="
    for cohort in "${COHORTS[@]}"; do
        for seed in "${SEEDS[@]}"; do
            run_episode "g1_${cohort,,}_s${seed}" \
                --cohort "$cohort" --seed "$seed" --gene-codebook-gate 0
        done
    done
}

run_g2() {
    echo ""
    echo "=== G2: Data-driven — gate=30 (21 runs) ==="
    for cohort in "${COHORTS[@]}"; do
        for seed in "${SEEDS[@]}"; do
            run_episode "g2_${cohort,,}_s${seed}" \
                --cohort "$cohort" --seed "$seed"
        done
    done
}

run_g3() {
    echo ""
    echo "=== G3: Mislead — wrong barcodes injected (${#G3_PAIRS[@]} pairs × 3 seeds) ==="
    for pair in "${G3_PAIRS[@]}"; do
        local true_cohort="${pair%%:*}"
        local mislead_cohort="${pair##*:}"
        for seed in "${SEEDS[@]}"; do
            run_episode "g3_${true_cohort,,}_mislead_${mislead_cohort,,}_s${seed}" \
                --cohort "$true_cohort" --mislead-cohort "$mislead_cohort" --seed "$seed"
        done
    done
}

# ── Main ──────────────────────────────────────────────────────────────────────
[[ "$DRY_RUN" == "false" ]] && check_key

echo "Task A benchmark — model: $MODEL | out: $OUT_DIR"
[[ "$DRY_RUN" == "true" ]] && echo "(dry run — no API calls)"

case "$RUN_GROUP" in
    G0) run_g0 ;;
    G1) run_g1 ;;
    G2) run_g2 ;;
    G3) run_g3 ;;
    "")
        run_g0
        run_g1
        run_g2
        run_g3
        ;;
    *)
        echo "Unknown group: $RUN_GROUP. Use G0, G1, G2, or G3." >&2
        exit 1
        ;;
esac

echo ""
echo "Done. Score with:"
echo "  bash scripts/score_all_withMeth.sh $OUT_DIR"
