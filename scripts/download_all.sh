#!/usr/bin/env bash
# Download the full BioDiscoveryGym data pipeline.
# Safe to re-run — all scripts skip already-downloaded files.
#
# Usage:
#   bash scripts/download_all.sh                           # full setup (both benchmarks)
#   bash scripts/download_all.sh --skip-tcga               # skip large TCGA downloads
#   bash scripts/download_all.sh --depmap-release 24Q2
#   bash scripts/download_all.sh --target-discovery-only   # skip anomaly-benchmark-only steps
#
# After TCGA downloads, build expression.parquet caches:
#   python scripts/process_tcga.py    # all target-discovery cohorts
#
# Cohorts by benchmark:
#   Target discovery : BRCA COAD HNSC KIRC LIHC LUAD LUSC OV PRAD SKCM
#   Anomaly detection: BRCA LUAD LUSC LIHC OV PRAD UCEC

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
CONDA_ENV="biodiscoverygym"

DEPMAP_RELEASE="23Q4"
SKIP_TCGA=0
TARGET_DISCOVERY_ONLY=0

# Parse flags
while [[ $# -gt 0 ]]; do
    case "$1" in
        --skip-tcga)               SKIP_TCGA=1 ;;
        --depmap-release)          DEPMAP_RELEASE="$2"; shift ;;
        --target-discovery-only)   TARGET_DISCOVERY_ONLY=1 ;;
        *) echo "Unknown option: $1"; exit 1 ;;
    esac
    shift
done

