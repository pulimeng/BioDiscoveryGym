# BioDiscoveryGym Implementation Plan v2

> Supersedes `IMPLEMENTATION_PLAN_v1.md`.
> Two major shifts from v1:
> (1) Dropped Gym-style RL environment and baseline agents — replaced with Claude tool use.
> (2) Full identity blinding — agent sees no information that reveals cancer type or cohort.

---

## What Changed from v1

### Architecture: Gym → Claude Tool Use

**v1 design:** OpenAI Gym-style environment with step/reset/budget/action registry.
Agents (random, greedy, ML, LLM) all implement `BaseAgent` and operate under a cost budget.

**v2 design:** Two tools only — `run_code` (sandboxed Python execution) and `submit_discovery`.
No predefined action space. Claude decides what analysis to run and how.

| v1 component | v2 status |
|---|---|
| `env.py` (BioDiscoveryGymEnv, step/reset/budget) | Removed |
| `agent_interface.py` (BaseAgent, ACTION_REGISTRY) | Removed |
| `agents/dummy_agent.py` | Removed |
| Baseline agents (random, greedy, ML pipeline) | Removed from critical path |
| `evaluator.py` | Kept — scores DiscoveryPackage |
| `DataLoader`, `HiddenContextBuilder`, sealed slices | Kept |
| Stage scoring (0–6) | Kept |
| `sandbox.py` (network blocker) | Kept — no internet during episodes |

### Baseline Agents

Dropped entirely. Not needed to build or validate the benchmark.
Can be revisited for a paper leaderboard comparison later.

### Multiple LLM Agents

Architecture is model-agnostic in principle, but **Claude is the only target for now**.

---

## Identity Blinding

The agent must not be able to infer the cancer type, cohort, or any clinical grouping.
The following are stripped or anonymized before the agent sees anything:

| What | Why it leaks | How it's handled |
|------|-------------|-----------------|
| `primary_diagnosis`, `tumor_stage`, `morphology` | Directly reveals histology | `DataAnonymizer._ALWAYS_STRIP` |
| TCGA sample barcodes (e.g. `TCGA-BH-A18H`) | TSS code (BH) identifies BRCA | Replaced with `SAMPLE_0001`, `SAMPLE_0002`, ... |
| File paths / dataset names | `data/tcga/brca/` reveals cohort | Never exposed to agent |
| Cohort name in prompt | Tells agent what cancer to expect | Not mentioned — task is framed generically |
| Gene expression profile shape | 1095 samples is a known BRCA number | Minor — not worth obfuscating |

**Sample ID anonymization** happens at episode setup time inside `episode.py`.

### Traceback Record (Evaluator-Only)

Everything needed to fully reconstruct the episode is stored in `data/sealed/{cohort}/episode_key.json`.
This file is **never exposed to the agent** — it exists so the human and evaluator can always
trace back what the data actually was:

```json
{
  "cohort": "BRCA",
  "tcga_project": "TCGA-BRCA",
  "hidden_variable": "primary_diagnosis",
  "label_mapping": {"Context_A": "Infiltrating duct carcinoma, NOS", "Context_B": "Lobular carcinoma, NOS"},
  "sample_id_map": {"SAMPLE_0001": "TCGA-BH-A18H", "SAMPLE_0002": "TCGA-EW-A424", ...},
  "n_public": 751,
  "n_sealed": 187,
  "seed": 42
}
```

This means: if Claude discovers "Group_A has high CDH1 expression", we can immediately look up
that Group_A = Context_B = Lobular carcinoma, and verify the biology makes sense.

---

## Task Framing: Guided Discovery ("New PhD Student with a Specific Aim")

The framing is specific enough that the agent knows what kind of output is expected,
but blind enough that it cannot shortcut to the answer.

The agent is NOT told:
- What cancer type or tissue the data comes from
- That there is a pre-defined hidden variable
- How many groups exist
- Whether the grouping is clinical, molecular, or genetic

The agent IS told:
- It has a bulk RNA-seq gene expression dataset from a human cancer cohort
- The specific aim: identify whether there are distinct molecular subtypes in this cohort,
  characterize the biology of each subtype, and propose a mechanistic hypothesis
