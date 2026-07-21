#!/usr/bin/env bash
# smoke_lean.sh — LEAN-PROMPT smoke across all arms (G0/G1/G2/G3a/G3b) for every model.
#
# Runs `run_tcga.sh --smoke-test` (1 cohort × 1 seed × all five arms) with the LEAN prompt
# (prompts/ablation/tcga_lean.txt) for each model, so you can confirm every model still submits
# clean discoveries on all arms under the lean prompt BEFORE funding the full lean ablation.
# This is the lean-prompt counterpart of smoke_ladder.sh.
#
# The lean ablation tests whether the staged/detailed prompt manufactures the grounding
# (reviewer confound). Paired A/B vs the detailed runs — same seeds/cohort/budget, prompt only.
#
# Opus is EXCLUDED by default (cost). Add it back via SMOKE_MODELS if you want it.
# Skips any provider whose API key isn't set.
#
# Setup:  source load_keys.sh "<keys.txt>"     # exports ANTHROPIC / OPENAI / GEMINI keys
# Usage:  bash scripts/smoke_lean.sh
#         SMOKE_MODELS="claude-sonnet-5 gpt-5.5" bash scripts/smoke_lean.sh
#         SMOKE_CALLS=40 bash scripts/smoke_lean.sh            # smaller per-episode budget
#         bash scripts/smoke_lean.sh --dry-run                 # print the run_tcga commands, run nothing
#
# Any extra args (e.g. --dry-run, --group G2) pass through to run_tcga.sh.
set -o pipefail   # not -u: macOS bash 3.2 errors on empty-array expansion under -u

PROMPT_FILE="${LEAN_PROMPT:-prompts/ablation/tcga_lean.txt}"
CALLS="${SMOKE_CALLS:-100}"
# Default set EXCLUDES opus (cost). Gemini = 3.5-flash (Pro 503s under load — see MODEL_LADDER §2).
read -r -a MODELS <<< "${SMOKE_MODELS:-claude-sonnet-5 gpt-5.5 gemini-3.5-flash}"
PASSTHRU=("$@")   # forwarded to run_tcga.sh (e.g. --dry-run, --group)

if [[ ! -f "$PROMPT_FILE" ]]; then
    echo "smoke_lean: lean prompt '$PROMPT_FILE' not found" >&2; exit 1
fi

key_ok() {  # $1=model -> 0 if the required API key is present
    case "$1" in
        claude*)        [[ -n "${ANTHROPIC_API_KEY:-}" ]] ;;
        gpt*|o[0-9]*)   [[ -n "${OPENAI_API_KEY:-}" ]] ;;
        gemini*)        [[ -n "${GEMINI_API_KEY:-}" || -n "${GOOGLE_API_KEY:-}" ]] ;;
        *) return 1 ;;
    esac
}
key_name() {
    case "$1" in
        claude*) echo ANTHROPIC_API_KEY ;; gpt*|o[0-9]*) echo OPENAI_API_KEY ;;
        gemini*) echo "GEMINI_API_KEY/GOOGLE_API_KEY" ;; *) echo "?" ;;
    esac
}

declare -a SUMMARY
for m in "${MODELS[@]}"; do
    tag="_ablation/lean_smoke/${m//[^a-zA-Z0-9]/_}"
    if ! key_ok "$m"; then
        echo ">>> SKIP $m — $(key_name "$m") not set"
        SUMMARY+=("$m|SKIP (no key)")
        continue
    fi
    echo ""
    echo "############################################################"
    echo ">>> LEAN SMOKE  $m   (all arms, --smoke-test)  ->  results/tcga/$tag"
    echo "############################################################"
    # --smoke-test = 1 cohort × 1 seed × G0/G1/G2/G3a/G3b. Per-episode logs land in <tag>/_logs/.
    bash scripts/run_tcga.sh --smoke-test --model "$m" \
        --prompt-file "$PROMPT_FILE" --max-calls "$CALLS" \
        --tag "$tag" "${PASSTHRU[@]}"
    rc=$?
    if [[ $rc -eq 0 ]]; then
        SUMMARY+=("$m|done (rc=0)  results/tcga/$tag")
    else
        SUMMARY+=("$m|FAILED (rc=$rc) — see results/tcga/$tag/_logs/")
    fi
done

echo ""
echo "============================================================"
echo "  LEAN SMOKE SUMMARY  (prompt: $PROMPT_FILE)"
echo "============================================================"
for s in "${SUMMARY[@]}"; do
    printf '  %-22s %s\n' "${s%%|*}" "${s#*|}"
done
echo ""
echo "  Next: eyeball each model submitted on every arm, then run the full lean ablation."
echo "  Score with:  bash scripts/score_run.sh results/tcga/_ablation/lean_smoke/<model>"
