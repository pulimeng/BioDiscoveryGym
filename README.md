# BioDiscoveryGym

A benchmark for evaluating LLM agents on open-ended cancer biology discovery tasks.

---

## What it measures

BioDiscoveryGym tests whether LLM agents can perform **genuine data-driven biological discovery** — or whether they produce correct answers primarily by recalling training knowledge.

The core instrument is a **three-group blinding experiment**:

| Group | Data shown | Identity visible | Tests |
|-------|-----------|-----------------|-------|
| G0 — explicit retrieval | real gene names + cancer type declared | yes | recall ceiling |
| G1 — implicit retrieval | real gene names, cancer type withheld | partial | implicit recall |
| G2 — data-driven blind  | anonymized genes (`GENE_XXXXX`) + cancer type withheld | no | pure reasoning |

If G2 scores near G0, the agent is reasoning from data. If G2 degrades sharply, recall is carrying most of the load.

**Identity blinding layers** (G2): cancer-type columns stripped, sample IDs → `SAMPLE_XXXX`, gene symbols → `GENE_XXXXX` (shuffled per episode), data served from a neutral path with no cohort-identifying filenames.

---

## Tasks

### Task A — Cohort Analysis

Given an anonymized patient cohort, discover molecular subtypes without being told the cancer type, number of groups, or scoring criteria.

**Available modalities per cohort:**

| Modality | Variable | Format |
|----------|----------|--------|
| Gene expression | `expression` | samples × genes, log1p TPM |
| Somatic mutations | `mutation` | samples × genes, binary (any functional variant) |
| Copy-number alterations | `cna` | samples × genes, GISTIC calls (0/1/2 for amp, 0/-1 for del) |
| DNA methylation | `methylation` | samples × CpG probes, beta values |
| Protein expression (RPPA) | `rppa` | samples × proteins |
| Clinical metadata | `metadata` | survival, age, staging (remapped to `CAT_X`) |

Not all modalities are present for every cohort; the agent must check for `None` and adapt.

### Task B — Target Discovery

Given population-scale cancer dependency and normal tissue data, reason to a computationally supported therapeutic target without being told what criteria define a good target.

The chain it should construct: CRISPR selective dependency → cancer specificity → normal tissue tolerance (GTEx) → human tolerability (gnomAD pLI) → mechanism (STRING/pathway DBs) → patient frequency (TCGA) → evidence gaps stated → experimental roadmap.

---

## Scoring

Two phases, scored independently.

### Phase 1 — Discovery (18 pts max)

| Component | Weight | What it measures |
|-----------|--------|-----------------|
| `structure_validity` | 2 | Bootstrap-stable silhouette + ARI vs k-means re-cluster |
| `clinical_signal` | 3 | ΔC-index over null Cox + log HR between extreme-survival subtypes |
| `genomic_coherence_drivers` | 2 | Driver gene enrichment in the submitted subtype grouping |
| `genomic_coherence_rppa` | 2 | RPPA protein concordance with expression subtypes |
| `reference_concordance` | 2 | Overlap of submitted markers with curated subtype signatures |
| `marker_evidence` | 2 | OvR AUC of submitted top genes for their claimed subtype |
| `pathway_validity` | 1 | GSEA enrichment of submitted pathways in top DE genes |
| `mechanism_grounding` | 2 | LLM judge (3 axes: coherence, data grounding, mechanistic logic) |
| `experiment_quality` | 2 | LLM judge: is the proposed experiment specific and falsifiable? |

### Phase 2 — Examination (5 pts max)

Triggered after data lock. Agent answers Q1–Q4 (mechanistic deep-dive) and is scored on:

| Component | Weight | What it measures |
|-----------|--------|-----------------|
| `exam_data_lock_quality` | 1 | Completeness of committed sweep results |
| `exam_experiment_depth` | 2 | 5-part Q4 rubric: named model + numeric justification, perturbation with direction, assay with magnitude threshold, falsification criterion, orthogonal-modality prediction |
| `exam_mechanistic_integration` | 2 | Cross-modal consistency, quantitative grounding, causal chain completeness |

Phase 2 uses an adversarial judge stance — partial answers that omit direction, magnitude, or specific cell line identifiers are scored 0, not charitably.

---

## Setup

```bash
conda env create -f environment.yaml
conda activate biodiscoverygym
pip install -e .
export ANTHROPIC_API_KEY="sk-..."
```

### OS cohort data (SGH-OS, Jia et al. 2022)

Raw data from GSA accession HRA003260. After downloading, preprocess:

```bash
python scripts/process_os_jia2022.py \
    --raw-dir data/os_jia2022/raw \
    --out-dir data/os_jia2022 \
    --min-vaf 0.05
```

This produces:
- `expression.parquet` — 91 × ~20k genes, log1p TPM
- `mutations.parquet` — 91 × 3779 genes, binary functional variants (VAF ≥ 0.05)
- `cna.parquet` — 91 × 1618 genes, GISTIC focal calls (cytoband-aligned, DUX/OR artifacts blacklisted)
- `OS_clinical.tsv` — survival, grade, histology

For other TCGA cohorts, see `scripts/download_tcga.py` and `scripts/process_tcga.py`.

---

## Running