# Colour helpers
GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
log()  { echo -e "${GREEN}[$(date +%H:%M:%S)]${NC} $*"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $*"; }
fail() { echo -e "${RED}[FAIL]${NC} $*"; exit 1; }

cd "$ROOT"

# Activate conda env if not already active
if [[ "${CONDA_DEFAULT_ENV:-}" != "$CONDA_ENV" ]]; then
    CONDA_BASE="$(conda info --base 2>/dev/null)" || CONDA_BASE="$HOME/miniconda3"
    source "$CONDA_BASE/etc/profile.d/conda.sh"
    conda activate "$CONDA_ENV"
    log "Activated conda env: $CONDA_ENV"
fi

PYTHON="$(conda run -n "$CONDA_ENV" which python)"

run_step() {
    local label="$1"; shift
    log "=== $label ==="
    if "$PYTHON" "$@"; then
        log "$label — done"
    else
        fail "$label failed (exit $?). Fix the error and re-run; completed steps will be skipped."
    fi
    echo
}

# ------------------------------------------------------------------
# 1. DepMap / CCLE  (used by target discovery)
# ------------------------------------------------------------------
run_step "DepMap ${DEPMAP_RELEASE}" \
    scripts/download_depmap.py --release "$DEPMAP_RELEASE"

# ------------------------------------------------------------------
# 2. PRISM drug response  (used by target discovery)
# ------------------------------------------------------------------
run_step "PRISM" \
    scripts/download_prism.py

# ------------------------------------------------------------------
# 3. GTEx normal-tissue baseline  (used by target discovery)
# ------------------------------------------------------------------
run_step "GTEx v8" \
    scripts/download_gtex.py

# ------------------------------------------------------------------
# 4. gnomAD gene constraint  (used by target discovery)
# ------------------------------------------------------------------
run_step "gnomAD v2.1.1 constraint" \
    scripts/download_gnomad.py

# ------------------------------------------------------------------
# 5. HPA normal tissue protein expression  (used by target discovery)
# ------------------------------------------------------------------
run_step "Human Protein Atlas — normal tissue" \
    scripts/download_hpa.py

# ------------------------------------------------------------------
# 5b. CCLE proteomics — mass-spec protein abundance  (used by target discovery)
# ------------------------------------------------------------------
run_step "CCLE proteomics (Nusinow 2020)" \
    scripts/download_ccle_proteomics.py

# ------------------------------------------------------------------
# 6. TCGA expression + clinical
#    Target discovery: BRCA COAD HNSC KIRC LIHC LUAD LUSC OV PRAD SKCM
#    Anomaly detection adds: UCEC
# ------------------------------------------------------------------
if [[ $SKIP_TCGA -eq 1 ]]; then
    warn "Skipping TCGA downloads (--skip-tcga set)"
else
    run_step "TCGA expression + clinical (11 cohorts)" \
        scripts/download_tcga.py --cohorts BRCA COAD HNSC KIRC LIHC LUAD LUSC OV PRAD SKCM UCEC
fi

# ------------------------------------------------------------------
# 7. TCGA somatic mutations
# ------------------------------------------------------------------
if [[ $SKIP_TCGA -eq 0 ]]; then
    run_step "TCGA mutations (11 cohorts)" \
        scripts/download_mutations.py --cohorts BRCA COAD HNSC KIRC LIHC LUAD LUSC OV PRAD SKCM UCEC
fi

# ------------------------------------------------------------------
# 8. Build expression.parquet caches from raw TCGA downloads
# ------------------------------------------------------------------
if [[ $SKIP_TCGA -eq 0 ]]; then
    run_step "Build TCGA expression parquets (target discovery cohorts)" \
        scripts/process_tcga.py
fi

# ------------------------------------------------------------------
# 5c. COSMIC Cancer Gene Census  (used by target discovery)
#     Requires: COSMIC_EMAIL and COSMIC_PASSWORD env vars
# ------------------------------------------------------------------
if [[ -n "${COSMIC_EMAIL:-}" && -n "${COSMIC_PASSWORD:-}" ]]; then
    run_step "COSMIC Cancer Gene Census" \
        scripts/download_cosmic.py
else
    warn "Skipping COSMIC CGC — set COSMIC_EMAIL and COSMIC_PASSWORD to include it."
fi

# ------------------------------------------------------------------
# 9. GDSC drug response  (anomaly detection)
# ------------------------------------------------------------------
if [[ $TARGET_DISCOVERY_ONLY -eq 0 ]]; then
    run_step "GDSC" \
        scripts/download_gdsc.py
fi

# ------------------------------------------------------------------
# 10. TCGA RPPA  (anomaly detection)
# ------------------------------------------------------------------
if [[ $SKIP_TCGA -eq 0 && $TARGET_DISCOVERY_ONLY -eq 0 ]]; then
    run_step "TCGA RPPA (anomaly benchmark cohorts)" \
        scripts/download_rppa.py --cohorts BRCA PRAD UCEC LUAD LIHC LUSC OV
fi

# ------------------------------------------------------------------
# 11. TCGA molecular subtypes (anomaly detection ground truth)
# ------------------------------------------------------------------
if [[ $SKIP_TCGA -eq 0 && $TARGET_DISCOVERY_ONLY -eq 0 ]]; then
    run_step "TCGA molecular subtypes" \
        scripts/download_subtypes.py
fi

# ------------------------------------------------------------------
# 12. Gene sets + cancer gene annotations  (anomaly detection)
# ------------------------------------------------------------------
if [[ $TARGET_DISCOVERY_ONLY -eq 0 ]]; then
    run_step "MSigDB + STRING DB" \
        scripts/download_genesets.py
    run_step "OncoKB + cancer genes" \
        scripts/download_cancer_genes.py
fi

# ------------------------------------------------------------------
# Summary
# ------------------------------------------------------------------
echo -e "${GREEN}==============================${NC}"
echo -e "${GREEN}  All downloads complete.${NC}"
echo -e "${GREEN}==============================${NC}"
echo
echo "Data layout:"
du -sh "$ROOT/data"/*/  2>/dev/null || true
echo
echo "Run benchmarks:"
echo "  Target discovery : python scripts/run_target_discovery.py --indication 'AML'"
echo "  Anomaly detection: python scripts/run_episode.py --cohort LIHC"
echo "  Tests            : pytest tests/ -v"
