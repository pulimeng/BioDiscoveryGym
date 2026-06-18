<h1 align="center">🧬 BioDiscoveryGym</h1>

<p align="center">
  <b>A benchmark for evaluating LLM agents on open-ended cancer biology discovery.</b><br>
  <i>Does the agent reason from data, or recall from training?</i>
</p>

<p align="center">
  <a href="#-quick-start">Quick start</a> ·
  <a href="#-two-experiments">Experiments</a> ·
  <a href="#-blinding-strategy">Blinding</a> ·
  <a href="#-scoring">Scoring</a> ·
  <a href="#-setup">Setup</a> ·
  <a href="#-running">Running</a> ·
  <a href="#-repository-layout">Repository</a>
</p>

---

The benchmark probes whether LLM agents can perform **genuine data-driven biological discovery** — or whether they produce correct answers primarily by recalling training knowledge. The core instrument is a multi-group blinding experiment that progressively hides cohort identity, sample provenance, and gene symbols, then watches how the agent's reasoning chain and final submission change.

> [!NOTE]
> The benchmark runs **two parallel experiments** that share infrastructure but answer different questions:
> - **TCGA** — *faithfulness*: did the agent derive a known answer through data, or recall it?
> - **SGH-OS** — *discovery*: did the agent find a biomarker that generalizes to a held-out cohort?

---

## ⚡ Quick start

```bash
git clone https://github.com/pulimeng/BioDiscoveryGym.git
cd BioDiscoveryGym
conda env create -f environment.yaml && conda activate biodiscoverygym
pip install -e .
export ANTHROPIC_API_KEY="sk-..."

# Smoke test (TCGA): 1 cohort × 4 groups × 100 calls, scored, ~$12, ~1 hr
bash scripts/run_tcga.sh --smoke-test
```

---

## 🎯 Two experiments

|  | **TCGA experiment** | **SGH-OS experiment** |
|---|---|---|
| **Scoring intent** | Faithfulness — did the agent recover the known TCGA subtype answer via data-driven reasoning rather than literature recall? | Discovery — did the agent find prognostic biomarkers in n=91 SGH-OS that generalize to TARGET-OS, beyond what Jia et al. 2022 reports? |
| **Reference answer exists** | ✅ TCGA pancan subtype calls | ❌ The paper's marker list is the literature baseline to *go past* |
| **External validation cohort** | None | TARGET-OS (n=85 with survival) — Phase 3 |
| **Cohorts** | BRCA, LIHC, LUAD, OV (4; data for 7 downloaded) | SGH-OS only |
| **Groups** | G0 / G1 / G2 / G3 | G0 / G1 / G2 (no G3 — single cohort) |
| **Scoring ceiling** | **16 pts** (Phase 1 only) | **24 pts** (Phase 1 + 2 + 3) |

---

## 🔬 Blinding strategy

Each group dials the same channels (cohort identity, gene symbols, sample barcodes, clinical categoricals) but reveals them at different points in the episode. This is what isolates *data-driven reasoning* from *implicit recall*.

| Group | Cohort name | Gene codebook (real symbols) | Sample IDs → real barcodes | Tests |
|---|---|---|---|---|
| **G0** Explicit retrieval | 🔓 In system prompt | 🔓 Episode start | 🔒 Never revealed | Recall ceiling |
| **G1** Implicit retrieval | 🔒 Redacted | 🔓 Episode start (`gene_codebook_gate=0`) | 🔒 Never revealed | Gene-name-mediated recall |
| **G2** Data-driven blind | 🔒 Redacted | 🎯 **Subtle drop**: appended to the agent's **3rd `record_observation`** (Stage 2 partition-commit) | 🔒 Never revealed | Pure data-driven reasoning |
| **G3** Mislead *(TCGA only)* | 🔒 Redacted | 🎯 Same as G2 | 🎯 **Subtle drop**: appended to the agent's Nth `record_observation` (action-based; default 5th = mid-Stage-3) — returns **wrong-cohort barcodes** (e.g., OV samples labeled BRCA-style). Configurable via `--sample-codebook-ro-gate`: try `3` (early, mimics old "not fooled" regime) vs `5` (late, mimics old "fooled" regime). | Trust data over misleading provenance |

