#!/usr/bin/env bash
# Run OS cohort benchmark across multiple seeds and retrieval modes.
# Usage: bash scripts/run_os_multiseed.sh
# Requires ANTHROPIC_API_KEY in environment.
#
# NOTE: runs tagged _withMeth_noCNA — full WES somatic calls and CNA/CNV data
# are pending controlled-access approval (GSA HRA003260). Only mRNA expression
# + 41-gene sparse mutation panel available. Re-run without tag once data arrives.

set -euo pipefail

G0_SEEDS=(0 1 7)
G1_SEEDS=(0 1 7 42 123)
G2_SEEDS=(0 1 7 42 123)
COHORT="OS"
MODEL="claude-sonnet-4-6"
RUN_TAG="run5_threePrompt_clinAnon"

if [[ -z "${ANTHROPIC_API_KEY:-}" ]]; then
    echo "Error: ANTHROPIC_API_KEY is not set." >&2
    exit 1
fi

run_episode() {
    local mode="$1"
    local seed="$2"
    local extra_args="$3"
    local label="os_${mode}_s${seed}_${RUN_TAG}"

    echo ""
    echo "============================================================"
    echo "  ${mode} | seed=${seed} | ${RUN_TAG}"
    echo "============================================================"

    python scripts/run_episode.py \
        --cohort "$COHORT" \
        --seed "$seed" \
        --model "$MODEL" \
        --quiet \
        $extra_args \
        --save-log "${label}.json"
}

# --- G0: explicit retrieval (cohort name + both codebooks pre-revealed) — 3 runs ---
for seed in "${G0_SEEDS[@]}"; do
    run_episode "g0" "$seed" "--explicit-retrieval"
done

# --- G1: implicit retrieval (gene codebook pre-revealed, cohort hidden) — 5 runs ---
for seed in "${G1_SEEDS[@]}"; do
    run_episode "g1" "$seed" "--gene-codebook-gate 0"
done

# --- G2: data-driven (gene codebook gated at call 25, cohort hidden) — 5 runs ---
for seed in "${G2_SEEDS[@]}"; do
    run_episode "g2" "$seed" ""
done

echo ""
echo "============================================================"
echo "  All runs complete."
echo "  Results in: results/cohort/external/"
echo "============================================================"
