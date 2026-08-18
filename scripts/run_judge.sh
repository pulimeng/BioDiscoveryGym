#!/usr/bin/env bash
# Run ONE judge over an entire run set. Sequential by design — one API call at a time.
#
#   scripts/run_judge.sh nemotron
#   scripts/run_judge.sh laguna --wave detailed     # only results/tcga/clean
#   scripts/run_judge.sh qwen   --wave lean         # only results/tcga/clean_lean
#
# NOTE ON SCOPE. BDG_RUNS=clean resolves to BOTH waves — results/tcga/clean (the "detailed"
# wave) AND results/tcga/clean_lean (the "lean" wave), 6 lanes and 570 episodes. To finish one
# wave before starting the other, pass --wave. The directory is named `clean`/`clean_lean` but
# the wave is named `detailed`/`lean`; --wave takes the wave name.
#
# Run the three in three terminals. That IS the parallelism: three processes, one per judge,
# each a single stream of work. The previous driver sharded episodes across N background
# workers per stage; it was faster on paper and had far more ways to go wrong — partial shards
# on interrupt, interleaved logs, a silent empty work-list, and 6-18 concurrent connections
# onto a gateway that is known to 503 under load (Gemini 3.1 Pro returned 503 there on a
# 1-token preflight; Gemini 3.5 Flash was abandoned at 60/95). Three streams is a load the
# gateway is known to survive, and a crashed terminal loses one judge, not a shard of three.
#
# Resume-safe: each scorer skips episodes that already have its artifact, so re-running after
# an interrupt continues where it stopped. Nothing here can overwrite another judge's output —
# every write goes to <episode>/scoring/<tag>/.
#
# Env:  BDG_RUNS=clean   (required)
set -uo pipefail
cd "$(dirname "$0")/.."
PY="${BDG_PYTHON:-$HOME/miniconda3/envs/biodiscoverygym/bin/python}"
: "${BDG_RUNS:?set BDG_RUNS (e.g. export BDG_RUNS=clean)}"

TAG="${1:-}"; shift || true
WAVE=""
while [ $# -gt 0 ]; do
  case "$1" in
    --wave) WAVE="${2:-}"; shift 2 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done
if [ -n "$WAVE" ] && [ "$WAVE" != "detailed" ] && [ "$WAVE" != "lean" ]; then
  echo "--wave must be 'detailed' or 'lean' (got '$WAVE')" >&2; exit 2
fi
if [ -z "$TAG" ]; then
  echo "usage: $0 <judge-tag>    one of: $($PY -c "
import sys; sys.path.insert(0,'scripts'); import judges_config as J; print(' '.join(J.tags()))")" >&2
  echo "  Run one judge per terminal. There is deliberately no 'run everything' mode." >&2
  echo "  Optional: --wave detailed|lean  (default: both waves, 6 lanes)" >&2
  exit 2
fi
MODEL=$($PY -c "
import sys; sys.path.insert(0,'scripts'); import judges_config as J; print(J.model_for('$TAG'))") || exit 2

# Fail in seconds on a bad key or model id, not 95 episodes in.
$PY - "$MODEL" <<'PYEOF' || exit 2
import os, sys
sys.path.insert(0, '.'); sys.path.insert(0, 'scripts')
from biodiscoverygym.scoring.judge import openai_client_for, required_key_env
model = sys.argv[1]
key = required_key_env(model)
if not os.environ.get(key):
    sys.exit(f"  PREFLIGHT FAIL: {key} not set for {model}. source load_keys.sh first.")
try:
    r = openai_client_for(model, timeout=60.0, max_retries=1).chat.completions.create(
        model=model, max_tokens=5, messages=[{"role": "user", "content": "ok"}])
    print(f"  preflight OK: {model} -> {r.choices[0].message.content!r}")
except Exception as e:
    sys.exit(f"  PREFLIGHT FAIL: {type(e).__name__}: {str(e)[:200]}")
PYEOF

LOG="results/tcga/_judge_logs/${TAG}"; mkdir -p "$LOG"
DIRS=()
while IFS= read -r d; do [ -n "$d" ] && DIRS+=("$d"); done < <($PY -c "
import sys; sys.path.insert(0,'scripts'); import runs_config
w = '$WAVE' or None
print('\n'.join(runs_config.flat(w)))")
if [ ${#DIRS[@]} -eq 0 ]; then
  echo "ERROR: no run directories for BDG_RUNS='${BDG_RUNS}'. Refusing." >&2; exit 1
fi

echo "judge: $TAG ($MODEL)   wave: ${WAVE:-both}   lanes: ${#DIRS[@]}   logs: $LOG"
START=$(date +%s)

for d in "${DIRS[@]}"; do
  lane=$(basename "$(dirname "$d")")_$(basename "$d")
  echo; echo "===== $lane ====="

  echo "  [cot]"
  $PY scripts/summarize_cot.py "$d" --model "$MODEL" --judge-tag "$TAG" --save \
      2>&1 | tee -a "$LOG/${lane}_cot.log" | tail -1

  echo "  [support]"
  $PY scripts/score_support.py "$d" --model "$MODEL" --judge-tag "$TAG" --save \
      2>&1 | tee -a "$LOG/${lane}_support.log" | tail -1

  echo "  [outcome]"
  n=0
  for ep in "$d"/*/; do
    lab=$(basename "$ep")
    epj="$ep$lab.json"
    [ -f "$epj" ] || continue
    [ -f "$ep/scoring/$TAG/v3scores.json" ] && continue
    $PY scripts/score_tcga_episode.py "$epj" --save --llm-model "$MODEL" --judge-tag "$TAG" \
        >>"$LOG/${lane}_outcome.log" 2>&1 || echo "  !! failed: $lab" | tee -a "$LOG/${lane}_outcome.log"
    n=$((n+1))
  done
  echo "    scored $n new"
done

echo; echo "===== $TAG done in $(( ($(date +%s)-START)/60 )) min ====="
$PY scripts/panel_status.py ${WAVE:+--wave "$WAVE"}
