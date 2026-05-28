#!/usr/bin/env bash
# Run OS cohort benchmark across multiple seeds and retrieval modes.
# Usage: bash scripts/run_os_multiseed.sh
# Requires ANTHROPIC_API_KEY in environment.
#
# NOTE: runs tagged _withMeth_noCNA — full WES somatic calls and CNA/CNV data
# are pending controlled-access approval (GSA HRA003260). Only mRNA expression
# + 41-gene sparse mutation panel available. Re-run without tag once data arrives.

set -euo pipefail

SEEDS=(0 1 7)   # seed 42 already done
COHORT="OS"
MODEL="claude-sonnet-4-6"

if [[ -z "${ANTHROPIC_API_KEY:-}" ]]; then
    echo "Error: ANTHROPIC_API_KEY is not set." >&2
    exit 1
fi

run_episode() {
    local mode="$1"
    local seed="$2"
    local extra_args="$3"
    local label="os_${mode}_s${seed}_withMeth_noCNA"

    echo ""
    echo "============================================================"
    echo "  ${mode} | seed=${seed}"
    echo "============================================================"

    python scripts/run_episode.py \
        --cohort "$COHORT" \
        --seed "$seed" \
        --model "$MODEL" \
        --quiet \
        $extra_args \
        --save-log "${label}.json"
}

# --- G0: explicit retrieval (cohort name + genes revealed) ---
for seed in "${SEEDS[@]}"; do
    run_episode "g0" "$seed" "--explicit-retrieval"
done

# --- G1: implicit retrieval (genes pre-revealed, no cohort name) ---
for seed in "${SEEDS[@]}"; do
    run_episode "g1" "$seed" "--gene-codebook-gate 0"
done

# --- G2: data-driven (genes gated at call 25) ---
for seed in "${SEEDS[@]}"; do
    run_episode "g2" "$seed" ""
done

echo ""
echo "============================================================"
echo "  All runs complete."
echo "  Results in: results/cohort/external/"
echo "============================================================"
