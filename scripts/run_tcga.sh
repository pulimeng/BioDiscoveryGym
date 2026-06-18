#!/usr/bin/env bash
# run_tcga.sh — TCGA multi-cohort benchmark runner + scorer
#
# Runs G0/G1/G2/G3 across 4 TCGA cohorts (BRCA LIHC LUAD OV) — trimmed from 7 for
# cost; G3 pairs depend on OV + LUAD. Then scores every episode. Resume-safe: skips
# runs whose JSON already exists.
#
# G3 splits into two sub-arms that share the wrong-barcode mechanic but differ
# in WHEN the fake sample codebook subtly drops:
#   G3a (ro_gate=3) — fake codebook arrives alongside the gene codebook at the
#                     3rd record_observation. Mimics old gate=0 "not fooled" regime.
#   G3b (ro_gate=5) — fake codebook arrives mid-Stage 3, after gene-based
#                     interpretation is formed. Mimics old gate=30 "fooled" regime.
#
# Usage:
#   bash scripts/run_tcga.sh --smoke-test                    # 1 cohort × 1 seed × G0/G1/G2/G3a/G3b at default 100-call budget, scored (~$15, ~1.25 hr)
#   bash scripts/run_tcga.sh --tag run10                     # full benchmark (40 episodes) + scoring (~$120)
#   bash scripts/run_tcga.sh --tag run10 --group G2          # one group only
#   bash scripts/run_tcga.sh --tag run10 --group G3          # both G3a + G3b
#   bash scripts/run_tcga.sh --tag run10 --group G3a         # one sub-arm only
#   bash scripts/run_tcga.sh --tag run10 --score-only        # score existing results
#   bash scripts/run_tcga.sh --tag run10 --skip-score        # run only, no scoring
#   bash scripts/run_tcga.sh --tag run10 --dry-run           # print commands only
#
# Environment overrides:
#   TASK_A_MODEL=claude-opus-4-7 bash scripts/run_tcga.sh --tag run10_opus

set -euo pipefail

# ── Defaults ─────────────────────────────────────────────────────────────────
TAG=""
MODEL="${TASK_A_MODEL:-claude-sonnet-4-6}"
# MAX_CALLS resolved later from USER_MAX_CALLS sentinel + smoke-test mode
BASE_DIR="results/tcga"
# G0/G1/G2 cohorts. Trimmed 2026-06-18 from 7 → 4 for cost (dropped LUSC/PRAD/UCEC:
# LUSC redundant with LUAD, PRAD weak survival signal, UCEC mutation/CN-driven subtypes).
# OV + LUAD are retained because G3_PAIRS depends on them as the true cohorts.
COHORTS=(BRCA LIHC LUAD OV)
SEEDS=(42 7 123)
G3_PAIRS=("OV:BRCA" "LUAD:LIHC")   # locked 2026-06-13 — see docs/TASK_A_COHORT.md § G3 cohort pairs

RUN_GROUP=""
DRY_RUN=0
SCORE_ONLY=0
FAILED_EPISODES=()   # episodes that errored/OOM'd — reported at the end, don't abort the batch
SKIP_SCORE=0
SMOKE_TEST=0
USER_MAX_CALLS=""             # sentinel: tracks whether --max-calls was explicitly passed

# ── Argument parsing ──────────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
    case "$1" in
        --tag)         TAG="$2";         shift 2 ;;
        --model)       MODEL="$2";       shift 2 ;;
        --max-calls)   USER_MAX_CALLS="$2"; shift 2 ;;
        --group)       RUN_GROUP="$2";   shift 2 ;;
        --dry-run)     DRY_RUN=1;        shift ;;
        --score-only)  SCORE_ONLY=1;     shift ;;
        --skip-score)  SKIP_SCORE=1;     shift ;;
        --smoke-test)  SMOKE_TEST=1;     shift ;;
        -h|--help)
            sed -n '2,18p' "$0" | sed 's/^# \{0,1\}//'
            exit 0 ;;
        *)
            echo "Unknown argument: $1" >&2; exit 1 ;;
    esac
done

