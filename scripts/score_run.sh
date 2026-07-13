#!/usr/bin/env bash
# score_run.sh — score a run dir on BOTH tracks. Decoupled from run_tcga.sh so scoring can be
# re-run / changed without re-running episodes.
#
#   bash scripts/score_run.sh results/tcga/ladder/gpt55_20260707
#   bash scripts/score_run.sh <dir> --rescore                 # overwrite existing support scores
#   bash scripts/score_run.sh <dir> --model claude-sonnet-5   # different support judge (robustness)
#   bash scripts/score_run.sh <dir> --outcome-only            # skip the support track
#   bash scripts/score_run.sh <dir> --support-only            # skip the outcome track
#
# Any other flags after <dir> pass through to score_support.py (--rescore, --model, --arms, ...).
set -uo pipefail

DIR="${1:?usage: score_run.sh <run_dir> [--outcome-only|--support-only] [score_support args...]}"
shift || true

DO_OUTCOME=1; DO_SUPPORT=1; RESCORE=""
SUPPORT_ARGS=()
for a in "$@"; do
    case "$a" in
        --outcome-only) DO_SUPPORT=0 ;;
        --support-only) DO_OUTCOME=0 ;;
        --rescore)      RESCORE="--rescore"; SUPPORT_ARGS+=("$a") ;;   # both tracks
        *)              SUPPORT_ARGS+=("$a") ;;
    esac
done

if [[ $DO_OUTCOME -eq 1 ]]; then
    echo "=== outcome track  ->  _v3scores.json  (judge: DeepSeek) ==="
    bash scripts/score_all_tcga.sh "$DIR" $RESCORE
fi

if [[ $DO_SUPPORT -eq 1 ]]; then
    echo ""
    echo "=== support track (strategy x support)  ->  _supportscores.json ==="
    python scripts/score_support.py "$DIR" --save ${SUPPORT_ARGS[@]+"${SUPPORT_ARGS[@]}"}
fi