- It has access to a Python execution environment and a set of reference biological databases
  (described below) which it can use freely in any way it chooses
- It should submit findings via `submit_discovery` when done

**System prompt (draft):**
> You are a computational biologist. You have been given bulk RNA-seq gene expression data
> from a cohort of cancer patients. Patient identifiers have been anonymized.
>
> Your specific aim:
> 1. Determine whether this cohort contains distinct molecular subtypes.
> 2. If subtypes exist, characterize the biological processes that define each subtype.
> 3. Propose a mechanistic hypothesis explaining what drives the subtype differences.
> 4. Suggest a testable experiment that would validate your hypothesis.
>
> You have a Python environment pre-loaded with the patient dataset and several reference
> databases (cell line omics data, drug response data, pathway gene sets, normal tissue
> expression, cancer gene annotations, and protein interaction networks). Use them however
> you see fit — there are no constraints on your analysis approach.
>
> When you are satisfied with your findings, call `submit_discovery` with your results.

This framing:
- Gives the agent a concrete scientific aim (subtype discovery) without revealing the answer
- Does not hint at how many groups or what the variable is
- Allows "no subtypes found" as a valid outcome (scoreable)
- Treats the agent like a new PhD student with a project aim but no pre-specified hypothesis
- Makes the reference databases feel like a normal scientific toolkit, not a hint

---

## What the Agent Sees

At episode start, the agent receives:

**In the system prompt:**
- Task framing (above)
- Description of available tools (`run_code`, `submit_discovery`)
- Description of pre-loaded variables in the code environment

**Pre-loaded in the code execution namespace:**

*Target dataset (fully blinded):*
```python
expression   # DataFrame — SAMPLE_XXXX × gene_symbol, log1p TPM, protein-coding genes only
metadata     # DataFrame — SAMPLE_XXXX × clinical columns (age, gender, vital_status,
             #             days_to_last_follow_up) — leaky columns already stripped
```

*Reference databases — generic biology and cell line data, full labels intact:*
```python
# Cell line omics (DepMap 23Q4) — use to cross-reference gene function / cancer biology
depmap_expr      # DataFrame — cell_line × gene, log1p TPM expression
depmap_mutation  # DataFrame — cell_line × gene, binary damaging mutation matrix
depmap_cnv       # DataFrame — cell_line × gene, copy number
depmap_crispr    # DataFrame — cell_line × gene, CRISPR KO gene effect scores
depmap_meta      # DataFrame — cell_line metadata (lineage, subtype, etc.) — FULL labels

# Drug response
prism            # DataFrame — cell_line × drug, log fold-change (PRISM secondary screen)
gdsc             # DataFrame — cell_line × drug, IC50 / AUC (GDSC1 + GDSC2)

# Pathway and gene set databases
msigdb           # dict — gene set name → list of gene symbols (Hallmark, KEGG, Reactome, GO)
string_ppi       # DataFrame — gene_a, gene_b, combined_score (STRING v12, score ≥ 700)

# Normal tissue baseline
gtex             # DataFrame — gene_symbol × tissue_name, median TPM (GTEx v8)

# Cancer gene annotations
oncokb           # DataFrame — gene, oncogene/TSG flags, actionability level
dgidb            # DataFrame — gene, drug, interaction type
```

The agent can use the reference databases in any way — cross-reference genes found in the
target dataset against cell line data, look up drug sensitivity of genes of interest,
run pathway enrichment, build PPI subnetworks, compare against normal tissue, etc.

**Filesystem access during code execution:**
- Agent CAN read `data/depmap/`, `data/prism/`, `data/gdsc/`, `data/genesets/`, `data/gtex/`, `data/cancer_genes/` — reference data
- Agent CANNOT access `data/sealed/` — this directory contains mapping files, public/sealed labels, and episode_key.json
- `data/sealed/` is enforced off-limits in the code executor (permission denied or hidden from working directory)
- The agent is never told the path to any file — all data is accessed via pre-loaded namespace variables

**What is NOT in the namespace:**
- Labels of any kind for the target dataset (public or sealed)
- Cancer type, cohort name, or any file paths
- Original TCGA sample barcodes
- Any hint about `data/sealed/` existing

---

## Tools

