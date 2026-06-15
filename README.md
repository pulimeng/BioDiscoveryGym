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

#### Phase 1 — 8 components, 16 pts

| # | Component | Wt | Type | What it measures | Implementation |
|---|---|---:|---|---|---|
| 1 | `structure_validity` | 2 | computational | Partition is well-formed: bootstrap silhouette + ARI vs k-means re-cluster on PCA-reduced expression (50 dims) | `components.score_structure_validity` |
| 2 | `clinical_signal` | 3 | computational | Subtypes stratify survival: ΔC-index over null Cox (60% weight) + log HR between best- and worst-survival extreme groups (40% weight) | `components.score_clinical_signal` |
| 3 | `genomic_coherence_drivers` | 2 | computational | OncoKB driver mutations enrich per subtype via FDR-corrected Fisher exact (one-vs-rest per gene per subtype) | `components.score_driver_enrichment` |
| 4 | `genomic_coherence_rppa` | 2 | computational | Expression-derived grouping is coherent with protein-level structure: ARI between submitted partition and RPPA k-means re-cluster | `components.score_rppa_concordance` |
| 5 | `reference_concordance` | 2 | computational | **Faithfulness anchor** — recovered the known answer: max NMI across `pancan_subtypes.tsv` and `TCGASubtype.20170308.tsv.gz` schemes | `components.score_reference_concordance` |
| 6 | `marker_evidence` | 2 | computational | Submitted `top_genes` actually mark their clusters: 40% HGNC validity + 40% one-vs-rest AUC + 20% OncoKB driver overlap | `components.score_marker_evidence` |
| 7 | `pathway_validity` | 1 | computational | Pathway names are real GMT entries (MSigDB Hallmarks / Reactome / GO / KEGG) + ORA enrichment of `top_genes` adds a bonus | `components.score_pathway_validity` |
| 8 | `mechanism_grounding` | 2 | LLM judge | 3 axes scored /4 each, total /12: internal coherence (hypothesis follows from genes/pathways), data grounding (claims traceable to dataset numbers — the faithfulness signal), mechanistic logic (directional A→B→C chain with named actors) | `judge.score_mechanism_grounding` |
| | **Phase 1 total** | **16** | | | |

14 of 16 pts are deterministic computational. Only `mechanism_grounding` (2 pts) uses an LLM judge — specifically because its `data_grounding` axis is what distinguishes data-derivation from literature recall.

### SGH-OS — discovery rubric (24 pts, Phase 1 + 2 + 3)

Test whether the agent finds prognostic biomarkers that **generalize** to an independent cohort (TARGET-OS), beyond what the source paper reports. Reference concordance is deliberately absent — recovering the paper's subtypes would be the opposite of discovery.

#### Phase 1 — 7 components, 16 pts

| # | Component | Wt | Type | What it measures | Implementation |
|---|---|---:|---|---|---|
| 1 | `structure_validity` | 2 | computational | Same as TCGA — partition well-formedness via silhouette + bootstrap ARI | `components.score_structure_validity` (shared) |
| 2 | `survival_stratification` | 3 | computational | OS-specific Cox survival test: multi-group log-rank p scaled `-log10(p)/4` (1.5 pts) + Cox max-vs-min HR magnitude scaled `log(HR)/log(4)` (1.5 pts) | `components_os.score_survival_stratification` |
| 3 | `provenance_integrity` | 3 | computational | Per-gene independent re-audit of the prompt's 2-of-3 test: (a) DE FDR<0.05 BH between groups, (b) Spearman ρ with OS time, FDR<0.05 BH, (c) methylation CpG-expression correlation FDR<0.05 BH OR CNA Fisher per group. Score = fraction of submitted `top_genes` passing ≥2 of 3 | `components_os.score_provenance_integrity` |
| 4 | `pathway_validity` | 1 | computational | Same as TCGA — direction-neutral GMT name + ORA check. Catches hallucinated pathway names without rewarding recovery of known biology | `components.score_pathway_validity` (shared) |
| 5 | `mechanistic_grounding` | 3 | LLM judge | OS-specific 3 axes scored /4 each, total /12: prior/data discipline (labels + cited computations), causal chain from data (each link grounded in cohort numbers), discovery beyond priors (identifies novel claims explicitly) | `judge_os.score_mechanism_grounding_os` |
| 6 | `cross_modal_support` | 2 | computational | Stricter than provenance test 3: per gene, requires **both** RNA evidence (DE OR survival, nominal p<0.05) **AND** non-RNA evidence (methylation CpG correlation OR CNA Fisher). Score = fraction with both | `components_os.score_cross_modal_support` |
| 7 | `validation_experiment` | 2 | LLM judge | Reused from TCGA stack — 4 binary criteria for the proposed next experiment: specific model, specific perturbation + method, specific assay, quantitative outcome | `judge.score_experiment_quality` |
| | **Phase 1 subtotal** | **16** | | | |

