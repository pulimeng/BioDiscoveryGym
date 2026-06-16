#!/usr/bin/env bash
# Score all TCGA episode JSONs in a results folder (faithfulness rubric, includes LLM judge).
# Usage: ANTHROPIC_API_KEY=sk-... bash scripts/score_all_tcga.sh <results_folder>
# Example: ANTHROPIC_API_KEY=sk-... bash scripts/score_all_tcga.sh results/tcga/run4
#
# Resume-safe: skips episodes that already have a *_v3scores.json (re-running after a
# partial batch won't re-bill the LLM judge on already-scored episodes). Pass
# --rescore to force re-scoring everything.
#
# Resilient: a single episode's failure (e.g. the LLM judge hitting a transient
# connection error) is collected and reported at the end rather than aborting the whole
# batch. Exit status is non-zero if any episode failed.

# NOTE: deliberately NOT 'set -e' — one failed episode must not abort the rest.
set -uo pipefail

RESCORE=0
RESULTS_DIR=""
for arg in "$@"; do
    case "$arg" in
        --rescore) RESCORE=1 ;;
        *)         RESULTS_DIR="$arg" ;;
    esac
done

if [[ -z "$RESULTS_DIR" ]]; then
    echo "Usage: ANTHROPIC_API_KEY=sk-... bash scripts/score_all_tcga.sh <results_folder> [--rescore]" >&2
    exit 1
fi

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

FAILED=()
SKIPPED=0
SCORED=0
for ep in "${EPISODES[@]}"; do
    # Skip agent-written artifacts that aren't episodes (e.g. subtype_labels.json,
    # arbitrary label maps the agent saves via run_code). Real episode JSONs always
    # carry a top-level "messages" key; artifacts don't. More robust than denylisting
    # every possible filename.
    if ! python -c "import json,sys; d=json.load(open(sys.argv[1])); sys.exit(0 if isinstance(d, dict) and 'messages' in d else 1)" "$ep" 2>/dev/null; then
        echo "=== SKIP (not an episode): $(basename "$ep") ==="
        SKIPPED=$((SKIPPED + 1))
        continue
    fi
    scorefile="${ep%.json}_v3scores.json"
    if [[ $RESCORE -eq 0 && -f "$scorefile" ]]; then
        echo "=== SKIP (already scored): $(basename "$ep") ==="
        SKIPPED=$((SKIPPED + 1))
        continue
    fi
    echo "=== $(basename "$ep") ==="
    if python scripts/score_tcga_episode.py "$ep" --save; then
        SCORED=$((SCORED + 1))
    else
        rc=$?
        echo "  !! scoring FAILED for $(basename "$ep") (exit $rc)" >&2
        FAILED+=("$(basename "$ep")")
    fi
    echo ""
done

echo "============================================================"
echo "  Scoring summary: ${SCORED} scored, ${SKIPPED} skipped, ${#FAILED[@]} failed"
if [[ ${#FAILED[@]} -gt 0 ]]; then
    printf '    FAILED: %s\n' "${FAILED[@]}" >&2
    echo "  Re-run the same command to retry the failed episodes (succeeded ones are skipped)."
    exit 1
fi
echo "  All done."
