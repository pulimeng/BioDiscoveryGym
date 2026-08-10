#!/usr/bin/env bash
# score_run.sh — score a run dir on BOTH tracks. Decoupled from run_tcga.sh so scoring can be
# re-run / changed without re-running episodes.
#
#   bash scripts/score_run.sh results/tcga/pilot/ladder/gpt55_20260707
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
    # BDG_JUDGE_MODEL keeps all three tracks on ONE judge. Set it and the outcome, support and
    # CoT judges move together; forget it and they diverge silently, which is the failure a
    # multi-judge robustness check cannot survive.
    _J="${BDG_JUDGE_MODEL:-nemotron-3-super}"
    echo "=== outcome track  ->  _v3scores.json  (judge: ${_J}) ==="
    bash scripts/score_all_tcga.sh "$DIR" $RESCORE ${BDG_JUDGE_MODEL:+--llm-model "$BDG_JUDGE_MODEL"}
fi

if [[ $DO_SUPPORT -eq 1 ]]; then
    echo ""
    echo "=== support track (strategy x support)  ->  _supportscores.json (judge: ${BDG_JUDGE_MODEL:-nemotron-3-super}) ==="
    # An explicit --model in SUPPORT_ARGS still wins; BDG_JUDGE_MODEL is only the default.
    if [[ -n "${BDG_JUDGE_MODEL:-}" ]] && ! printf '%s\n' ${SUPPORT_ARGS[@]+"${SUPPORT_ARGS[@]}"} | grep -qx -- '--model'; then
        SUPPORT_ARGS+=(--model "$BDG_JUDGE_MODEL")
    fi
    python scripts/score_support.py "$DIR" --save ${SUPPORT_ARGS[@]+"${SUPPORT_ARGS[@]}"}
fi
