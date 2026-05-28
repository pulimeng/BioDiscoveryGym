#!/usr/bin/env bash
# Score all episode JSONs in a results folder with v3 scorer (includes LLM judge).
# Usage: ANTHROPIC_API_KEY=sk-... bash scripts/score_all_withMeth.sh <results_folder>
# Example: ANTHROPIC_API_KEY=sk-... bash scripts/score_all_withMeth.sh results/cohort/external/run4_clinAnon_obsTrack

set -e

if [[ -z "${1:-}" ]]; then
    echo "Usage: ANTHROPIC_API_KEY=sk-... bash scripts/score_all_withMeth.sh <results_folder>" >&2
    exit 1
fi

RESULTS_DIR="$1"

if [[ ! -d "$RESULTS_DIR" ]]; then
    echo "Error: directory not found: $RESULTS_DIR" >&2
    exit 1
fi

EPISODES=()
while IFS= read -r line; do EPISODES+=("$line"); done < <(find "$RESULTS_DIR" -name "*.json" \
    -not -name "*scores*" \
    -not -name "*trace*" \
    -not -name "grouping.json" \
    -not -name "codebook.json" \
    -not -name "gene_map.json" \
    -not -name "clinical_codebook.json" \
    -not -name "sample_codebook.json" \
    | sort)

if [[ ${#EPISODES[@]} -eq 0 ]]; then
    echo "No episode JSONs found in $RESULTS_DIR" >&2
    exit 1
fi

echo "Found ${#EPISODES[@]} episode(s) in $RESULTS_DIR"
echo ""

for ep in "${EPISODES[@]}"; do
    echo "=== $(basename $ep) ==="
    python scripts/score_episode_v3.py "$ep" --save
    echo ""
done

echo "All done."