### `run_code(code: str) → str`
Executes Python in a sandboxed environment. Returns stdout + any printed output.
- All pre-loaded variables are available
- Standard scientific libraries available: pandas, numpy, scipy, sklearn, matplotlib, seaborn, gseapy, statsmodels
- **No internet access** — `sandbox.py` blocks all outbound HTTP except `api.anthropic.com`
- Stateful across calls within one episode (variables persist between `run_code` calls)

### `submit_discovery(discovery: dict) → str`
Claude calls this when done. Accepts a structured DiscoveryPackage:
```json
{
  "proposed_grouping": {"SAMPLE_0001": "Group_A", "SAMPLE_0042": "Group_B", ...},
  "top_genes": ["CDH1", "ESR1", "FOXA1"],
  "pathway_evidence": ["Epithelial-mesenchymal transition", "Estrogen response early"],
  "mechanism_hypothesis": "Free text — what biological process distinguishes the groups",
  "confidence": "high | medium | low",
  "next_experiment": "Free text — what experiment would validate this"
}
```
`proposed_grouping` is required for scoring. All other fields are optional but scored if present.

---

## Agent Prompt

### System Prompt

```
You are a computational biologist. You have been given a bulk RNA-seq gene expression
dataset from a cohort of cancer patients. Patient identifiers and clinical labels have
been anonymized. The cancer type and tissue of origin are not disclosed.

Your goal is to conduct a rigorous molecular discovery analysis on this cohort.
Work through the following stages in order. Each stage requires you to produce
specific outputs before moving to the next.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STAGE 0 — DATA ORIENTATION
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Before any analysis: understand what you are working with.

Produce:
  - Sample count, gene count, data type and units
  - Summary of available clinical/metadata fields and their distributions
  - Basic data quality assessment (missing values, outlier samples, expression range)
  - A short paragraph describing what this dataset appears to be

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STAGE 1 — SIGNAL DISCOVERY
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Find genes and features that carry meaningful biological signal.

Produce:
  - Top variably expressed genes and what drives their variance
  - Any genes whose expression correlates with available clinical variables
  - An assessment of whether the expression data contains structured signal
    (e.g. PCA variance explained, presence of separation in low-dimensional projections)
  - A ranked list of candidate marker genes worth investigating further

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STAGE 2 — SUBTYPE INFERENCE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Determine whether this cohort contains distinct molecular subtypes.

Produce:
  - Your proposed patient grouping: assign every sample to a subtype label
    (e.g. Subtype_A, Subtype_B) or declare no meaningful subtypes found
  - Quantitative evidence for the grouping (silhouette score, separation metrics,
    reproducibility across methods)
  - Genes most differentially expressed between groups (with effect sizes and p-values)
  - A clear statement of your confidence in the grouping

If you find no meaningful subtypes: explain why and what you tried.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STAGE 3 — ANALYSIS PLAN
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Based on what you found in Stages 1 and 2, commit to a direction.

Produce:
  - A working hypothesis: what biological variable do you think underlies the grouping?
  - Your analysis plan: what specific follow-up analyses will you run and why?
  - Which reference databases you will use and how (DepMap, GTEx, MSigDB, etc.)
  - What would change your mind (i.e. what result would lead you to revise the hypothesis)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STAGE 4 — MECHANISTIC INVESTIGATION
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Dig into the biology. Use the reference databases to build and support your mechanism.

Produce:
  - Pathway enrichment results for each subtype (use MSigDB gene sets)
  - Cross-reference your top genes against:
      · GTEx: is differential expression subtype-specific or a normal tissue effect?
      · DepMap: do cell lines with similar expression patterns share a known lineage or
        genetic feature? What happens when these genes are knocked out?
      · OncoKB / DGIdb: are your top genes cancer drivers? Are they druggable?
      · STRING: what interaction network do your top genes form?
  - A mechanistic model: what molecular process distinguishes the subtypes and why?
  - Supporting and contradicting evidence for your model

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STAGE 5 — VALIDATION
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Test robustness of your findings before committing.

Produce:
  - Cross-validation or resampling evidence that your grouping is stable
  - Confirmation that your top genes are specific to the subtype contrast
    and not confounded by technical factors (batch, sequencing depth, gender, age)
  - Whether a simple model trained on your top genes predicts the grouping reliably
  - An honest assessment of the strength and limitations of your evidence

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STAGE 6 — FINAL REPORT & SUBMISSION
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Summarize your findings and submit.

Produce:
  - A concise scientific summary of your discovery (3–5 sentences)
  - Your final mechanistic hypothesis in one clear statement
  - One next experiment that would definitively validate or refute your hypothesis,
    with the model system, perturbation, and expected measurable outcome specified
  - Call submit_discovery with all required fields

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
DATA & TOOLS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Your patient dataset:
  data/episode/expression.parquet  — samples × genes, log1p TPM
  data/episode/metadata.tsv        — anonymized clinical metadata

Reference databases (explore these as you would in a real project):
  data/depmap/     — DepMap 23Q4: cell line expression, mutation, CNV, CRISPR, metadata
  data/prism/      — PRISM drug response (cell lines × drugs)
  data/gdsc/       — GDSC drug response (cell lines × drugs)
  data/genesets/   — MSigDB gene sets (GMT files) and STRING PPI network
  data/gtex/       — GTEx v8 normal tissue expression
  data/cancer_genes/ — OncoKB cancer drivers and DGIdb drug-gene interactions

run_code(code: str) → str
    Execute Python. Libraries available: pandas, numpy, scipy, sklearn, statsmodels,
    matplotlib, seaborn, gseapy, networkx, umap-learn, and more.
    Stateful — variables persist between calls. No internet access.

submit_discovery(
    proposed_grouping: dict,    # {sample_id: "Subtype_A" | ...} — required
    top_genes: list[str],       # your marker genes — required
    pathway_evidence: list[str],# enriched pathways — required
    mechanism_hypothesis: str,  # your mechanistic model — required
    confidence: str,            # "high" | "medium" | "low" — required
    next_experiment: str        # your validation experiment — required
) → str
    Call once when done. Final — cannot be revised after submission.
```

