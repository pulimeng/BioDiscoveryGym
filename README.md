# BioDiscoveryGym

A benchmark for evaluating LLM agents on open-ended cancer biology discovery tasks.

The benchmark probes whether LLM agents can perform **genuine data-driven biological discovery** — or whether they produce correct answers primarily by recalling training knowledge. The core instrument is a multi-group blinding experiment that progressively hides cohort identity, sample provenance, and gene symbols, then watches how the agent's reasoning chain and final submission change.

---

## Two experiments, two scoring rubrics

The benchmark runs two parallel experiments that share infrastructure but answer different questions. Each has its own runner, prompt, and scoring rubric.

|  | TCGA experiment | SGH-OS experiment |
|---|---|---|
| **Scoring intent** | Faithfulness — did the agent recover the known TCGA subtype answer via data-driven reasoning rather than literature recall? | Discovery — did the agent find prognostic biomarkers in n=91 SGH-OS that generalize to TARGET-OS, beyond what Jia et al. 2022 reports? |
| **Reference answer exists** | Yes (TCGA pancan subtype calls) | No (the paper's marker list is the literature baseline to *go past*) |
| **External validation cohort** | None | TARGET-OS (n=85 with survival) — Phase 3 |
| **Cohorts** | BRCA, PRAD, UCEC, LUAD, LIHC, LUSC, OV (7) | SGH-OS only |
| **Groups** | G0, G1, G2, G3 | G0, G1, G2 (no G3 — single cohort) |
| **Scoring ceiling** | **16 pts** (Phase 1 only) | **24 pts** (Phase 1 + 2 + 3) |

---

## Blinding strategy

Each group dials the same channels (cohort identity, gene symbols, sample barcodes, clinical categoricals) but reveals them at different points in the episode. This is what isolates "data-driven reasoning" from "implicit recall."

| Group | Cohort name | Gene codebook (real symbols) | Sample IDs → real barcodes | Special |
|---|---|---|---|---|
| **G0** — explicit retrieval | **Revealed in system prompt** | Revealed at episode start | Revealed at episode start | Recall ceiling |
| **G1** — implicit retrieval | Redacted | Revealed at episode start (`gene_codebook_gate=0`) | Via `request_sample_codebook()` after tool call #25 | Tests gene-name-mediated recall |
| **G2** — data-driven blind | Redacted | **Subtle drop**: appended to the agent's 3rd `record_observation` tool result (Stage 2 partition-commit checkpoint) | Via `request_sample_codebook()` after tool call #25 | Tests pure data-driven reasoning |
| **G3** — mislead (TCGA only) | Redacted | Same as G2 | Same as G2, BUT barcodes are from a **different cohort** (e.g., OV samples labeled as BRCA-style) | Tests whether the agent trusts data over misleading provenance |

**Always stripped** (regardless of group): cancer-type columns in metadata; subtype/cluster labels (the paper's answer); cohort-fingerprinting categorical values (e.g. Enneking stage `IIB`/`III` → `CAT_0`/`CAT_1`).

**The G1→G2 delta** is the cleanest single-variable test in the benchmark: the only thing that differs is *when* the gene codebook arrives (call 0 vs ~call 25–35 once the agent has worked through Stages 0–2 on GENE_XXXXX). If a model performs similarly on G1 and G2, it's reasoning from molecular structure. If G2 degrades sharply, gene-symbol recall was carrying the work.

**The G2→G3 delta** (TCGA only) is the mislead-resilience test: identical pipeline to G2 plus wrong-cohort barcodes. G3 pairs are locked at OV:BRCA (female cancer recall) and LUAD:LIHC (common adult solid tumor recall).

---

## Available modalities per cohort

The agent must check for `None` and adapt — not every modality is present everywhere.

| Modality | Variable | Format | TCGA | SGH-OS |
|---|---|---|:-:|:-:|
| Gene expression | `expression` | samples × genes, log2(CPM+1) | ✅ | ✅ 18,869 genes |
| Somatic mutations | `mutation` | samples × genes, binary (functional variant) | ✅ | ✅ 3,779 genes (panel, sparse) |
| Copy-number alterations | `cna` | samples × genes, GISTIC focal calls (+1 amp / −1 del / 0 neutral) | ✅ | ✅ 1,618 genes |
| DNA methylation | `methylation` | samples × CpG probes, beta values | varies | ✅ 10,000 most-variable CpGs |
| Protein expression (RPPA) | `rppa` | samples × proteins, z-scores | ✅ | ❌ |
| Clinical metadata | `metadata` | survival, stage, age, gender (categorical values remapped to `CAT_X` for non-G0) | ✅ | ✅ |

---

## Scoring

### TCGA — faithfulness rubric (16 pts, Phase 1 only)

Test whether the agent **derived** the known TCGA subtype biology from data rather than **recalled** it from literature. Examination phase removed 2026-06-15 (the Phase 1 components already cover the faithfulness signal).

| Component | Weight | What it measures |
|---|---:|---|
| `structure_validity` | 2 | Bootstrap silhouette + ARI vs k-means re-cluster |
| `clinical_signal` | 3 | ΔC-index over null Cox + log HR between extreme-survival subtypes |
| `genomic_coherence_drivers` | 2 | FDR-corrected Fisher exact for OncoKB drivers per subtype |
| `genomic_coherence_rppa` | 2 | ARI between expression grouping and RPPA k-means re-cluster |
| `reference_concordance` | 2 | **Faithfulness anchor**: max NMI across known TCGA subtype schemes |
| `marker_evidence` | 2 | HGNC validity + one-vs-rest AUC + OncoKB driver overlap |
| `pathway_validity` | 1 | GMT name validity (MSigDB Hallmarks / Reactome / GO / KEGG) + ORA enrichment bonus |
| `mechanism_grounding` | 2 | LLM judge — 3 axes: internal coherence, data grounding, mechanistic logic |
| **Total** | **16** | |

14 of 16 pts are deterministic computational. Only `mechanism_grounding` (2 pts) uses an LLM judge — specifically because its `data_grounding` axis is what distinguishes data-derivation from literature recall.

### SGH-OS — discovery rubric (24 pts, Phase 1 + 2 + 3)

Test whether the agent finds prognostic biomarkers that **generalize** to an independent cohort (TARGET-OS), beyond what the source paper reports. Reference concordance is deliberately absent — recovering the paper's subtypes would be the opposite of discovery.

#### Phase 1 — structural + computational (16 pts)

| Component | Weight | What it measures |
|---|---:|---|
| `structure_validity` | 2 | Same as TCGA — bootstrap silhouette + ARI |
| `survival_stratification` | 3 | Multi-group log-rank p (1.5) + Cox max-vs-min HR magnitude (1.5) |
| `provenance_integrity` | 3 | Per-gene audit of the prompt's 2-of-3 test: DE FDR<0.05 BH + survival correlation FDR<0.05 BH + methylation CpG correlation OR CNA Fisher. Score = fraction of submitted `top_genes` passing ≥2 |
| `pathway_validity` | 1 | Same as TCGA — direction-neutral GMT name + ORA check |
| `mechanism_grounding` | 3 | OS-specific LLM judge — 3 axes: prior/data discipline, causal chain from data, discovery beyond priors |
| `cross_modal_support` | 2 | Stricter than provenance test 3: per gene, RNA evidence (DE OR survival, p<0.05) **AND** non-RNA evidence (methylation OR CNA) |
| `validation_experiment` | 2 | LLM judge (reused from TCGA stack) — 4 binary criteria for proposed next experiment |

#### Phase 2 — post-submission Examination (3 pts)

Triggered after `submit_discovery`. Agent commits a Data Lock report then answers Q1–Q4.

| Component | Weight | What it measures |
|---|---:|---|
| `exam_data_lock_quality` | 1 | Regex coverage of 5 required Data Lock sections (PC loadings, survival, mutation, methylation/RPPA, unexpected finding) |
| `exam_mechanistic_integration` | 2 | OS-specific LLM judge on Q1–Q4: Data Lock numeric citation, multi-modal integration, [PRIOR]/[DATA] discipline |

#### Phase 3 — external validation in TARGET-OS (5 pts)

Hands the submitted gene set to TARGET-OS (n=85 independent pediatric/AYA osteosarcoma with survival) and lets the data decide whether the signature replicates.

| Component | Weight | What it measures |
|---|---:|---|
| `target_coexpr_replication` | 2 | Three subscores averaged: `os_specificity_delta` (target_os ρ − target_non_os ρ), sign concordance of pairwise correlations, leave-one-out signature direction match |
| `target_survival_replication` | 3 | Direction-as-gate: wrong-direction signature = 0. Right direction → (significance + magnitude) / 2. Literature positive controls (cytolytic, IFN-γ, hypoxia, proliferation, metastasis_at_dx) verify the cohort can detect signal |

The Phase 3 verdict is the only direct empirical answer to "is this a discovery or in-sample optimism?"

### Null-baseline calibration (SGH-OS only)

```bash
python scripts/calibrate_os_null.py --n-iter 100 --seed 42
```

Runs the scorer on 100 random gene sets to establish per-component chance floors. Two modes (random partition + random gene set; fixed partition + random gene set) decompose which signal comes from partition quality vs gene-set quality. Saved to `data/calibration/os_null_baseline_*.json`. See `docs/TASK_A_COHORT.md` § Calibration for the empirical findings.

---

## Setup

```bash
conda env create -f environment.yaml
conda activate biodiscoverygym
pip install -e .
export ANTHROPIC_API_KEY="sk-..."
```

### TCGA cohort data

```bash
python scripts/download_tcga.py    # downloads BRCA, PRAD, UCEC, LUAD, LIHC, LUSC, OV
python scripts/process_tcga.py     # builds expression.parquet caches
```

### SGH-OS cohort data (Jia et al. 2022)

Raw data from GSA accession HRA003260. After downloading:

```bash
python scripts/process_os_jia2022.py \
    --raw-dir data/external/os_jia2022/raw \
    --out-dir data/external/os_jia2022 \
    --min-vaf 0.05
```

Produces `expression.parquet` (91 × 18,869), `mutations.parquet` (91 × 3,779), `cna.parquet` (91 × 1,618), `methylation.parquet` (91 × 10,000), and `OS_clinical.tsv`.

### TARGET-OS (for SGH-OS Phase 3 validation)

```bash
python scripts/process_target.py   # processes TARGET pan-cancer; OS arm = 88 samples, 85 with survival
```

---

## Running

### Single episode

```bash
# G2 default — blind, data-driven, codebook gated on 3rd record_observation
python scripts/run_episode.py --cohort OS --seed 42 --save-log results/ep.json

# G0 ceiling — disease + gene names revealed
python scripts/run_episode.py --cohort OS --seed 42 --explicit-retrieval

# G1 — gene names revealed, disease redacted
python scripts/run_episode.py --cohort OS --seed 42 --gene-codebook-gate 0

# G3 — TCGA only; mislead with wrong-cohort barcodes
python scripts/run_episode.py --cohort OV --mislead-cohort BRCA --seed 42
```

### Multi-seed benchmarks

```bash
# === TCGA ===
bash scripts/run_tcga.sh --smoke-test    # 1 cohort × 1 seed × G0/G1/G2/G3, 100 calls, scored (~$12, ~1 hr)
bash scripts/run_tcga.sh --tag run10     # full 55 episodes + scoring                          (~$165)

# === SGH-OS ===
bash scripts/run_cohort.sh --smoke-test --cohort OS   # 1 seed/mode × 15 calls, no scoring     (~$1)
bash scripts/run_cohort.sh --tag run10 --cohort OS    # full G0/G1/G2 × 3 seeds = 9 episodes   (~$30)
```

The runners are **resume-safe** — they check for `<label>.json` in the output directory and skip already-completed episodes. To re-run a tag from scratch, `rm -rf` its output directory first.

### Post-hoc scoring

```bash
# SGH-OS — discovery rubric (24 pts)
python scripts/score_sghos_episode.py results/external/<run>/<uuid>/<label>.json --save

# TCGA — faithfulness rubric (16 pts)
python scripts/score_tcga_episode.py results/tcga/<run>/<uuid>/<label>.json --cohort BRCA --save

# Batch
bash scripts/score_all_sghos.sh results/external/<run>/
bash scripts/score_all_tcga.sh results/tcga/<run>/

# Skip LLM judges (no API cost, partial score)
python scripts/score_sghos_episode.py <...>.json --skip-llm
```

The scoring scripts fail-fast if `ANTHROPIC_API_KEY` is missing (LLM-judge components otherwise silently zero). Pass `--skip-llm` for explicit opt-out.

---

## Repository layout

```
biodiscoverygym/
  episode.py                — episode lifecycle: anonymization, data write, phase transitions
  executor.py               — sandboxed code execution, injects data into agent namespace
  scoring/
    components.py           — TCGA + shared computational scorers (structure, survival, …)
    components_os.py        — OS-specific computational scorers (survival_stratification,
                              provenance_integrity, cross_modal_support, target_*_replication)
    judge.py                — TCGA LLM judges (mechanism grounding, experiment quality, exam)
    judge_os.py             — OS LLM judges (prior/data discipline, discovery beyond priors,
                              Data Lock citation, multi-modal integration)
    evaluator_v2.py         — TCGA Phase 1 orchestrator (16 pts)
    evaluator_v3.py         — TCGA + trace extraction + (legacy) Phase 2 attachment
    evaluator_os.py         — OS discovery scorer (Phase 1 + 2 + 3 = 24 pts)
  utils/
    data_loader.py          — loads TCGA / external (SGH-OS, TARGET) datasets
    hidden_context.py       — manages blinding: what the agent can and cannot see

prompts/
  agent_system_tcga.txt     — TCGA faithfulness prompt
  agent_system_os.txt       — OS discovery prompt (Stage 0–5 with multi-modal scaffolding)
  examination/              — Phase 2 examination question sets (OS only now)
  archive/                  — superseded prompts

scripts/
  run_episode.py            — single-episode CLI
  run_cohort.sh             — OS multi-seed runner (G0/G1/G2 × seeds)
  run_tcga.sh               — TCGA multi-seed runner (G0/G1/G2/G3 × seeds × cohorts)
  process_os_jia2022.py     — preprocess SGH-OS raw data → parquet
  process_target.py         — preprocess TARGET pan-cancer (Phase 3 source)
  process_tcga.py           — preprocess TCGA cohorts
  score_sghos_episode.py    — single-episode OS scorer
  score_tcga_episode.py     — single-episode TCGA scorer
  score_all_sghos.sh        — batch OS scoring
  score_all_tcga.sh         — batch TCGA scoring
  calibrate_os_null.py      — OS null-baseline calibration
  signed_correlation_diagnostic.py  — OS signature direction replication diagnostic
  modality_attribution.py   — post-hoc: which modalities did the agent use?
  archive/                  — abandoned Task B + experimental scorers

analysis/                   — (gitignored) one-off analysis scripts + outputs
  external_validation.py    — TARGET-OS survival validation harness w/ positive controls

docs/
  GRAND_DESIGN.md           — three-part architecture (Skills Library + Benchmark + Evaluator)
  TASK_A_COHORT.md          — full task design, scoring system, empirical findings
  BENCHMARK_PLAN.md         — running notes on benchmark cohort + group choices
```

---

## Tests

```bash
pytest tests/ -v
```
