<h1 align="center">🧬 BioDiscoveryGym</h1>

<p align="center">
  <b>A benchmark for evaluating LLM agents on open-ended cancer biology discovery.</b><br>
  <i>Does the agent reason from data, or recall from training?</i>
</p>

<p align="center">
  <a href="#-quick-start">Quick start</a> ·
  <a href="#-blinding-strategy">Blinding</a> ·
  <a href="#-scoring">Scoring</a> ·
  <a href="#-setup">Setup</a> ·
  <a href="#-running">Running</a> ·
  <a href="#-repository-layout">Repository</a>
</p>

---

The benchmark probes whether LLM agents can perform **genuine data-driven biological discovery** — or whether they produce correct answers primarily by recalling training knowledge. The core instrument is a multi-group blinding experiment that progressively hides cohort identity, sample provenance, and gene symbols, then watches how the agent's reasoning chain and final submission change.

> [!NOTE]
> The benchmark asks one question of every episode: did the agent derive the known TCGA subtype answer through the data, or recall it?

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

## 🔬 Blinding strategy

Each group dials the same channels (cohort identity, gene symbols, sample barcodes, clinical categoricals) but reveals them at different points in the episode. This is what isolates *data-driven reasoning* from *implicit recall*.

| Group | Cohort name | Gene codebook (real symbols) | Sample IDs → real barcodes | Tests |
|---|---|---|---|---|
| **G0** Explicit retrieval | 🔓 In system prompt | 🔓 Episode start | 🔒 Never revealed | Recall ceiling |
| **G1** Implicit retrieval | 🔒 Redacted | 🔓 Episode start (`gene_codebook_gate=0`) | 🔒 Never revealed | Gene-name-mediated recall |
| **G2** Data-driven blind | 🔒 Redacted | 🎯 **Subtle drop**: appended to the agent's **3rd `record_observation`** (Stage 2 partition-commit) | 🔒 Never revealed | Pure data-driven reasoning |
| **G3** Mislead | 🔒 Redacted | 🎯 Same as G2 | 🎯 **Subtle drop**: appended to the agent's Nth `record_observation` (action-based; default 5th = mid-Stage-3) — returns **wrong-cohort barcodes** (e.g., OV samples labeled BRCA-style). Configurable via `--sample-codebook-ro-gate`: try `3` (early, mimics old "not fooled" regime) vs `5` (late, mimics old "fooled" regime). | Trust data over misleading provenance |

> [!NOTE]
> **Always stripped** (regardless of group): cancer-type metadata columns; subtype/cluster labels (the paper's answer); cohort-fingerprinting categorical values (e.g. AJCC stage `IIB`/`III` → `CAT_0`/`CAT_1`).

<details>
<summary><b>📊 The G1→G2 delta — the load-bearing test</b></summary>
<br>

The only thing that changes between G1 and G2 is *when* the gene codebook arrives:

|  | G1 | G2 |
|---|---|---|
| `gene_codebook_gate` | `0` | `3` |
| Real gene names visible at | First tool call | After 3rd `record_observation` (~call #25–35) |
| Partition derivation | Can use ESR1, GATA3, etc. for clustering | Must derive from `GENE_XXXXX` correlations + clinical structure alone |

If a model performs similarly on G1 and G2, it's reasoning from molecular structure. If G2 degrades sharply, gene-symbol recall was carrying the work.

</details>

<details>
<summary><b>🎭 The G2→G3 delta — mislead resilience</b></summary>
<br>

Same pipeline as G2, plus wrong-cohort barcodes injected at the sample-codebook level. G3 pairs are locked at:

| True cohort | Mislead as | Why this pair |
|---|---|---|
| OV | BRCA | Female-predominant, BRCA1/2-associated overlap |
| LUAD | LIHC | Common adult solid tumors with mid-range mutation burden |

</details>

---

## 🧪 Available modalities per cohort

| Modality | Variable | Format | TCGA |
|---|---|---|:-:|
| Gene expression | `expression` | samples × genes, log2(CPM+1) | ✅ |
| Somatic mutations | `mutation` | samples × genes, binary functional variant | ✅ |
| Copy-number alterations | `cna` | samples × genes, GISTIC focal calls (+1 amp / −1 del / 0 neutral) | ✅ |
| DNA methylation | `methylation` | samples × CpG probes, beta values | varies |
| Protein expression (RPPA) | `rppa` | samples × proteins, z-scores | ✅ |
| Clinical metadata | `metadata` | survival, stage, age, gender (categoricals → `CAT_X` for non-G0) | ✅ |

> [!TIP]
> The agent must check for `None` and adapt — not every modality is present everywhere.

---

## 📊 Scoring

### Faithfulness rubric

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

---

## ▶️ Running

### Single episode

```bash
# G2 default — blind, data-driven, codebook gated on 3rd record_observation
python scripts/run_episode.py --cohort BRCA --seed 42 --save-log results/ep.json

# G0 ceiling — disease + gene names revealed
python scripts/run_episode.py --cohort BRCA --seed 42 --explicit-retrieval

# G1 — gene names revealed, disease redacted
python scripts/run_episode.py --cohort BRCA --seed 42 --gene-codebook-gate 0

# G3 — mislead with wrong-cohort barcodes
python scripts/run_episode.py --cohort OV --mislead-cohort BRCA --seed 42
```

### Multi-seed benchmarks

```bash
bash scripts/run_tcga.sh --smoke-test              # 1×1×4 groups at 100 calls, scored      (~$12, ~1 hr)
bash scripts/run_tcga.sh --tag run10               # full 40 episodes + scoring             (~$120)
```

> [!TIP]
> Runners are **resume-safe** — they check for `<label>.json` in the output directory and skip already-completed episodes. To re-run a tag from scratch: `rm -rf` its output directory first.

### Post-hoc scoring

```bash
# Faithfulness rubric (16 pts)
python scripts/score_tcga_episode.py results/tcga/<run>/<uuid>/<label>.json --cohort BRCA --save

# Batch-score a whole run
bash scripts/score_all_tcga.sh results/tcga/<run>/

# Skip LLM judges (no API cost, partial score)
python scripts/score_tcga_episode.py <...>.json --skip-llm
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
    components.py           — computational scorers
    judge.py                — LLM judges
    evaluator_v2.py         — TCGA Phase 1 orchestrator (16 pts)
    evaluator_v3.py         — TCGA + trace extraction + (legacy) Phase 2 attachment
  utils/
    data_loader.py          — loads TCGA datasets
    hidden_context.py       — manages blinding: what the agent can and cannot see

prompts/
  agent_system_tcga.txt     — TCGA faithfulness prompt
  COHORT_REFERENCE_CARDS.md — per-cohort fact-check card injected into the support judge
  examination/              — Phase 2 examination question sets (legacy)
  archive/                  — superseded prompts

scripts/
  run_episode.py            — single-episode CLI
  run_tcga.sh               — TCGA multi-seed runner (G0/G1/G2/G3 × seeds × cohorts)
  process_tcga.py           — preprocess TCGA cohorts
  score_tcga_episode.py     — single-episode TCGA scorer
  score_all_tcga.sh         — batch TCGA scoring
  modality_attribution.py   — post-hoc: which modalities did the agent use?
  archive/                  — abandoned Task B + experimental scorers

analysis/                   — (gitignored) one-off analysis scripts + outputs
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
