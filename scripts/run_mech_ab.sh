#!/usr/bin/env bash
# run_mech_ab.sh — cheap A/B test: does the loosened mechanism prompt unflatten the
# D3 (mechanism derive-vs-recall) signal?
#
# Runs a few G2 episodes under the OLD (chain-prescribed) mechanism prompt vs the NEW
# (loosened) prompt — the ONLY difference between the two prompts is the Stage-6
# mechanism lines — then scores D3 with the decision-point judge and compares the
# mechanism derived-rate.
#
# Cost: 2 arms × N cohorts episodes (~$3 each) + 2N decision-point judge calls (~$0.01).
# Default N=3 (OV LUAD LIHC, seed 42) → ~6 episodes, ~$18.
#
# Usage:
#   ANTHROPIC_API_KEY=sk-... bash scripts/run_mech_ab.sh
#   MECH_AB_COHORTS="OV LUAD" MECH_AB_SEED=7 bash scripts/run_mech_ab.sh
set -uo pipefail   # not -e: one failed episode must not stop the A/B

MODEL="${TASK_A_MODEL:-claude-sonnet-4-6}"
read -r -a COHORTS <<< "${MECH_AB_COHORTS:-OV LUAD LIHC}"
SEED="${MECH_AB_SEED:-42}"
MAXCALLS="${MECH_AB_CALLS:-100}"
OLD_PROMPT="prompts/ablation/tcga_mechchain.txt"
OLD_DIR="results/tcga/mech_ab_old"
NEW_DIR="results/tcga/mech_ab_new"

[[ -z "${ANTHROPIC_API_KEY:-}" ]] && { echo "Error: ANTHROPIC_API_KEY not set" >&2; exit 1; }
[[ -f "$OLD_PROMPT" ]] || { echo "Error: $OLD_PROMPT missing" >&2; exit 1; }

run_arm() {  # $1=outdir  $2=extra run_episode args (prompt override or empty)
    local outdir="$1"; shift
    for c in "${COHORTS[@]}"; do
        local label="g2_$(echo "$c" | tr '[:upper:]' '[:lower:]')_s${SEED}"
        if [[ -n "$(find "$outdir" -name "${label}.json" 2>/dev/null | head -1)" ]]; then
            echo "  SKIP $label"; continue
        fi
        echo "  RUN  ${outdir##*/}/$label"
        python scripts/run_episode.py --cohort "$c" --seed "$SEED" "$@" \
            --model "$MODEL" --max-tool-calls "$MAXCALLS" --results-base "$outdir" \
            --no-examination --quiet --save-log "${label}.json" \
            || echo "  !! FAILED $label"
    done
}

echo "=== ARM OLD — chain-prescribed mechanism prompt ==="
run_arm "$OLD_DIR" --prompt-file "$OLD_PROMPT"
echo "=== ARM NEW — loosened mechanism prompt (current default) ==="
run_arm "$NEW_DIR"

echo ""
echo "=== scoring decision points (both arms) ==="
python scripts/score_decision_points.py "$OLD_DIR" --save
python scripts/score_decision_points.py "$NEW_DIR" --save

echo ""
echo "============================================================"
echo "  D3 MECHANISM level comparison — old (chain) vs new (loose)"
echo "============================================================"
python3 - "$OLD_DIR" "$NEW_DIR" <<'PY'
import glob, json, sys
from collections import Counter
for name, d in [("OLD (chain)", sys.argv[1]), ("NEW (loose)", sys.argv[2])]:
    c = Counter()
    for f in glob.glob(d + "/*/*_dpscores.json"):
        c[json.load(open(f))["levels"]["d3_mechanism"]["level"]] += 1
    n = sum(c.values()) or 1
    print(f"  {name:12} n={sum(c.values())}  derived={c['derived']}/{sum(c.values())} "
          f"({c['derived']/n:.0%})  | {dict(c)}")
print("  -> if NEW derived-rate >> OLD, the loosened prompt unflattens D3.")
PY