# ── Smoke-test overrides ──────────────────────────────────────────────────────
# 1 cohort (OV) × 1 seed × all 4 groups (G0/G1/G2/G3).
# G3 reuses the locked OV:BRCA pair so all 4 groups touch the OV expression matrix.
#
# Two flavors via --max-calls:
#   --smoke-test                       → 15 calls, no scoring (~$1, ~10 min)   — pipeline check
#   --smoke-test --max-calls 100       → 100 calls, scored   (~$12, ~1 hr)     — depth check
# Auto-skips scoring only when MAX_CALLS ≤ 30 (too few to produce meaningful scores).
if [[ $SMOKE_TEST -eq 1 ]]; then
    [[ -z "$TAG" ]] && TAG="smoke-test"   # default tag, but respect an explicit --tag
    COHORTS=(OV)
    SEEDS=(42)
    G3_PAIRS=("OV:BRCA")
    # RUN_GROUP left as parsed: empty = all groups (full pipeline check);
    # --group G3 / G3a / G3b runs only those at smoke scale (1 cohort × 1 seed).
fi

# ── Resolve MAX_CALLS from sentinel ───────────────────────────────────────────
[[ -z "$USER_MAX_CALLS" ]] && USER_MAX_CALLS=100   # default for all modes (full + smoke)
MAX_CALLS="$USER_MAX_CALLS"

# ── Validation ────────────────────────────────────────────────────────────────
if [[ -z "$TAG" ]]; then
    echo "Error: --tag is required (e.g. --tag run10, or use --smoke-test)" >&2
    exit 1
fi

if [[ $DRY_RUN -eq 0 && -z "${ANTHROPIC_API_KEY:-}" ]]; then
    echo "Error: ANTHROPIC_API_KEY is not set." >&2
    exit 1
fi

OUT_DIR="${BASE_DIR}/${TAG}"
mkdir -p "$OUT_DIR"

# ── Summary ───────────────────────────────────────────────────────────────────
echo ""
echo "============================================================"
echo "  Task A Benchmark"
echo "  Tag      : ${TAG}"
echo "  Model    : ${MODEL}"
echo "  Max calls: ${MAX_CALLS} (Phase 1)"
echo "  Output   : ${OUT_DIR}/<uuid>/"
echo "  Group    : ${RUN_GROUP:-all}"
[[ $DRY_RUN    -eq 1 ]] && echo "  Mode     : DRY RUN"
[[ $SCORE_ONLY -eq 1 ]] && echo "  Mode     : SCORE ONLY"
[[ $SKIP_SCORE -eq 1 ]] && echo "  Scoring  : skipped"
echo "============================================================"
echo ""

# ── Helpers ───────────────────────────────────────────────────────────────────
lower() { echo "$1" | tr '[:upper:]' '[:lower:]'; }

already_run() {
    local label="$1"
    # Resume-safe: check for any JSON with this label under OUT_DIR
    [[ -n "$(find "$OUT_DIR" -name "${label}.json" 2>/dev/null | head -1)" ]]
}

run_episode() {
    local label="$1"; shift
    if already_run "$label"; then
        echo "  SKIP  $label"
        return
    fi
    echo "  RUN   $label"
    # TCGA = faithfulness rubric: Phase 1 only, no post-submission examination.
    # The known-answer comparison (reference_concordance, clinical_signal, drivers)
    # already tests recovery of the right partition. A Q1-Q4 layer on top is
    # parallel-testing the same thing at higher cost — removed 2026-06-15.
    local cmd="python scripts/run_episode.py $* \
        --model $MODEL \
        --max-tool-calls $MAX_CALLS \
        --results-base $OUT_DIR \
        --no-examination \
        --quiet \
        --save-log ${label}.json"
    if [[ $DRY_RUN -eq 1 ]]; then
        echo "        $cmd"
    else
        # Resilient: one episode failing (incl. OOM 'Killed: 9', exit 137) must NOT
        # abort the whole batch — log it and continue. Resume-safe skip means a later
        # re-run retries only the failed/missing episodes.
        local rc=0
        eval "$cmd" || rc=$?
        if [[ $rc -ne 0 ]]; then
            echo "  !! FAILED  $label (exit $rc)$( [[ $rc -eq 137 ]] && echo ' — likely OOM (SIGKILL); see memory notes' )" >&2
            FAILED_EPISODES+=("$label (exit $rc)")
        fi
    fi
}

