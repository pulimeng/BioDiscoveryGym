#!/usr/bin/env bash
# Run the 3-family judge panel over a run set: one pass per judge, all three LLM artifacts.
#
# Replaces the 3-passes-of-one-model panel. See scripts/judges_config.py for the design note.
#
#   scripts/run_judge_panel_v2.sh [tag ...]      default: every tag in judges_config.PANEL
#
# Env:  BDG_RUNS=clean (required)   BDG_QWEN_MODEL=<id> (once the AIE cert is installed)
#
# Resume-safe: every scorer skips episodes that already have the target suffix, so an
# interrupted pass is restarted by re-running this. Nothing here overwrites another judge's
# output — each writes to its own <artifact>_<tag>.json.
set -uo pipefail
cd "$(dirname "$0")/.."
PY="${BDG_PYTHON:-$HOME/miniconda3/envs/biodiscoverygym/bin/python}"
: "${BDG_RUNS:?set BDG_RUNS (e.g. export BDG_RUNS=clean)}"

LOGDIR="results/tcga/_judge_panel_v2_logs"; mkdir -p "$LOGDIR"
if [ $# -gt 0 ]; then TAGS=("$@"); else
  TAGS=($($PY -c "
import sys; sys.path.insert(0,'scripts'); import judges_config as J; print(' '.join(J.tags()))"))
fi

# Resolve the run directories from the SAME source of truth the analysis uses, so the panel
# can never judge a different set of episodes than the one that gets analysed.
#
# NOT mapfile: macOS ships bash 3.2, where mapfile does not exist. Under `set -uo pipefail`
# (no -e) it fails silently and leaves DIRS EMPTY, so every loop below iterates zero times and
# the script exits 0 having judged nothing — a non-event rendering as a clean run, which is the
# exact failure class this repo keeps catching. while-read works on 3.2, and the guard turns an
# empty resolution into a loud exit instead of a quiet success.
DIRS=()
while IFS= read -r _d; do [ -n "$_d" ] && DIRS+=("$_d"); done < <($PY -c "
import sys; sys.path.insert(0,'scripts'); import runs_config
print('\n'.join(runs_config.flat()))")
if [ ${#DIRS[@]} -eq 0 ]; then
  echo "ERROR: runs_config.flat() resolved no run directories for BDG_RUNS='${BDG_RUNS}'." >&2
  echo "       Refusing to run a panel over nothing." >&2
  exit 1
fi
echo "run dirs (${#DIRS[@]}):"; printf '  %s\n' "${DIRS[@]}"

for tag in "${TAGS[@]}"; do
  MODEL=$($PY -c "
import sys; sys.path.insert(0,'scripts'); import judges_config as J; print(J.model_for('$tag'))")
  echo; echo "################ JUDGE: $tag  ($MODEL) ################"
  for d in "${DIRS[@]}"; do
    echo "=== [$tag] CoT      $d ==="
    $PY scripts/summarize_cot.py "$d" --model "$MODEL" --save \
        --out-suffix "_cotsummary_${tag}.json"      2>&1 | tail -2 | tee -a "$LOGDIR/${tag}_cot.log"
    echo "=== [$tag] support  $d ==="
    $PY scripts/score_support.py "$d" --model "$MODEL" --save \
        --out-suffix "_supportscores_${tag}.json"   2>&1 | tail -2 | tee -a "$LOGDIR/${tag}_support.log"
    echo "=== [$tag] outcome  $d ==="
    for ep in "$d"/*/g[0-3]*_s*.json; do
      case "$ep" in *scores*|*trace*|*summary*|*codebook*|*gene_map*|*grouping*) continue;; esac
      out="${ep%.json}_v3scores_${tag}.json"; [ -f "$out" ] && continue
      $PY scripts/score_tcga_episode.py "$ep" --save --llm-model "$MODEL" \
          --out-suffix "_v3scores_${tag}.json" >/dev/null 2>>"$LOGDIR/${tag}_outcome.log" \
          || echo "  !! outcome failed: $ep" | tee -a "$LOGDIR/${tag}_outcome.log"
    done
    echo "  outcome done: $(ls "$d"/*/*_v3scores_${tag}.json 2>/dev/null | wc -l | xargs)"
  done
done

echo; echo "################ PANEL COVERAGE ################"
$PY - <<'PYEOF'
import sys, glob, os
sys.path.insert(0,'scripts'); import runs_config, judges_config as J
for kind in ('cot','support','outcome'):
    row=[]
    for tag in [None]+J.tags():
        n=sum(len(glob.glob(os.path.join(d,'*','*'+J.suffix(kind,tag)))) for d in runs_config.flat())
        row.append(f"{tag or J.LEGACY_TAG}={n}")
    print(f"  {kind:8} " + "  ".join(row))
PYEOF
