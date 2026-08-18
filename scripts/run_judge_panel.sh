#!/usr/bin/env bash
# Three-replicate CoT judge panel over every arm (G0/G1/G2 honest + G3a/G3b mislead).
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
#   source load_keys.sh <keys.txt>   # exports the key for whichever JUDGE is selected
#   bash scripts/run_judge_panel.sh              # run the panel
#   bash scripts/run_judge_panel.sh --dry-run    # show what WOULD run, no API calls
set -uo pipefail
cd "$(dirname "$0")/.."

JUDGE="${JUDGE:-${BDG_JUDGE_MODEL:-nemotron-3-super}}"
# G3 (mislead) is included deliberately. The headline fooling number comes from the OUTCOME
# scorer (v3scores.cohort_identity_verdict), not from here, so it needs no replicates — but the
# CoT-based G3 claims do: "identity derivation under a false frame" and the relabel-a-real-finding
# mechanism. G3 is also the hardest call the judge makes, since it must decide whether the agent
# DERIVED identity or COMPLIED with an injected false label, so its labels are the least stable
# and most in need of a majority vote. Set ARMS=g0,g1,g2 to skip it.
ARMS="${ARMS:-g0,g1,g2,g3a,g3b}"
# Pass 1 = _cotsummary.json (already complete; deliberately NOT regenerated — the committed
# report, figures and every quoted number derive from it, so a re-run would silently move them).
# Override to run one pass at a time, e.g.  PASSES=_cotsummary_j2.json bash scripts/run_judge_panel.sh
# Pass 1 is EXCLUDED BY DEFAULT only because the pilot already has it. A run that has never been
# judged needs all three, and defaulting to two would hand back a 2-pass "3-pass panel" without
# erroring. So: default to whatever is missing, computed per run set below.
_DEFAULT_PASSES="${PASSES:-}"

# Runs come from runs_config, the same single source of truth every analysis script uses, so
# `export BDG_RUNS=clean` moves the judge panel with everything else. Previously hardcoded to the
# pilot, which meant a clean-run panel would have silently re-judged the CONTAMINATED pilot and
# written its labels — the exact failure runs_config exists to prevent. Override with
# RUNS_OVERRIDE="dir1 dir2".
# PROMPT_SET=detailed|lean judges ONE wave. The waves are generated weeks apart, so a combined
# panel schedules judge calls against a wave that is still being written — spending on a partial
# lane that must be re-judged once the rest lands. Default stays both for backwards compatibility.
if [[ -n "${RUNS_OVERRIDE:-}" ]]; then
  IFS=' ' read -r -a RUNS <<< "$RUNS_OVERRIDE"
else
  while IFS= read -r line; do RUNS+=("$line"); done < <(
    PROMPT_SET="${PROMPT_SET:-}" python -c "
import os, sys
sys.path.insert(0, 'scripts')
import runs_config
sel = os.environ.get('PROMPT_SET') or None
[print(p) for p in runs_config.flat(sel)]"
  )
fi
if [[ ${#RUNS[@]} -eq 0 ]]; then
  echo "No run directories resolved. Set BDG_RUNS (e.g. clean) or RUNS_OVERRIDE." >&2
  exit 1
fi
echo "=== judging runs ==="; printf '  %s\n' "${RUNS[@]}"

# Auto-select passes: keep pass 1 whenever ANY run is missing it. Testing only RUNS[0] was wrong —
# a list whose first entry is a fully-judged lane concluded "pass 1 is done" for every other lane
# too, so a freshly generated run would receive j2 and j3 and never a base pass. Nothing errors:
# cot_compare simply finds two passes where it expects three, and a "3-pass consensus" is silently
# computed from 2. summarize_cot skips episodes that already have the suffix, so including pass 1
# costs nothing on the lanes that have it.
if [[ -z "$_DEFAULT_PASSES" ]]; then
  _missing_p1=()
  for run in "${RUNS[@]}"; do
    compgen -G "$run/*/*_cotsummary.json" > /dev/null || _missing_p1+=("$run")
  done
  if [[ ${#_missing_p1[@]} -eq 0 ]]; then
    _DEFAULT_PASSES="_cotsummary_j2.json _cotsummary_j3.json"
    echo "  pass 1 present in all ${#RUNS[@]} runs — running j2 + j3"
  else
    _DEFAULT_PASSES="_cotsummary.json _cotsummary_j2.json _cotsummary_j3.json"
    echo "  pass 1 missing in ${#_missing_p1[@]}/${#RUNS[@]} runs — running all three passes"
    printf '    no pass 1: %s\n' "${_missing_p1[@]}"
  fi
fi
IFS=', ' read -r -a PASSES <<< "$_DEFAULT_PASSES"

DRY=""; [[ "${1:-}" == "--dry-run" ]] && DRY=1

# Require the key for THIS judge, not always DeepSeek's.
case "$JUDGE" in
  nemotron*|laguna*) KEY_VAR=BIFROST_API_KEY ;;
  deepseek*)         KEY_VAR=DEEPSEEK_API_KEY ;;
  claude*)           KEY_VAR=ANTHROPIC_API_KEY ;;
  *)                 KEY_VAR=OPENAI_API_KEY ;;
esac
if [[ -z "$DRY" && -z "${!KEY_VAR:-}" ]]; then
  echo "$KEY_VAR not set for judge '$JUDGE' — source your keys first." >&2
  exit 1
fi

LOGDIR="results/tcga/_superseded/judge_panel_logs"
mkdir -p "$LOGDIR"

# Identify a run by its last TWO path components. `basename` alone is ambiguous: the detailed and
# lean waves use the SAME model stems, so results/tcga/clean/gemini25pro and
# results/tcga/clean_lean/gemini25pro both render as "gemini25pro". In the preflight table that is
# merely confusing; in the log name below it is destructive — both lanes tee to one file and the
# second silently overwrites the first, so the evidence for one of them is simply gone.
run_label() { local p="${1%/}"; printf '%s/%s' "$(basename "$(dirname "$p")")" "$(basename "$p")"; }

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
    printf "  %-14s %-46s %3s\n" "${sfx%.json}" "$(run_label "$run")" "$n"
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
    tag="$(run_label "$run" | tr '/' '_')${sfx%.json}"
    echo ">>> $tag"
    # python -u: without it Python block-buffers stdout when piped, so per-episode progress sits
    # in an 8K buffer and the log stays EMPTY for ~40 min. Stream to both the log and the
    # terminal (no `tail`, which only emits after the whole run dir finishes).
    # PIPESTATUS, not $?, so a python failure is not masked by tee's exit code.
    python -u scripts/summarize_cot.py "$run" \
        --arms "$ARMS" --model "$JUDGE" --out-suffix "$sfx" --save \
        2>&1 | tee "$LOGDIR/${tag}.log"
    if [[ "${PIPESTATUS[0]}" -ne 0 ]]; then
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