# ── Groups ────────────────────────────────────────────────────────────────────
run_g0() {
    echo "=== G0: Explicit retrieval (${#COHORTS[@]} runs, seed 42) ==="
    for cohort in "${COHORTS[@]}"; do
        run_episode "g0_$(lower $cohort)_s42" \
            --cohort "$cohort" --seed 42 --explicit-retrieval
    done
}

run_g1() {
    echo "=== G1: Implicit retrieval — gene codebook pre-revealed (${#COHORTS[@]}×${#SEEDS[@]} runs) ==="
    for cohort in "${COHORTS[@]}"; do
        for seed in "${SEEDS[@]}"; do
            run_episode "g1_$(lower $cohort)_s${seed}" \
                --cohort "$cohort" --seed "$seed" --gene-codebook-gate 0
        done
    done
}

run_g2() {
    echo "=== G2: Data-driven — gene codebook on 3rd record_observation (Stage 2 commit) (${#COHORTS[@]}×${#SEEDS[@]} runs) ==="
    for cohort in "${COHORTS[@]}"; do
        for seed in "${SEEDS[@]}"; do
            run_episode "g2_$(lower $cohort)_s${seed}" \
                --cohort "$cohort" --seed "$seed"
        done
    done
}

run_g3a() {
    echo "=== G3a: Mislead, early drop — fake sample codebook at 3rd record_observation (${#G3_PAIRS[@]} pairs × ${#SEEDS[@]} seeds) ==="
    for pair in "${G3_PAIRS[@]}"; do
        local true_cohort="${pair%%:*}"
        local mislead_cohort="${pair##*:}"
        for seed in "${SEEDS[@]}"; do
            run_episode "g3a_$(lower $true_cohort)_mislead_$(lower $mislead_cohort)_s${seed}" \
                --cohort "$true_cohort" --mislead-cohort "$mislead_cohort" --seed "$seed" \
                --sample-codebook-ro-gate 3
        done
    done
}

run_g3b() {
    echo "=== G3b: Mislead, late drop — fake sample codebook at 5th record_observation (${#G3_PAIRS[@]} pairs × ${#SEEDS[@]} seeds) ==="
    for pair in "${G3_PAIRS[@]}"; do
        local true_cohort="${pair%%:*}"
        local mislead_cohort="${pair##*:}"
        for seed in "${SEEDS[@]}"; do
            run_episode "g3b_$(lower $true_cohort)_mislead_$(lower $mislead_cohort)_s${seed}" \
                --cohort "$true_cohort" --mislead-cohort "$mislead_cohort" --seed "$seed" \
                --sample-codebook-ro-gate 5
        done
    done
}

score_all() {
    echo ""
    echo "============================================================"
    echo "  Scoring all episodes in ${OUT_DIR}"
    echo "============================================================"
    if [[ $DRY_RUN -eq 1 ]]; then
        echo "  [dry-run] bash scripts/score_all_tcga.sh ${OUT_DIR}"
        return
    fi
    bash scripts/score_all_tcga.sh "$OUT_DIR"
}

# ── Main ─────────────────────────────────────────────────────────────────────
if [[ $SCORE_ONLY -eq 0 ]]; then
    case "$RUN_GROUP" in
        G0)  run_g0 ;;
        G1)  run_g1 ;;
        G2)  run_g2 ;;
        G3)  run_g3a; echo ""; run_g3b ;;
        G3a) run_g3a ;;
        G3b) run_g3b ;;
        "")
            run_g0;  echo ""
            run_g1;  echo ""
            run_g2;  echo ""
            run_g3a; echo ""
            run_g3b
            ;;
        *) echo "Unknown group: $RUN_GROUP. Use G0, G1, G2, G3, G3a, or G3b." >&2; exit 1 ;;
    esac
fi

if [[ ${#FAILED_EPISODES[@]} -gt 0 ]]; then
    echo ""
    echo "============================================================"
    echo "  ${#FAILED_EPISODES[@]} episode(s) FAILED (batch continued):"
    printf '    - %s\n' "${FAILED_EPISODES[@]}"
    echo "  Re-run the same command to retry them (completed episodes are skipped)."
    echo "============================================================"
fi

if [[ $SKIP_SCORE -eq 0 ]]; then
    score_all
fi

echo ""
echo "============================================================"
echo "  Done. Results: ${OUT_DIR}/"
echo "============================================================"
