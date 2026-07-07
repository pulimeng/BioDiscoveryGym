#!/usr/bin/env bash
# smoke_ladder.sh — one episode per provider to verify PARITY before funding the full ladder.
#
# Runs the identical G2 episode (BRCA, seed 42, thinking off) on each model and checks the
# things that must match across providers:
#   - the model actually uses record_observation (else the G2 codebook never reveals)
#   - the gene codebook reveals at the SAME record_observation turn (deterministic gate)
#   - tools parse and a discovery is submitted
# Skips any provider whose API key isn't set. Cheap (~cents–$1/model at 50 calls).
#
# Setup:  pip install anthropic openai google-genai
#         export ANTHROPIC_API_KEY=... OPENAI_API_KEY=... GEMINI_API_KEY=...   (or GOOGLE_API_KEY)
# Usage:  bash scripts/smoke_ladder.sh
#         SMOKE_MODELS="claude-opus-4-8 gpt-4.1" SMOKE_CALLS=40 bash scripts/smoke_ladder.sh
set -o pipefail   # not -u: macOS bash 3.2 errors on empty-array expansion under -u

COHORT="${SMOKE_COHORT:-BRCA}"
COHORT_LC="$(echo "$COHORT" | tr '[:upper:]' '[:lower:]')"   # bash 3.2 has no ${var,,}
SEED="${SMOKE_SEED:-42}"
CALLS="${SMOKE_CALLS:-50}"
read -r -a MODELS <<< "${SMOKE_MODELS:-claude-sonnet-5 claude-opus-4-8 gpt-5.5 gemini-3.5-pro}"
OUT="results/tcga/_smoke/ladder"
mkdir -p "$OUT"

key_ok() {  # $1=model -> 0 if the required API key is present
    case "$1" in
        claude*)            [[ -n "${ANTHROPIC_API_KEY:-}" ]] ;;
        gpt*|o[0-9]*)   [[ -n "${OPENAI_API_KEY:-}" ]] ;;
        gemini*)            [[ -n "${GEMINI_API_KEY:-}" || -n "${GOOGLE_API_KEY:-}" ]] ;;
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
    tag="${m//[^a-zA-Z0-9]/_}"
    label="g2_${COHORT_LC}_s${SEED}_${tag}"
    if ! key_ok "$m"; then
        echo ">>> SKIP $m — $(key_name "$m") not set"
        SUMMARY+=("$m|SKIP (no key)|-|-|-|-")
        continue
    fi
    echo ">>> RUN  $m  ($label)"
    log="$OUT/${label}.log"
    python scripts/run_episode.py --cohort "$COHORT" --seed "$SEED" --model "$m" \
        --max-tool-calls "$CALLS" --no-examination --results-base "$OUT" \
        --save-log "${label}.json" >"$log" 2>&1
    rc=$?
    # parity metrics from the saved episode + the log
    metrics=$(python3 - "$OUT" "$label" "$log" "$rc" <<'PY'
import glob, json, re, sys
outdir, label, logpath, rc = sys.argv[1:5]
files = sorted(glob.glob(f"{outdir}/*/{label}.json"))
if not files:
    print(f"FAILED (rc={rc}, no episode json)|-|-|-|-"); raise SystemExit
d = json.load(open(files[-1]))
ro = len(d.get("observations") or [])
rc_calls = sum(1 for msg in d.get("messages", [])
               if isinstance(msg.get("content"), list)
               for b in msg["content"]
               if isinstance(b, dict) and b.get("type") == "tool_use" and b.get("name") == "run_code")
submitted = "yes" if d.get("discovery") else "no"
try:
    reveal = re.search(r"Codebook revealed on record_observation #(\d+)", open(logpath).read())
    reveal = reveal.group(1) if reveal else "none"
except OSError:
    reveal = "?"
status = "ok" if (rc == "0" and submitted == "yes") else f"partial(rc={rc})"
print(f"{status}|{ro}|{rc_calls}|{reveal}|{submitted}")
PY
)
    SUMMARY+=("$m|$metrics")
    echo "    -> $metrics"
done

echo ""
echo "============================================================================"
echo "  SMOKE LADDER — parity check (G2 $COHORT seed $SEED, thinking off)"
echo "============================================================================"
printf "  %-22s %-16s %5s %5s %8s %6s\n" model status "#RO" "#run" "reveal@RO" "submit"
for row in "${SUMMARY[@]}"; do
    IFS='|' read -r m st ro rc rev sub <<< "$row"
    printf "  %-22s %-16s %5s %5s %8s %6s\n" "$m" "$st" "$ro" "$rc" "$rev" "$sub"
done
echo ""
echo "  PARITY = good if 'reveal@RO' is the SAME across models (deterministic gate) and every"
echo "  model submitted. A model with reveal=none never called record_observation -> its G2"
echo "  codebook never fired: an adapter/tool-parsing problem to fix before the full ladder."
