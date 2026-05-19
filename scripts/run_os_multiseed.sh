#!/usr/bin/env bash
# Run OS cohort benchmark across multiple seeds and retrieval modes.
# Usage: bash scripts/run_os_multiseed.sh
# Requires ANTHROPIC_API_KEY in environment.
#
# NOTE: runs tagged _noCNA_noSNV — full WES somatic calls and CNA/CNV data
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

run_and_score() {
    local mode="$1"
    local seed="$2"
    local extra_args="$3"
    local label="os_${mode}_s${seed}_noCNA_noSNV"

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

    # Find the episode dir that was just created (most recently modified)
    local episode_json
    episode_json=$(find results/cohort/external -name "${label}.json" | sort -t/ -k5 | tail -1)

    if [[ -z "$episode_json" ]]; then
        echo "Warning: could not find ${label}.json to score" >&2
        return
    fi

    echo ""
    echo "Scoring ${episode_json} ..."
    python scripts/score_episode_v2.py "$episode_json" --save
}

# --- G0: explicit retrieval (cohort name + genes revealed) ---
for seed in "${SEEDS[@]}"; do
    run_and_score "g0" "$seed" "--explicit-retrieval"
done

# --- G1: implicit retrieval (genes pre-revealed, no cohort name) ---
for seed in "${SEEDS[@]}"; do
    run_and_score "g1" "$seed" "--gene-codebook-gate 0"
done

# --- G2: data-driven (genes gated at call 30) ---
for seed in "${SEEDS[@]}"; do
    run_and_score "g2" "$seed" ""
done

echo ""
echo "============================================================"
echo "  All runs complete."
echo "  Results in: results/cohort/external/"
echo "============================================================"