```bash
# Single episode — G2 (blind, data-driven; codebook gated on Stage 2 record_observation)
python scripts/run_episode.py \
    --cohort OS --seed 42 \
    --save-log results/ep.json

# G0 ceiling — disease + gene names revealed
python scripts/run_episode.py --cohort OS --seed 42 --explicit-retrieval

# G1 — gene names revealed, disease redacted
python scripts/run_episode.py --cohort OS --seed 42 --gene-codebook-gate 0

# Score a completed episode (cohort-specific track)
python scripts/score_sghos_episode.py results/external/<run>/<uuid>/<label>.json --save        # OS discovery rubric (24 pts)
python scripts/score_tcga_episode.py results/tcga/<run>/<uuid>/<label>.json --cohort BRCA --save  # TCGA faithfulness rubric (16 pts)

# Pipeline smoke test (1 seed/mode, 15 calls, no exam — ~$1, ~15 min)
bash scripts/run_cohort.sh --smoke-test --cohort OS

# Full OS benchmark (G0/G1/G2 × 3 seeds = 9 episodes; ~$30 on Sonnet)
bash scripts/run_cohort.sh --tag run10 --cohort OS

# Null-baseline calibration for OS discovery rubric
python scripts/calibrate_os_null.py --n-iter 100 --seed 42

# Post-hoc modality attribution (which data types did the agent actually use?)
python scripts/modality_attribution.py
```

---

## Results

### OS Discovery Benchmark — SGH-OS (Jia et al. 2022)

91-sample osteosarcoma cohort. mRNA expression + sparse mutation panel + DNA methylation + GISTIC CNA. Three modes (G0/G1/G2) × 3 seeds = 9 episodes per run.

**Latest: run9_marker (2026-06-08).** Biomarker-discovery prompt (`agent_system_os.txt`) with pre-registration, [PRIOR]/[DATA] discipline, and two-of-three provenance. 13 episodes (the now-deprecated 5-seed config); all converged on residual prognostic structure (CX3CL1, EPHA2, FAM110D, ZBTB42, TRIM9) rather than the dominant SP7/RUNX2 axis from earlier runs.

**External validation (2026-06-11)** in TARGET-OS (n=85 with survival, independent pediatric/AYA osteosarcoma cohort):
- Co-expression structure REPLICATES (matrix ρ=0.81 vs SGH-OS; 84% sign concordance; OS-specific vs non-OS control ρ=−0.14)
- Prognostic signature is **indistinguishable from random gene-set chance** in TARGET-OS (Cox HR=1.08, p=0.70 vs SGH-OS HR=0.42, p=1e-6). Signed-correlation diagnostic across 13 episodes: mean ρ = −0.064 (Wilcoxon p=0.008 against 0 but tiny effect) — signatures are uninformative in TARGET-OS, not actively wrong.
- Positive controls (cytolytic, hypoxia, metastasis_at_dx) all detected in TARGET-OS → the null on the candidate signatures is genuine, not cohort underpowering.

The co-expressed biology is real; the prognostic claim was in-sample optimism — a sharper statement of the rare-cohort biomarker problem than the literature usually makes. See `docs/TASK_A_COHORT.md` § "External Validation" and § "Scoring (post-hoc, bifurcated)" for the OS discovery scoring system (Phase 1 + 2 + 3, 23 pt ceiling) with null calibration framework.

---

## Repository layout

```
biodiscoverygym/
  episode.py          — episode lifecycle: anonymization, data write, phase transitions
  executor.py         — sandboxed code execution, injects data into agent namespace
  scoring/
    components.py     — TCGA + shared computational scorers (structure, survival, …)
    components_os.py  — OS discovery scorers (survival_stratification, provenance_integrity,
                        cross_modal_support, target_coexpr/survival_replication)
    judge.py          — TCGA LLM judges (mechanism grounding, experiment quality, exam)
    judge_os.py       — OS LLM judges (prior_data discipline, discovery_beyond_priors,
                        data_lock citation, multi-modal integration)
    evaluator_v2.py   — TCGA Phase 1 orchestrator
    evaluator_v3.py   — TCGA Phase 1+2 + trace
    evaluator_os.py   — OS discovery scorer (Phase 1 + 2 + 3 = 23 pts)
  utils/
    data_loader.py    — loads DepMap / TCGA / external (SGH-OS, TARGET) datasets
    hidden_context.py — manages blinding: what the agent can and cannot see

prompts/
  agent_system_tcga.txt — TCGA faithfulness prompt (G0/G1/G2)
  agent_system_os.txt   — OS discovery prompt (G0/G1/G2)
  agent_system.txt      — legacy unified prompt (fallback only)
  examination/          — Phase 2 examination question sets
  archive/              — superseded per-mode prompts

scripts/
  run_episode.py              — run a single episode
  run_cohort.sh               — OS multi-seed benchmark runner
  run_tcga.sh                 — TCGA multi-seed benchmark runner
  process_os_jia2022.py       — preprocess SGH-OS raw data → parquet
  process_target.py           — preprocess TARGET pan-cancer (Phase 3 validation source)
  score_sghos_episode.py         — score OS episode (discovery rubric)
  score_tcga_episode.py       — score TCGA episode (faithfulness rubric)
  score_all_sghos.sh             — batch-score an OS results directory
  score_all_tcga.sh           — batch-score a TCGA results directory
  calibrate_os_null.py             — null-baseline calibration for OS discovery scorer
  signed_correlation_diagnostic.py — signature direction replication test (TARGET-OS)
  modality_attribution.py          — post-hoc: which modalities did the agent use?
  archive/                         — abandoned Task B + experimental scorers

analysis/                          — (gitignored) one-off analysis scripts + outputs
  external_validation.py           — TARGET-OS survival validation harness w/ positive controls
  validate_run9_target*.py         — run9-specific TARGET-OS replication analyses
  run9_target_validation/          — output tables, figures, reports

docs/
  GRAND_DESIGN.md     — three-part architecture (Skills Library + Benchmark + Evaluator)
  TASK_A_COHORT.md    — Task A full design, scoring system, empirical findings
```

---

## Tests

```bash
pytest tests/ -v
```