### First User Message (episode kickoff)

```
Begin. Work through each stage in order and show your reasoning as you go.
```

### Design Notes

- The stage structure maps directly to the scoring rubric (Stages 0–6) but the agent
  is not told it is being scored — it is framed as a scientific workflow
- Each stage asks for specific outputs that the evaluator can parse and score
- The agent is free to use `run_code` as many times as needed within each stage
- "No subtypes found" is a valid outcome at Stage 2 — the agent is not forced to invent signal
- The reference databases are described by path, not pre-loaded — agent discovers their
  structure naturally by reading files, consistent with real scientific practice

---

## Comparison to Related Benchmarks

### What others do

**scBench / BAISBench** (closest to ours — single-cell RNA-seq analysis)
```
System: You are a bioinformatics expert.
User:   Given this scRNA-seq dataset: Trachea_raw.h5ad
        Perform basic analysis and annotate cell types.
        Return annotated data in h5ad format.
```
Agent runs code freely, outputs a file. Graded against known ground-truth cell type labels.

**BioML-bench** (end-to-end biomedical ML pipeline)
```
User: Create a model to predict drug response from gene expression.
      Training data: train.csv, Test data: test.csv
      Return predictions as: submission.csv
```
Agent builds an ML pipeline in a Docker container, submits predictions against a leaderboard.

**Shared pattern across all existing benchmarks:**
- Single natural language task description — no stages
- Data provided as a labeled file path
- Agent decides how to get there
- Single metric evaluation (accuracy, AUROC, Spearman)

### How BioDiscoveryGym differs

| | Others | BioDiscoveryGym |
|---|---|---|
| Task | "Annotate these cells" / "Predict this" | Open discovery — agent doesn't know what to find |
| Ground truth | Known to agent (cell types, drug labels) | **Hidden** — agent never sees labels |
| Identity | Data labeled (tissue source in filename) | **Fully blinded** — no cancer type, no barcodes |
| Evaluation | Single metric | 7-dimensional scoring (Stages 0–6) |
| Reference data | None / limited | Full reference databases (DepMap, GTEx, etc.) |

**The key distinction:** every other benchmark tells the agent what it's looking at. We don't.
That is the novel contribution — evaluating open-ended discovery under full identity blinding.

