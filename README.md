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
# Single episode — G2 (blind, data-driven)
python scripts/run_episode.py \
    --cohort OS --seed 42 \
    --save-log results/ep.json

# G0 ceiling
python scripts/run_episode.py --cohort OS --seed 42 --mode g0

# G1 implicit retrieval
python scripts/run_episode.py --cohort OS --seed 42 --mode g1

# Score a completed episode
python scripts/score_episode_v3.py results/ep.json --cohort OS

# Pipeline smoke test (1 seed/mode, 15 calls, no exam — ~$1, ~15 min)
bash scripts/run_cohort.sh --smoke-test --cohort OS

# Full 3-mode × 3-seed OS benchmark
bash scripts/run_os_multiseed.sh

# Post-hoc modality attribution (which data types did the agent actually use?)
python scripts/modality_attribution.py
```

---

## Results

### OS Benchmark — run7 (SGH-OS, Jia et al. 2022)

91-sample osteosarcoma cohort. mRNA expression + sparse mutation panel (limited panel, no WES). 3 modes × 3 seeds.

| Group | Mean score (/18 pts) | Normalized | Notes |
|-------|--------------------:|-----------|-------|
| G0 — explicit retrieval | ~8.0 | ~0.44 | Best mean, tightest spread |
| G1 — implicit retrieval | ~7.6 | ~0.42 | Most variable |
| G2 — data-driven | ~7.7 | ~0.43 | Most stable (low seed variance) |

All 9 runs recover the same 4-cluster partition (25/25/21/20 vs paper's 25/22/23/21). Mode differences are smaller than G1 seed-to-seed variance — no mode effect detected under run7 conditions.

**run8 is pending** with the full WES mutation matrix and GISTIC CNA matrix (now processed), updated agent prompt (CNA modality added, biology hints stripped), and hardened Phase 2 rubric (5-part Q4).

Full run7 results: `results/cohort/external/os_benchmark_summary.md`

---

## Repository layout

```
biodiscoverygym/
  episode.py          — episode lifecycle: anonymization, data write, phase transitions
  executor.py         — sandboxed code execution, injects data into agent namespace
  scoring/
    components.py     — quantitative scorers (structure, survival, genomic coherence, …)
    judge.py          — LLM judge scorers (mechanism grounding, experiment quality, exam)
    evaluator_v2.py   — orchestrator: applies weights, returns ScoreReport
    evaluator_v3.py   — adds TraceReport (per-call reasoning + token attribution)
  utils/
    data_loader.py    — loads DepMap / TCGA / synthetic datasets
    hidden_context.py — manages blinding: what the agent can and cannot see

prompts/
  agent_system.txt    — unified agent system prompt (G0/G1/G2, all modalities)
  examination/        — Phase 2 examination question sets
  archive/            — superseded per-mode prompts (g0/g1/g2 pre-unification)

scripts/
  run_episode.py              — run a single Task A episode
  run_os_multiseed.sh         — 3-mode × 3-seed OS benchmark
  process_os_jia2022.py       — preprocess SGH-OS raw data → parquet
  score_episode_v3.py         — score + trace a completed episode
  modality_attribution.py     — post-hoc: which modalities did the agent use?

docs/
  GRAND_DESIGN.md     — three-part architecture (Skills Library + Benchmark + Evaluator)
  TASK_A_COHORT.md    — Task A full design, blinding implementation, empirical findings
```

---

## Tests

```bash
pytest tests/ -v
```
