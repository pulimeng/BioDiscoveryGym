#!/usr/bin/env bash
# Three-replicate CoT judge panel over the honest arms (G0/G1/G2).
#
# WHY replicates rather than three different families: identity_derivation is one categorical
# call, and we do not know its run-to-run stability. Three independent passes of the SAME neutral
# judge separate "the label is noisy" from "the effect is real" — a majority vote denoises the
# per-episode label, and the spread across passes gives an honest uncertainty band on every delta.
# This measures the judge's SELF-CONSISTENCY ceiling. It says nothing about cross-family bias;
# that needs a --model override to a different family and a separate suffix.
#
# Replicates are meaningful only because the judge call uses the provider's default temperature
# (call_judge passes no temperature/seed). j1-vs-j2 already disagree on ~40% of G2 episodes, so
# the draws are genuinely independent rather than a deterministic re-run.
#
# Resume-safe: summarize_cot.py skips any episode that already has the target suffix, so
# re-running this script only fills gaps. It never touches _cotsummary.json (pass 1).
#
# Usage:
#   source ~/OneDrive/keys.txt   # or however DEEPSEEK_API_KEY gets into the env
#   bash scripts/run_judge_panel.sh              # run the panel
#   bash scripts/run_judge_panel.sh --dry-run    # show what WOULD run, no API calls
set -uo pipefail
cd "$(dirname "$0")/.."

JUDGE="${JUDGE:-deepseek-v4-pro}"
ARMS="${ARMS:-g0,g1,g2}"
# Pass 1 = _cotsummary.json (already complete; deliberately NOT regenerated — the committed
# report, figures and every quoted number derive from it, so a re-run would silently move them).
PASSES=("_cotsummary_j2.json" "_cotsummary_j3.json")
RUNS=(
  results/tcga/ladder/sonnet5_20260713
  results/tcga/ladder/gpt55_20260707
  results/tcga/ladder/gemini35flash_20260716
  results/tcga/lean/sonnet5_20260722
  results/tcga/lean/gpt55_20260721
  results/tcga/lean/gemini35flash_20260722
)

DRY=""; [[ "${1:-}" == "--dry-run" ]] && DRY=1

if [[ -z "$DRY" && -z "${DEEPSEEK_API_KEY:-}" ]]; then
  echo "DEEPSEEK_API_KEY not set — source your keys first (see feedback_never_commit_keys)." >&2
  exit 1
fi

LOGDIR="results/tcga/_judge_panel_logs"
mkdir -p "$LOGDIR"

# ---- pre-flight: how much work is actually outstanding? -----------------------------------
todo_total=0
echo "=== outstanding episodes (arms: $ARMS) ==="
for sfx in "${PASSES[@]}"; do
  for run in "${RUNS[@]}"; do
    n=$(python - "$run" "$sfx" "$ARMS" <<'PY'
import glob, os, sys
run, sfx, arms = sys.argv[1], sys.argv[2], set(sys.argv[3].split(','))
n = 0
for p in glob.glob(f"{run}/*/g[0-3]*_s*.json"):
    b = os.path.basename(p)
    if b[:-5] != os.path.basename(os.path.dirname(p)):        # skip derived artifacts
        continue
    if b.split('_')[0] not in arms:
        continue
    if not os.path.exists(p[:-5] + sfx):
        n += 1
print(n)
PY
)
    printf "  %-14s %-46s %3s\n" "${sfx%.json}" "$(basename "$run")" "$n"
    todo_total=$((todo_total + n))
  done
done
echo "  TOTAL outstanding: $todo_total episodes"
if [[ -n "$DRY" ]]; then echo; echo "(dry run — nothing executed)"; exit 0; fi
if [[ "$todo_total" -eq 0 ]]; then echo; echo "Panel already complete — nothing to do."; exit 0; fi

# ---- run ----------------------------------------------------------------------------------
echo
fail=0
for sfx in "${PASSES[@]}"; do
  for run in "${RUNS[@]}"; do
    tag="$(basename "$run")${sfx%.json}"
    echo ">>> $tag"
    if ! python scripts/summarize_cot.py "$run" \
        --arms "$ARMS" --model "$JUDGE" --out-suffix "$sfx" --save \
        2>&1 | tee "$LOGDIR/${tag}.log" | tail -3; then
      echo "  !! FAILED: $tag (see $LOGDIR/${tag}.log)" >&2
      fail=$((fail + 1))
    fi
  done
done

echo
echo "=== panel done (${fail} run-level failures) ==="
echo "Per-episode judge failures do NOT abort the run — verify coverage before analysing:"
echo "  python scripts/cot_compare.py --panel _cotsummary.json,_cotsummary_j2.json,_cotsummary_j3.json --arms $ARMS"
[[ "$fail" -gt 0 ]] && exit 1 || exit 0