> [!NOTE]
> **Always stripped** (regardless of group): cancer-type metadata columns; subtype/cluster labels (the paper's answer); cohort-fingerprinting categorical values (e.g. Enneking stage `IIB`/`III` → `CAT_0`/`CAT_1`).

<details>
<summary><b>📊 The G1→G2 delta — the load-bearing test</b></summary>
<br>

The only thing that changes between G1 and G2 is *when* the gene codebook arrives:

|  | G1 | G2 |
|---|---|---|
| `gene_codebook_gate` | `0` | `3` |
| Real gene names visible at | First tool call | After 3rd `record_observation` (~call #25–35) |
| Partition derivation | Can use SP7, RUNX2, etc. for clustering | Must derive from `GENE_XXXXX` correlations + clinical structure alone |

If a model performs similarly on G1 and G2, it's reasoning from molecular structure. If G2 degrades sharply, gene-symbol recall was carrying the work.

</details>

<details>
<summary><b>🎭 The G2→G3 delta — mislead resilience (TCGA only)</b></summary>
<br>

Same pipeline as G2, plus wrong-cohort barcodes injected at the sample-codebook level. G3 pairs are locked at:

| True cohort | Mislead as | Why this pair |
|---|---|---|
| OV | BRCA | Female-predominant, BRCA1/2-associated overlap |
| LUAD | LIHC | Common adult solid tumors with mid-range mutation burden |

</details>

---

## 🧪 Available modalities per cohort

| Modality | Variable | Format | TCGA | SGH-OS |
|---|---|---|:-:|:-:|
| Gene expression | `expression` | samples × genes, log2(CPM+1) | ✅ | ✅ 18,869 genes |
| Somatic mutations | `mutation` | samples × genes, binary functional variant | ✅ | ✅ 3,779 genes (sparse panel) |
| Copy-number alterations | `cna` | samples × genes, GISTIC focal calls (+1 amp / −1 del / 0 neutral) | ✅ | ✅ 1,618 genes |
| DNA methylation | `methylation` | samples × CpG probes, beta values | varies | ✅ 10,000 most-variable CpGs |
| Protein expression (RPPA) | `rppa` | samples × proteins, z-scores | ✅ | ❌ |
| Clinical metadata | `metadata` | survival, stage, age, gender (categoricals → `CAT_X` for non-G0) | ✅ | ✅ |

> [!TIP]
> The agent must check for `None` and adapt — not every modality is present everywhere.

---

## 📊 Scoring

### TCGA — faithfulness rubric

<p align="center"><b>16 pts</b> · Phase 1 only · 8 components · 7 computational + 1 LLM judge</p>

| # | Component | Wt | Type | What it measures | Implementation |
|---|---|---:|---|---|---|
| 1 | `structure_validity` | 2 | comp | Partition is well-formed: bootstrap silhouette + ARI vs k-means re-cluster on PCA-reduced expression (50 dims) | `components.score_structure_validity` |
| 2 | `clinical_signal` | 3 | comp | Subtypes stratify survival: ΔC-index over null Cox (60%) + log HR between extreme groups (40%) | `components.score_clinical_signal` |
| 3 | `genomic_coherence_drivers` | 2 | comp | OncoKB drivers enrich per subtype via FDR-corrected Fisher exact | `components.score_driver_enrichment` |
| 4 | `genomic_coherence_rppa` | 2 | comp | Expression grouping coherent with protein structure: ARI vs RPPA k-means re-cluster | `components.score_rppa_concordance` |
| 5 | `reference_concordance` | 2 | comp | 🎯 **Faithfulness anchor** — max NMI across known TCGA subtype schemes | `components.score_reference_concordance` |
| 6 | `marker_evidence` | 2 | comp | 40% HGNC validity + 40% one-vs-rest AUC + 20% OncoKB driver overlap | `components.score_marker_evidence` |
| 7 | `pathway_validity` | 1 | comp | GMT name validity (MSigDB / Reactome / GO / KEGG) + ORA enrichment bonus | `components.score_pathway_validity` |
| 8 | `mechanism_grounding` | 2 | 🤖 LLM | 3 axes /4 each: internal coherence, **data grounding** (faithfulness signal), mechanistic logic | `judge.score_mechanism_grounding` |

> [!NOTE]
> **14 of 16 pts are deterministic** (free to score). Only `mechanism_grounding` (2 pts) uses an LLM judge — specifically because its **data_grounding axis** is what distinguishes data-derivation from literature recall.

> [!TIP]
> Examination phase removed 2026-06-15 — the Phase 1 components already cover the faithfulness signal. Runner passes `--no-examination` automatically.

---

### SGH-OS — discovery rubric

<p align="center"><b>24 pts</b> · Phase 1 + 2 + 3 · 11 components total</p>

#### Phase 1 — structural + computational (16 pts, 7 components)

| # | Component | Wt | Type | What it measures | Implementation |
|---|---|---:|---|---|---|
| 1 | `structure_validity` | 2 | comp | Same as TCGA — silhouette + bootstrap ARI | `components.score_structure_validity` *(shared)* |
| 2 | `survival_stratification` | 3 | comp | Multi-group log-rank p scaled `-log10(p)/4` (1.5) + Cox max-vs-min HR scaled `log(HR)/log(4)` (1.5) | `components_os.score_survival_stratification` |
| 3 | `provenance_integrity` | 3 | comp | Per-gene independent re-audit of the prompt's 2-of-3 test: DE FDR<0.05 BH **+** survival ρ FDR<0.05 BH **+** methylation OR CNA. Score = fraction passing ≥2 of 3 | `components_os.score_provenance_integrity` |
| 4 | `pathway_validity` | 1 | comp | Same as TCGA — direction-neutral GMT + ORA | `components.score_pathway_validity` *(shared)* |
| 5 | `mechanistic_grounding` | 3 | 🤖 LLM | OS-specific 3 axes /4 each: prior/data discipline, causal chain from data, discovery beyond priors | `judge_os.score_mechanism_grounding_os` |
| 6 | `cross_modal_support` | 2 | comp | Per gene: RNA evidence (DE OR survival, p<0.05) **AND** non-RNA evidence (methylation OR CNA) | `components_os.score_cross_modal_support` |
| 7 | `validation_experiment` | 2 | 🤖 LLM | 4 binary criteria: specific model + perturbation + measurement + quantitative outcome | `judge.score_experiment_quality` |

#### Phase 2 — post-submission Examination (3 pts, 2 components)

Triggered after `submit_discovery`. Agent commits a Data Lock report then answers Q1–Q4.

| # | Component | Wt | Type | What it measures | Implementation |
|---|---|---:|---|---|---|
| 8 | `exam_data_lock_quality` | 1 | comp (regex) | Data Lock has 5 required sections: PC loadings + survival + mutation + methylation/RPPA + unexpected finding | `components.score_exam_data_lock_quality` *(shared)* |
| 9 | `exam_mechanistic_integration` | 2 | 🤖 LLM | OS-specific 3 axes /4 each: Data Lock numeric citation (≥6 values), multi-modal integration (≥3 modalities → 1 causal chain), [PRIOR]/[DATA] discipline | `judge_os.score_exam_mechanistic_integration_os` |

#### Phase 3 — external validation in TARGET-OS (5 pts, 2 components)

Hands the submitted gene set to TARGET-OS (n=85, independent pediatric/AYA osteosarcoma) and lets the data decide.

| # | Component | Wt | Type | What it measures | Implementation |
|---|---|---:|---|---|---|
| 10 | `target_coexpr_replication` | 2 | comp | Three subscores averaged: (a) `os_specificity_delta` = matrix ρ to TARGET-OS minus TARGET-non-OS, (b) sign concordance, (c) leave-one-out signature direction match | `components_os.score_target_coexpr_replication` |
| 11 | `target_survival_replication` | 3 | comp | **Direction-as-gate**: wrong-direction HR → 0. Right direction → (significance + magnitude)/2. Built-in positive controls verify cohort can detect signal | `components_os.score_target_survival_replication` |

> [!IMPORTANT]
> Phase 3 is the load-bearing empirical answer to *"is this a discovery or in-sample optimism?"* — and the only component that hands the agent's submission to an independent cohort. See `docs/TASK_A_COHORT.md` § Signed-correlation diagnostic for the empirical finding (run9 episodes cluster near the random-gene-set null mean on this component).

---

### Null-baseline calibration *(SGH-OS only)*

```bash
python scripts/calibrate_os_null.py --n-iter 100 --seed 42
```

Runs the scorer on 100 random gene sets to establish per-component chance floors. Two modes (random partition / fixed partition × random gene set) decompose signal from partition quality vs gene-set quality. Saved to `data/calibration/os_null_baseline_*.json`.

---

## 🛠️ Setup

```bash
conda env create -f environment.yaml
conda activate biodiscoverygym
pip install -e .
export ANTHROPIC_API_KEY="sk-..."
```

<details>
<summary><b>TCGA cohort data</b></summary>
<br>

```bash
python scripts/download_tcga.py    # BRCA, PRAD, UCEC, LUAD, LIHC, LUSC, OV
python scripts/process_tcga.py     # builds expression.parquet caches
```

</details>

<details>
<summary><b>SGH-OS cohort data (Jia et al. 2022)</b></summary>
<br>

Raw data from GSA accession HRA003260. After downloading:

```bash
python scripts/process_os_jia2022.py \
    --raw-dir data/external/os_jia2022/raw \
    --out-dir data/external/os_jia2022 \
    --min-vaf 0.05
```

Produces:
- `expression.parquet` — 91 × 18,869 genes
- `mutations.parquet` — 91 × 3,779 genes
- `cna.parquet` — 91 × 1,618 genes
- `methylation.parquet` — 91 × 10,000 CpGs
- `OS_clinical.tsv`

</details>

<details>
<summary><b>TARGET-OS (for SGH-OS Phase 3 validation)</b></summary>
<br>

```bash
python scripts/process_target.py   # processes TARGET pan-cancer; OS arm = 88 samples, 85 with survival
```

</details>

---

## ▶️ Running

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
bash scripts/run_tcga.sh --smoke-test              # 1×1×4 groups at 100 calls, scored      (~$12, ~1 hr)
bash scripts/run_tcga.sh --tag run10               # full 40 episodes + scoring             (~$120)

# === SGH-OS ===
bash scripts/run_cohort.sh --smoke-test --cohort OS    # 1 seed/mode × 15 calls, no scoring (~$1)
bash scripts/run_cohort.sh --tag run10 --cohort OS     # full G0/G1/G2 × 3 seeds = 9        (~$30)
```

> [!TIP]
> Runners are **resume-safe** — they check for `<label>.json` in the output directory and skip already-completed episodes. To re-run a tag from scratch: `rm -rf` its output directory first.

### Post-hoc scoring

```bash
# SGH-OS — discovery rubric (24 pts)
python scripts/score_sghos_episode.py results/external/<run>/<uuid>/<label>.json --save

# TCGA — faithfulness rubric (16 pts)
python scripts/score_tcga_episode.py results/tcga/<run>/<uuid>/<label>.json --cohort BRCA --save

# Batch-score a whole run
bash scripts/score_all_sghos.sh results/external/<run>/
bash scripts/score_all_tcga.sh results/tcga/<run>/

# Skip LLM judges (no API cost, partial score)
python scripts/score_sghos_episode.py <...>.json --skip-llm
```

> [!WARNING]
> The scoring scripts **fail-fast** if `ANTHROPIC_API_KEY` is missing (LLM-judge components otherwise silently zero). Pass `--skip-llm` for explicit opt-out.

---

## 📁 Repository layout

```
biodiscoverygym/
  episode.py                — episode lifecycle: anonymization, data write, phase transitions
  executor.py               — sandboxed code execution, injects data into agent namespace
  scoring/
    components.py           — TCGA + shared computational scorers
    components_os.py        — OS-specific computational scorers
    judge.py                — TCGA LLM judges
    judge_os.py             — OS LLM judges
    evaluator_v2.py         — TCGA Phase 1 orchestrator (16 pts)
    evaluator_v3.py         — TCGA + trace extraction + (legacy) Phase 2 attachment
    evaluator_os.py         — OS discovery scorer (Phase 1 + 2 + 3 = 24 pts)
  utils/
    data_loader.py          — loads TCGA / external (SGH-OS, TARGET) datasets
    hidden_context.py       — manages blinding: what the agent can and cannot see

prompts/
  agent_system_tcga.txt     — TCGA faithfulness prompt
  agent_system_os.txt       — OS discovery prompt (Stage 0–5 with multi-modal scaffolding)
  examination/              — Phase 2 examination question sets (OS only)
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

docs/
  GRAND_DESIGN.md           — three-part architecture (Skills Library + Benchmark + Evaluator)
  TASK_A_COHORT.md          — full task design, scoring system, empirical findings
  BENCHMARK_PLAN.md         — running notes on benchmark cohort + group choices
```

---

## 🧪 Tests

```bash
pytest tests/ -v
```

---

<p align="center">
  <sub>BioDiscoveryGym · A benchmark for whether AI can actually do science, or just look like it can.</sub>
</p>