### Why the staged prompt

Other benchmarks use a single natural language task. We use a staged workflow because:
- Without stages, an agent can skip to clustering without building mechanistic evidence,
  making Stage 4 scoring impossible
- Each stage produces specific outputs the evaluator can parse and score independently
- The agent is not told it is being scored — the stages are framed as a scientific workflow,
  not an evaluation rubric

---

## Exact Episode Flow

### What Claude receives

**Turn 1 — System prompt:** *(the full staged prompt from the Agent Prompt section above)*

**Turn 1 — First user message:**
```
Begin. Work through each stage in order and show your reasoning.
```

### What happens next — tool-use loop

```
Claude  →  run_code("import pandas as pd
                     expr = pd.read_parquet('data/episode/expression.parquet')
                     print(expr.shape)")

System  →  "(1095, 19938)"

Claude  →  run_code("expr.var().nlargest(20).to_string()")

System  →  "GATA3    4.21
            CDH1     3.98
            ESR1     3.74
            ..."

Claude  →  run_code("# PCA to check for structure
                     from sklearn.decomposition import PCA
                     pca = PCA(n_components=10)
                     coords = pca.fit_transform(expr)
                     print(pca.explained_variance_ratio_[:5])")

System  →  "[0.142, 0.087, 0.031, 0.024, 0.019]"

...  (Claude continues through all 6 stages)  ...

Claude  →  submit_discovery({
               "proposed_grouping": {"SAMPLE_0001": "Subtype_A",
                                     "SAMPLE_0042": "Subtype_B", ...},
               "top_genes": ["CDH1", "ESR1", "FOXA1", "GATA3"],
               "pathway_evidence": ["Estrogen response early",
                                    "Epithelial-mesenchymal transition"],
               "mechanism_hypothesis": "The two subtypes differ in ...",
               "confidence": "high",
               "next_experiment": "..."
           })

System  →  "Submission received."
```

### After submission — scoring (agent never sees this)

```
Evaluator loads public_labels.json + sealed_labels.json via episode_key.json
↓
Stage 0: parse agent's data description, check it matches actual shape/metadata
Stage 1: check top_genes AUROC against hidden labels
Stage 2: compute ARI/NMI of proposed_grouping vs hidden labels
Stage 3: assess coverage and coherence of analysis plan from conversation log
Stage 4: pathway coherence + semantic similarity of mechanism_hypothesis
Stage 5: re-score proposed_grouping against sealed 20% only
Stage 6: testability and specificity of next_experiment
↓
EpisodeResult: {stage_0: 0.8, stage_1: 0.7, ..., total_score: 0.74}
```

SAMPLE_XXXX IDs in proposed_grouping are re-mapped to real TCGA barcodes
via episode_key.json before scoring.

---

## Phase 1: Core Benchmark

### 1.1 `biodiscoverygym/episode.py`

Orchestrates a single episode. Responsibilities:

1. Load dataset via `DataLoader.load_tcga()`
2. Anonymize via `DataAnonymizer.mask()`
3. Replace sample IDs with `SAMPLE_XXXX`, store mapping
4. Set up code execution namespace with pre-loaded variables
5. Run `ClaudeAgent`
6. Receive `DiscoveryPackage`
7. Re-map `SAMPLE_XXXX` back to real IDs for scoring
8. Pass to `Evaluator`, return `EpisodeResult`

### 1.2 `agents/claude_agent.py`

```python
class ClaudeAgent:
    def __init__(self, model="claude-opus-4-7", max_tool_calls=50):
        ...

    def run(self, system_prompt, namespace, tools) -> DiscoveryPackage:
        # Anthropic SDK tool use loop
        # Claude calls run_code → gets output → reasons → calls more tools
        # Loop ends when Claude calls submit_discovery or hits max_tool_calls
```

### 1.3 Stage Scoring (0–6)