13 of 16 Phase 1 pts are deterministic computational; 3 LLM-judge pts come from `mechanistic_grounding`. The `validation_experiment` judge is also LLM-based but at 2 pts.

#### Phase 2 — post-submission Examination (3 pts)

Triggered after `submit_discovery`. Agent commits a Data Lock report then answers Q1–Q4.

| # | Component | Wt | Type | What it measures | Implementation |
|---|---|---:|---|---|---|
| 8 | `exam_data_lock_quality` | 1 | computational (regex) | Data Lock contains 5 required sections: PC loadings, survival, mutation enrichment, methylation OR RPPA cross-modal, an explicitly-flagged unexpected finding | `components.score_exam_data_lock_quality` (shared) |
| 9 | `exam_mechanistic_integration` | 2 | LLM judge | OS-specific 3 axes scored /4 each, total /12: Data Lock numeric citation (≥6 specific values from the Lock cited in answers), multi-modal integration (≥3 modalities woven into ONE causal model), [PRIOR]/[DATA] labeling discipline maintained throughout Q1–Q4 | `judge_os.score_exam_mechanistic_integration_os` |
| | **Phase 2 subtotal** | **3** | | | |

#### Phase 3 — external validation in TARGET-OS (5 pts)

Hands the submitted gene set to TARGET-OS (n=85 independent pediatric/AYA osteosarcoma with survival) and lets the data decide whether the signature replicates. The empirical "is this a discovery?" component.

| # | Component | Wt | Type | What it measures | Implementation |
|---|---|---:|---|---|---|
| 10 | `target_coexpr_replication` | 2 | computational | Three subscores averaged: (a) `os_specificity_delta` = matrix ρ (SGH-OS ↔ TARGET-OS pairwise correlations) − matrix ρ (SGH-OS ↔ TARGET-non-OS, negative control), (b) off-diagonal sign concordance scaled `(conc − 0.5)·2`, (c) leave-one-out signature direction match (each gene tested against signature built from the *other* genes — kills the tautological self-correlation bias) | `components_os.score_target_coexpr_replication` |
| 11 | `target_survival_replication` | 3 | computational | Direction-as-gate: wrong-direction Cox HR (>1 when signature claims protective) → entire score = 0. Right direction → (significance + magnitude) / 2 where sig = clip(`-log10(p)/4`) and mag = clip(`|log HR|/log 2`). Literature positive controls (cytolytic GZMA/PRF1, IFN-γ, hypoxia HIF targets, proliferation, metastasis_at_dx) tested in the same TARGET-OS data verify the cohort can detect known signal — a null candidate is genuine non-replication, not underpowering | `components_os.score_target_survival_replication` |
| | **Phase 3 subtotal** | **5** | | | |

Phase 3 is OS-only and is the load-bearing answer to "is this a discovery or in-sample optimism?" Run9 episode scores on this component cluster near the random-gene-set null mean — see `docs/TASK_A_COHORT.md` § Signed-correlation diagnostic for the empirical finding.

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
