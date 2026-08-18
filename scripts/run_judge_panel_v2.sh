#!/usr/bin/env bash
# Run the 3-family judge panel over a run set: one pass per judge, all three LLM artifacts.
#
# See scripts/judges_config.py for the design note (why one pass x three families, not three
# passes x one model).
#
#   scripts/run_judge_panel_v2.sh [tag ...]     default: every tag in judges_config.PANEL
#
# Env:
#   BDG_RUNS=clean        (required) which run set, via runs_config
#   BDG_JOBS=6            parallel workers per (judge, artifact) stage; default 6
#   BDG_QWEN_MODEL=<id>   override the Qwen model id
#
# PARALLELISM. Work is sharded per EPISODE, not per lane: lanes differ ~3x in how long they
# take, so a lane-parallel run spends its tail single-threaded waiting on the slowest one.
# Each worker handles a disjoint slice of the episode list, so all workers finish together.
#
# Judges run SEQUENTIALLY even so. nemotron and laguna share one bifrost gateway, and the
# earlier abandoned run showed that lane is capacity-limited (Gemini 3.1 Pro returned 503 on a
# 1-token preflight); stacking three judges' concurrency onto it invites the same 503/hang that
# cost 60 episodes before. Concurrency within one judge is the tunable knob.
#
# Resume-safe: every scorer skips episodes that already have the target suffix, so re-running
# after an interruption continues. Nothing overwrites another judge's output.
set -uo pipefail
cd "$(dirname "$0")/.."
PY="${BDG_PYTHON:-$HOME/miniconda3/envs/biodiscoverygym/bin/python}"
JOBS="${BDG_JOBS:-6}"
: "${BDG_RUNS:?set BDG_RUNS (e.g. export BDG_RUNS=clean)}"

LOGDIR="results/tcga/_judge_panel_v2_logs"; mkdir -p "$LOGDIR"
if [ $# -gt 0 ]; then TAGS=("$@"); else
  TAGS=($($PY -c "
import sys; sys.path.insert(0,'scripts'); import judges_config as J; print(' '.join(J.tags()))"))
fi

# Resolve run dirs from the SAME source of truth the analysis uses, so the panel can never
# judge a different set of episodes than the one that gets analysed.
#
# NOT mapfile: macOS ships bash 3.2, where mapfile does not exist, fails silently under
# `set -uo pipefail`, and leaves the array EMPTY — every loop iterating zero times and the
# script exiting 0 having judged nothing.
DIRS=()
while IFS= read -r _d; do [ -n "$_d" ] && DIRS+=("$_d"); done < <($PY -c "
import sys; sys.path.insert(0,'scripts'); import runs_config
print('\n'.join(runs_config.flat()))")
if [ ${#DIRS[@]} -eq 0 ]; then
  echo "ERROR: runs_config.flat() resolved no run directories for BDG_RUNS='${BDG_RUNS}'." >&2
  echo "       Refusing to run a panel over nothing." >&2; exit 1
fi
echo "run dirs (${#DIRS[@]}):"; printf '  %s\n' "${DIRS[@]}"
echo "workers per stage: $JOBS   judges: ${TAGS[*]}"

# Every episode json across all lanes, one per line (excludes derived artifacts).
EPISODES=$($PY - <<'PYEOF'
import sys, glob, os
sys.path.insert(0,'scripts'); import runs_config
bad=("scores","trace","summary","codebook","gene_map","grouping")
for d in runs_config.flat():
    for f in sorted(glob.glob(os.path.join(d,'*','g[0-3]*_s*.json'))):
        if all(x not in os.path.basename(f) for x in bad) \
           and os.path.basename(os.path.dirname(f)) == os.path.basename(f)[:-5]:
            print(f)
PYEOF
)
N_EP=$(printf '%s\n' "$EPISODES" | grep -c . )
echo "episodes: $N_EP"
[ "$N_EP" -eq 0 ] && { echo "ERROR: no episodes resolved. Refusing to run." >&2; exit 1; }

for tag in "${TAGS[@]}"; do
  MODEL=$($PY -c "
import sys; sys.path.insert(0,'scripts'); import judges_config as J; print(J.model_for('$tag'))")
  echo; echo "################ JUDGE: $tag  ($MODEL) ################"

  # ---- per-episode artifacts (outcome), sharded across workers -------------------------
  for art in outcome; do
    echo "=== [$tag] $art  ($JOBS workers) ==="
    for w in $(seq 0 $((JOBS-1))); do
      (
        i=0
        printf '%s\n' "$EPISODES" | while IFS= read -r ep; do
          [ -z "$ep" ] && continue
          if [ $((i % JOBS)) -eq "$w" ]; then
            out="$(dirname "$ep")/scoring/${tag}/v3scores.json"
            [ -f "$out" ] || $PY scripts/score_tcga_episode.py "$ep" --save \
                --llm-model "$MODEL" --judge-tag "$tag" \
                >/dev/null 2>>"$LOGDIR/${tag}_outcome_w${w}.log" \
                || echo "  !! $ep" >>"$LOGDIR/${tag}_outcome_w${w}.log"
          fi
          i=$((i+1))
        done
      ) &
    done
    wait
    echo "  done: $(find "${DIRS[@]}" -path "*/scoring/${tag}/v3scores.json" | wc -l | xargs)/$N_EP"
  done

  # ---- per-lane artifacts (CoT, support): lanes in parallel, each scorer walks its lane --
  for art in cot support; do
    case "$art" in
      cot)     SCRIPT=scripts/summarize_cot.py;  SUF="scoring/${tag}/cotsummary.json" ;;
      support) SCRIPT=scripts/score_support.py;  SUF="scoring/${tag}/supportscores.json" ;;
    esac
    echo "=== [$tag] $art  (${#DIRS[@]} lanes in parallel) ==="
    for d in "${DIRS[@]}"; do
      $PY "$SCRIPT" "$d" --model "$MODEL" --save --judge-tag "$tag" \
          >>"$LOGDIR/${tag}_${art}_$(basename "$(dirname "$d")")_$(basename "$d").log" 2>&1 &
    done
    wait
    echo "  done: $(find "${DIRS[@]}" -path "*/${SUF}" | wc -l | xargs)/$N_EP"
  done
done

echo; echo "################ PANEL COVERAGE ################"
$PY scripts/panel_status.py