| Stage | What it scores | Key input from DiscoveryPackage |
|-------|---------------|--------------------------------|
| 0 | Data orientation | Did agent describe dataset shape/content correctly? |
| 1 | Signal discovery | AUROC of `top_genes` against hidden labels |
| 2 | Context inference | ARI/NMI of `proposed_grouping` vs hidden labels |
| 3 | Planning | Coherence and coverage of analysis steps taken |
| 4 | Mechanism | Pathway coherence, semantic similarity of `mechanism_hypothesis` to enrichment results |
| 5 | Hidden validation | Does `proposed_grouping` generalize to the sealed 20%? |
| 6 | Report | Testability of `next_experiment`, clarity of hypothesis |

Build order: Stage 1 and 2 first (pure numeric scoring, no NLP), then 0, 3, 6, then 4 last.

### Milestone M1
> Full episode runs end-to-end: Claude explores an anonymized dataset, submits DiscoveryPackage, Evaluator returns Stage 0–6 scores.

---

## Phase 2: Validation & Multi-Cohort

- Run full episodes across all 4 cohorts (BRCA, PRAD, UCEC, LUAD)
- Vary seed, check score stability across 3 seeds
- Negative control: shuffle hidden labels → scores should drop to chance
- Leakage probe: scramble gene names → scores should drop
- Full episode labels for remaining 6 cohorts (cBioPortal annotations — see v1 for details)

### Milestone M2
> Scores across 4 cohorts × 3 seeds, negative controls and leakage probes confirmed.

---

## Phase 3: Release

- Documentation: README, benchmark spec, agent guide
- Public GitHub + Zenodo dataset
- Leaderboard (optional, defer)
- Preprint

---

## File Structure (v2 target)

```
biodiscoverygym/
├── episode.py               # orchestrates a single episode
├── evaluator.py             # scores DiscoveryPackage → EpisodeResult
├── sandbox.py               # ✅ blocks outbound HTTP during code execution
├── scoring/
│   ├── stage0.py … stage6.py
├── utils/
│   ├── data_loader.py       ✅ done
│   ├── hidden_context.py    ✅ done
│   └── metrics.py           ✅ done
agents/
└── claude_agent.py
```

No `tools/` directory — Claude writes its own analysis code via `run_code`.

---

## Build Order

1. `episode.py` — data loading, anonymization, sample ID remapping, namespace setup
2. `run_code` executor — sandboxed Python with pre-loaded namespace
3. `agents/claude_agent.py` — Anthropic SDK tool use loop
4. Run first episode (no scoring yet) — verify Claude can explore data and submit
5. `scoring/stage1.py`, `stage2.py` — numeric scoring against hidden labels
6. `scoring/stage0.py`, `stage3.py`, `stage6.py` — simpler stages
7. `scoring/stage4.py` — semantic similarity, tackle last
8. Iterate on system prompt + scoring until M1 passes

---

## Key Decisions

| Date | Decision |
|------|----------|
| 2026-05-04 | Project moved to `/Users/lpu/myprojects/BioDiscovery` |
| 2026-05-04 | Python 3.11, numpy 2.1, Biomni-aligned deps |
| 2026-05-04 | Simplified TCGA episode labels to binary `primary_diagnosis` for now |
| 2026-05-04 | Dropped Gym-style env — replaced with Claude tool use + `run_code` |
| 2026-05-04 | Dropped baseline agents (random, greedy, ML) from critical path |
| 2026-05-04 | Claude is the only target LLM for now |
| 2026-05-04 | Full identity blinding — cancer type hidden, TCGA barcodes → SAMPLE_XXXX |
| 2026-05-04 | Traceback stored in episode_key.json (evaluator-only) — maps SAMPLE_XXXX back to TCGA IDs and Context_A/B back to real diagnosis strings |
| 2026-05-04 | Task framing: specific aim (subtype discovery) but no hints about cancer type, group count, or variable type |
| 2026-05-04 | All reference datasets (DepMap, PRISM, GDSC, GTEx, MSigDB, STRING, OncoKB, DGIdb) pre-loaded in agent namespace with full labels — only the target dataset is blinded |

---

## How to Resume

```bash
cd /Users/lpu/myprojects/BioDiscovery
conda activate biodiscoverygym
pip install -e ".[llm,bio,dev]"

# All data ready, all tests passing:
pytest tests/test_m0_milestone.py tests/test_tcga_loader.py -v

# Next: implement episode.py
```

---

*Last updated: 2026-05-04*
