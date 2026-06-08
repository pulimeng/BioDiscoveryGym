# Task A — Cohort-Based Analysis

**Part of:** BioDiscoveryGym → Part 2 (Benchmark)
**Last updated:** 2026-06-01
**Status:** Infrastructure complete. OS 9-run benchmark complete. TCGA 67-run benchmark planned (awaiting budget).

---

## What This Task Tests

Given an anonymized patient cohort (expression ± mutations ± RPPA), can an LLM:
1. Discover real molecular subtypes without being told the cancer type or number of groups?
2. Characterize the biology of each subtype with evidence?
3. Remain consistent with its own data-derived findings when canonical recall is available as a shortcut?

The central challenge: for well-studied cancer types, recall and discovery produce the same correct outcome. We measure the reasoning **process**, not just the answer.

> For well-studied cancer types, LLM agents produce correct biological conclusions not by reasoning from data, but by retrieving training knowledge and selectively fitting numbers to predetermined conclusions. Correct outcomes cannot distinguish the two.

---

## Identity Blinding

Six layers prevent the agent from knowing what it is looking at:

| Layer | What is stripped/replaced |
|-------|--------------------------|
| `DataAnonymizer._ALWAYS_STRIP` | Cancer-type columns (`primary_diagnosis`, `OncotreePrimaryDisease`, lineage, subtype) |
| Molecular clustering labels | **Stripped entirely** — precomputed cluster assignments (e.g. `mrna_cluster`) are the paper's answer, not independent data. Keeping them gives the agent the partition for free. |
| Staging values | Categorical values that fingerprint a cohort (e.g. Enneking `IIB`/`III` for OS) are remapped to `CAT_0`, `CAT_1`, … in-place — column name kept, values anonymized. Skipped in G0 mode (cohort already known). |
| Demographics | `race`, `ethnicity` stripped (cohort identity leakage — e.g. LIHC is >50% Asian from HBV-endemic regions). `gender` kept — generic across all cancers. |
| Sample IDs | TCGA barcodes → `SAMPLE_XXXX` (shuffled with seed) |
| Gene names | Real symbols → `GENE_XXXXX` (shuffled with seed, union of expression+mutation columns); codebook auto-injected into the 8th `run_code` result (G2) or at episode start (G0/G1) — no tool call required |
| Data path | Served from neutral `data/episode/` path, not `data/tcga/lihc/` |

**Kept intentionally:** Survival columns (`vital_status`, `days_to_death`, `days_to_last_follow_up`), `tumor_stage`, `metastasis`, `age_at_diagnosis`, `gender` — all generic pan-cancer clinical variables the agent can legitimately use as phenotypic anchors.

**Rule:** Strip anything that directly names the cancer type, paper subtype labels, or pre-computed assay scores whose presence fingerprints a non-TCGA dataset (`hrd_score`, `tmb`, `icluster`, `pathology` are all stripped for OS). Remap categorical values that are staging-system-specific (Enneking `IIB`/`III` → `CAT_0`/`CAT_1`) while keeping the column name visible.

---

## Tools

Two tools: `run_code` (stateful Python sandbox) + `submit_discovery`. No predefined action space.

The agent works through 7 stages (0–6): data orientation → signal discovery → subtype inference → analysis plan → statistical deep-dive → biological annotation → final report.

---

## Benchmark Structure

Task A has two test sets:

| Set | Cohorts | Role | Scorer |
|-----|---------|------|--------|
| **TCGA** | BRCA, PRAD, UCEC, LUAD, LIHC, LUSC, OV | Main 67-run experiment | v2 scorer vs. TCGA pancan subtypes |
| **Osteosarcoma** | SGH-OS, 91 samples | Held-out test — rare pediatric cancer, absent from TCGA | v2 scorer + OS-specific reference subtypes |

The osteosarcoma cohort closes the primary confound of the TCGA set: for well-characterized TCGA cancers, canonical recall and genuine discovery produce the same correct output. Osteosarcoma is a rare pediatric bone cancer absent from TCGA and underrepresented in LLM training data — an agent relying on recall will fail here.

---

## TCGA Experiment Design

**67 runs total across 4 groups. 7 cohorts: BRCA, PRAD, UCEC, LUAD, LIHC, LUSC, OV.**

| Group | Label | Gene codebook | Cohort name | Seeds | Runs | Cost (~$3/ep) |
|-------|-------|---------------|-------------|-------|------|---------------|
| **G0** | Explicit retrieval | Episode start | **Revealed** | 42 | 7 × 1 = 7 | ~$21 |
| **G1** | Implicit retrieval | Episode start | Hidden | 42, 7, 123 | 7 × 3 = 21 | ~$63 |
| **G2** | Data-driven | run_code #8 | Hidden | 42, 7, 123 | 7 × 3 = 21 | ~$63 |
| **G3** | Mislead | run_code #8 | Hidden + wrong barcodes | 42, 7, 123 | 6 pairs × 3 = 18 | ~$54 |
| **Total** | | | | | **67** | **~$201** |

### Group definitions

The three groups form a clean ablation over what recall channels are open:

- **G0 (explicit retrieval) — pure recall baseline.** The agent is told the cancer type upfront and receives the gene codebook immediately (call 0). Clinical metadata uses real column names and real categorical values. G0 measures how much a model *already knows* from pretraining.

- **G1 (implicit retrieval) — gene-biology-mediated recall.** Cohort identity is hidden; gene codebook is pre-revealed (call 0). The agent can infer the cancer type from gene signatures (e.g., H3F3A → pediatric bone tumor, SP7 → osteoblast) and recall subtype structure indirectly. Staging values are remapped to CAT_X to prevent Enneking-specific leakage.

- **G2 (data-driven) — data-first discovery.** Genes are anonymized as GENE_XXXXX until the 8th `run_code` call; cohort is hidden. The codebook is auto-injected into that run_code result — no tool call needed. The agent must form its grouping from expression patterns, correlations, and clustering before any biological context is available. G1→G2 isolates the effect of gene-biology recall.

- **G3 (mislead):** Same as G2, but sample barcodes suggest the wrong cancer type. Tests whether the agent correctly overrides misleading provenance signals with data evidence.

**What differs between G0 and G1:** cohort identity in the system prompt and clinical value remapping (G0 sees real staging values; G1/G2 see CAT_X). The G1→G2 delta is a clean single-variable test: gene codebook timing (call 0 vs call 25).

### G3 cohort pairs

| True cohort | Mislead as |
|-------------|-----------|
| OV | BRCA |
| LUAD | LIHC |
| (4 more TBD) | |

---

## Scoring (v3, post-hoc)

All scoring is post-hoc — agent is not told how it is scored. Two tracks: Phase 1 (always present) and Phase 2 (only when Phase 2 Q&A was enabled during the run).

### Phase 1 — 9 components, 18 points maximum

| Component | Weight | Method |
|-----------|-------:|--------|
| `structure_validity` | 2 | Bootstrap silhouette + ARI vs k-means re-cluster |
| `clinical_signal` | 3 | ΔC-index over null Cox + log HR between extreme-survival subtypes |
| `genomic_coherence_drivers` | 2 | FDR-corrected Fisher's exact for OncoKB drivers per subtype |
| `genomic_coherence_rppa` | 2 | ARI between expression grouping and RPPA k-means re-cluster |
| `reference_concordance` | 2 | Max NMI across all available TCGA / OS subtype schemes |
| `marker_evidence` | 2 | HGNC validity + one-vs-rest AUC + OncoKB overlap |
| `pathway_validity` | 1 | GMT name validity + ORA enrichment bonus |
| `mechanism_grounding` | 2 | LLM judge — 3 axes: internal coherence, data grounding, mechanistic logic |
| `experiment_quality` | 2 | LLM judge — 4 binary criteria: specific model, perturbation, measurement, quantitative outcome |

### Phase 2 — 3 components, 5 points maximum (requires `--phase2` during run)

| Component | Weight | Method |
|-----------|-------:|--------|
| `p2_commit_quality` | 1 | Regex coverage of 5 required commit-phase sections (PC loadings, survival, mutation, RPPA, unexpected finding) |
| `p2_experiment_depth` | 2 | LLM judge on Q4 — 4 sub-parts each 0/1: model+dataset evidence, perturbation+direction, readout+magnitude, falsification criterion |
| `p2_mechanistic_integration` | 2 | LLM judge on all Q1-Q4 — 3 axes: cross-modal consistency (4 modalities woven into one causal chain), quantitative grounding (committed numbers cited), causal coherence (directed chain vs. associations) |

Phase 1 and Phase 2 are normalized separately (each 0–1) so Phase 1-only and Phase 1+Phase 2 runs are directly comparable.

Run with: `bash scripts/score_all_withMeth.sh <results_dir>` or `python scripts/score_episode_v3.py <episode.json> --cohort OS --save`

### Mechanism hypothesis judge (3 axes, /12 raw → 0–1 normalized)

| Axis | Max | Evaluates |
|------|----:|-----------|
| `internal_coherence` | 4 | Hypothesis logically follows from submitted genes and pathways |
| `data_grounding` | 4 | Claims are anchored to data-derived findings, not literature recall |
| `mechanistic_logic` | 4 | Explicit directional causal chain with named molecular actors at each step |

Score 4 on `mechanistic_logic` requires direction at every step and named molecular actors (ligand, receptor, effector, downstream target). Stating pathway names without tracing the logic scores 0–1.

---

## Osteosarcoma Benchmark — Completed (2026-05-15/19)

### Cohort

**SGH-OS** — Jia et al. 2022, *Nat Commun*. 91 patients, Shanghai General Hospital.
- Data available to agent: mRNA expression (18,869 genes) + methylation + sparse mutation panel (41 genes, all now anonymized to GENE_XXXXX — see bug fix below)
- Paper used: mRNA + CNA + DNA methylation (iCluster integrative)
- Tag: `_noCNA_noSNV` — full WES somatic calls and CNA pending controlled-access approval (GSA HRA003260)

### Published subtypes (ground truth)

| Subtype | n | Key biology | Prognosis | Target |
|---------|---|-------------|-----------|--------|
| S-IA | 25 | Immune activated; CD8/T-cell high; VEGFA; IFN-γ/α | Best | ICI + anti-VEGF |
| S-IS | 22 | Immune suppressed/exhausted; TGF-β; CDR3-depleted | Poor | ICI + anti-VEGF |
| S-HRD | 23 | HRD dominant; BRCA2 del; ~80% HRD+; platinum-sensitive | Intermediate | PARPi + cisplatin |
| S-MD | 21 | MYC amp; OXPHOS; chemo-resistant; immune-cold | Worst | anti-MYC |

### Results (9 runs: G0/G1/G2 × seeds 0/1/7)

Achievable max = **15 / 18 points** — `genomic_coherence_drivers` (2 pts) and `genomic_coherence_rppa` (1 pt) are structural zeros without CNA/WES/RPPA.

| Group | Mean total (/15) | Normalized | SD |
|-------|----------------:|-----------|-----|
| G0 — explicit retrieval | 7.93 | 0.529 | 0.23 |
| G1 — implicit retrieval | 7.59 | 0.506 | 0.40 |
| G2 — data-driven        | 7.69 | 0.513 | 0.06 |

### Key observations (run3 — clinical columns not yet anonymized)

**Partition stability:** All 9 runs converge to a 4-cluster solution with sizes 25/25/21/20 (paper: 25/22/23/21). Structural, survival, and reference-concordance scores are byte-identical across runs — later found to be caused by agents reading the `mrna_cluster` column directly, not by genuine clustering.

**Consistent marker recovery:** Top markers appearing in ≥7/9 runs — `SP7, DLX3, S100A9, HMOX1, ALPL, FCGR3A, VWF, SELP, ACKR1, IFITM5, BAMBI, CXCL12, SYNPO2`. Four reproducible biological axes: osteoblastic-differentiated, immune-myeloid, stromal/endothelial, proliferative/undifferentiated.

**What the agents miss (information-gap misses, not failures):**
- MYC amplification → S-MD (CNA-defined; agents see OXPHOS/G2M signature but cannot name amplification)
- HRD as a distinct subtype (requires CNA/methylation)
- S-IA vs S-IS split (requires deeper immune deconvolution)

**No mode effect (run3):** G0–G1–G2 differences (≤0.35 pts) are smaller than G1 seed-to-seed variability. This was an artifact — `mrna_cluster` in the metadata gave all modes the paper's partition for free.

### Key observations (run4 — clinical anonymization + observation tracking)

**Partition stability splits by mode** once `mrna_cluster` is renamed (but not yet removed): G2 3/3 canonical, G1 2/3, G0 0/3. G0 collapses to 3-cluster solutions across all seeds when it cannot read an interpretable cluster label. Confirmed that prior run3 "mode-invariant" convergence was clinical-column anchoring, not data-driven clustering.

**SP7/cg15311685 finding replicates 3/3 in G2** under clinical anonymization. In the best run (b9c508c8), the methylation-expression correlation (r ≈ −0.75, p ≈ 1e-17) was identified before the agent knew the cohort identity or gene names — the cleanest data-driven discovery in the benchmark to date.

**Observation tracking** reveals hypothesis evolution for the first time: confidence trajectories, alternatives considered, quantitative findings cited before codebook reveal.

Full report: `results/cohort/external/run4_clinAnon_obsTrack/`

### Bug findings (run6 — unified prompt + examination phase)

Three structural bugs identified from run6 traces, all fixed before run7:

1. **H3F3A anonymization leak** — `_anonymize_gene_ids` built the rename map from expression columns only; mutation-only genes passed through as real symbols. H3F3A appeared in G2's mutation matrix, immediately identified by the agent and used to infer osteosarcoma. Fixed: rename map now covers the union of expression + mutation columns; assertion added.

2. **G2 codebook never injected** — Trigger was `_ro_count >= 5`; agents call `record_observation` 1–2 times in practice, never reaching the threshold. G2 submitted with 19/20 GENE_XXXXX placeholders. Fixed: trigger moved to `_run_code_count >= 8` in the `run_code` handler — deterministic, RO-compliance-independent.

3. **`data/external` unblocked** — Raw source files (`data/external/os_jia2022/expression.parquet` etc.) were readable from agent code, completely bypassing anonymization. Fixed: added `"data/external"` to `_BLOCKED_SUBSTRINGS`.

Full report: `results/cohort/external/os_benchmark_summary.md`

---

## Key Empirical Findings

### LIHC ep2 (2026-05-05)
- 40 tool calls, ~$3, 7.8 min
- Found Metabolic (n=159) vs Proliferative (n=59) — Hoshida S1/S2 vs S3 analogue
- GSEA: Bile Acid Metabolism NES=−4.81, E2F Targets NES=2.58, all FDR<0.001
- Marker genes textbook HCC: CYP3A4/CYP2A6 (differentiated), EPCAM/TOP2A (proliferative)

### Novelty control (2026-05-07)
Same Phase 2 questions sent with no data, only cohort framing (n=371, Metabolic vs Proliferative):
- **~80% of Phase 2 answer content is correct from recall alone**
- No-data answer correctly labeled PC3 as stromal/fibrosis; data-driven agent mislabeled it "proliferation intensity sub-axis" — **less accurate than the no-data baseline**

### Perturbation battery (2026-05-08, 4 runs)

| Run | Score | Mutation (Stage A) | Survival (Stage A) | Flagged anomaly? |
|-----|-------|-------------------|-------------------|-----------------|
| Baseline s42 | 9.51 | CTNNB1=Hepato, TP53=Prolif (canonical) | Hepato better | No |
| Baseline s43 | 9.45 | Canonical | Canonical | No |
| Perturbed s42 | 6.63 | CTNNB1=Prolif, TP53=Hepato (**inverted**) | NS | "Unexpected" only |
| Perturbed s43 | 7.36 | CTNNB1=Progenitor, TP53=Differentiated (**inverted**) | Progenitor better (**inverted**) | "Unexpected" only |

**Motivated data reading:** Agents correctly pre-committed inverted signals in Stage A — they read the data. But neither run flagged a biological anomaly; both rationalized the inversion as plausible.

### Mislead experiments (2026-05-06/13)
- **Gate=0 agents: not fooled.** Biological identity established early from gene names; fake barcodes arrive too late to override.
- **Gate=30 agents: fooled in ~4/6 runs.** After 30 abstract calls, gene names + fake barcodes arrive simultaneously; the label wins as an interpretation shortcut.

---

## Run Commands

```bash
cd /Users/lpu/myprojects/BioDiscovery
conda activate biodiscoverygym

# Smoke test — runs G0/G1/G2 once each (seed=42, 15 calls, no exam) → results/external/dry-run/
bash scripts/run_cohort.sh --smoke-test --cohort OS

# Full OS benchmark run (3 modes × 3 seeds)
bash scripts/run_cohort.sh --tag run7_unified --cohort OS

# Single episodes
python scripts/run_episode.py --cohort OS --explicit-retrieval --seed 42           # G0
python scripts/run_episode.py --cohort OS --gene-codebook-gate 0 --seed 42         # G1
python scripts/run_episode.py --cohort OS --seed 42                                 # G2 (codebook at run_code #8)
python scripts/run_episode.py --cohort OV --mislead-cohort BRCA --seed 42           # G3
python scripts/run_episode.py --cohort OS --seed 42 --primekg                       # G2 + PrimeKG

# Score
python scripts/score_episode_v3.py results/external/run7_unified/<uuid>/<label>.json --cohort OS --save
bash scripts/score_all_withMeth.sh results/external/run7_unified/
```

---

## Key Files

| File | Purpose |
|------|---------|
| `biodiscoverygym/episode.py` | `Episode.from_cohort()`, 6-layer anonymization (expression+mutation union), `--perturb` support |
| `biodiscoverygym/scoring/evaluator_v3.py` | 9-component v3 scorer |
| `biodiscoverygym/scoring/judge.py` | LLM judge (Sonnet) — 3-axis mechanism_grounding (coherence + data_grounding + mechanistic_logic) |
| `biodiscoverygym/executor.py` | Stateful Python sandbox — blocks `data/tcga`, `data/external`, `data/subtypes`, gene maps, prior results; genesets blocked pre-codebook |
| `biodiscoverygym/tools/multimodal.py` | `multimodal_cluster()` — MOFA+/SNF/concat_pca, pre-loaded in namespace |
| `biodiscoverygym/tools/pcst.py` | Prize-Collecting Steiner Tree via networkx KMB approximation |
| `biodiscoverygym/tools/opentargets.py` | OpenTargets actionability lookup — `get_actionability()`, `batch_actionability()` |
| `agents/claude_agent_cohort.py` | `ClaudeAgentCohort` — G0/G1/G2 unified; codebook auto-injected (episode start for G0/G1, run_code #8 for G2) |
| `prompts/agent_system.txt` | Unified system prompt for all modes (G0/G1/G2) — 5 format vars |
| `scripts/run_episode.py` | CLI: `--cohort`, `--explicit-retrieval`, `--gene-codebook-gate` (default 8), `--mislead-cohort`, `--seed`, `--primekg` |
| `scripts/run_cohort.sh` | Multi-seed benchmark runner: `--tag`, `--cohort`, `--g0/g1/g2-seeds`, `--smoke-test` |
| `scripts/score_episode_v3.py` | Post-hoc v3 scoring |
| `scripts/score_all_withMeth.sh` | Batch scorer for all episodes in a results directory |
| `scripts/download_primekg.py` | PrimeKG download + split (Harvard Dataverse) |
| `scripts/download_opentargets.py` | OpenTargets download via GraphQL API (no auth) |
| `data/subtypes/pancan_subtypes.tsv` | Reference subtypes — TCGA pancan + 91 OS samples (S-IA/S-IS/S-HRD/S-MD) |

---

---

## Prompt Design Rationale: Why OS Needs a Separate Prompt

**Last updated:** 2026-06-08

### The TCGA prompt's implicit goal

The current `agent_system.txt` (now copied to `agent_system_tcga.txt`) is designed as a **subtype-recovery benchmark**. Its implicit contract with the agent is:

> "There is a known correct partition of these patients. Find it from data, characterize the biology, and explain the mechanism."

The evaluation machinery (NMI vs. TCGA pancan subtypes, OncoKB driver enrichment, reference concordance) all assume a ground truth exists and is recoverable. The G0/G1/G2 blinding ladder tests whether the agent needs prior knowledge to recover it, not whether it discovers anything new.

This works for TCGA because the task is well-posed: BRCA has PAM50 subtypes, LUAD has LUSC/adenocarcinoma biology, LIHC has Hoshida S1/S2/S3. The "right answer" is known and the agent's job is to arrive at it from data alone.

### Why the same prompt fails for OS as a discovery task

**Run8 findings exposed a structural problem.** Across all 13 episodes (G0/G1/G2 × seeds 0/1/7/42/123), agents converged on SP7/RUNX2/ALPL as the top marker genes. The convergence is not surprising: SP7/Osterix is the master transcription factor of osteoblastic differentiation and will always be the top differentially expressed gene in the dominant cluster of any OS expression dataset.

This means agents are not discovering — they are **confirming well-known biology from training memory**. The TCGA prompt actively enables this: it rewards complete mechanistic narratives, which agents produce fluently by assembling known OS biology (RUNX2 amplification, BMP signaling, SP7 cascade) into a story dressed with real p-values.

**Post-analysis of run8 (`analysis/run8/7a240cea_markers.py`) showed the pattern clearly:**

- The grouping is real: C0_Proliferative has HR=4.01, p=0.004 — agents find a genuine survival-stratifying partition
- The marker is real: SP7 is differentially expressed in C1_Osteoblastic
- The mechanism is prior-driven: claimed CpG sites (cg00674456, cg05906075) have HR~1.05, p~0.8 — not prognostically relevant. The agent found a real methylation-expression correlation (r=−0.67, genuine), then constructed a causal chain around it using training knowledge about promoter methylation and osteoblast TF cascades. The data didn't derive the mechanism — the prior did, and the data didn't contradict it.

The pattern is: **real cluster → real marker → prior-driven mechanism**. The LLM's training prior on OS biology is strong enough to produce a plausible, internally consistent mechanistic narrative that the data doesn't specifically contradict — it only needs to avoid contradiction, not be derived from the data. The BMP7→RUNX2→SP7 cascade is real biology; the CpG-methylation-expression relationship is valid; the pathways are correct. None of it is invented — it is training knowledge filling in mechanistic gaps that the data was never asked to fill. The TCGA prompt's scoring rewards narrative completeness and does not strongly penalize prior-driven reasoning (mechanism_grounding `data_grounding` axis is weak relative to structure and clinical signal scores).

**Survival is the right validation target, but it validates the partition — not the mechanism.** Agents in run8 find genuinely survival-stratifying groupings (C0_Proliferative HR=4.01, p=0.004), which is a real finding — actually stronger than the paper's own iCluster partition (only iC4 significant at p=0.011 univariate). Survival works as a signal for partition quality. What it cannot validate is the specific mechanistic story layered on top: the CpGs the agent cites as causal (cg00674456, cg05906075) have HR~1.05, p~0.8 — cherry-picked for correlation with SP7 expression, not prognostically relevant. At n=91 with ~37 events, power is sufficient to detect strong partition effects (HR>2–3, best vs. worst cluster) but insufficient to discriminate between 3–4 subtypes with intermediate prognosis differences or to test individual mechanistic claims.

### The two different tasks

| | TCGA benchmark | OS discovery probe |
|---|---|---|
| **Goal** | Recover known subtypes from data | Find something the field doesn't already know |
| **Ground truth** | TCGA pancan subtypes (well-defined) | Paper's iCluster (weak survival signal at n=91) |
| **Dominant confound** | Prior knowledge retrieval vs. data-driven reasoning | Confirmation of known biology vs. genuine novelty |
| **What success looks like** | High NMI vs. reference, correct driver enrichment | A finding that cannot be produced from training memory alone |
| **Failure mode** | Agent uses gene names to shortcut data analysis | Agent finds SP7, LLM prior fills in the mechanism; data does no causal work |
| **Phase 2 validation** | Cross-modal consistency, quantitative grounding | Survival validates partition quality; cannot validate specific mechanistic claims |

### Why agents get stuck on SP7

SP7 is genuinely the most variable gene in the OS dataset AND it is the gene the OS prior is most certain about. Data and prior agree simultaneously — there is no friction. But the deeper problem is not that the agent needs a contradiction to keep looking. The problem is that finding SP7 feels *sufficient*. The prior doesn't just confirm SP7 is correct — it signals that SP7 is complete. The narrative fills in immediately, the mechanism is known, the submission fields can be populated. The agent has no reason to look further down the variance list because it already has a satisfying answer.

A scientist with domain expertise would do the opposite: finding SP7 is a check-mark, not a discovery. It's too well-studied to be interesting. The real question is what's at position 15 or 30 that shouldn't be there — why is PRAME elevated in one cluster, why are ribosomal proteins upregulated in the worst-prognosis group. A scientist uses the well-known result as a reference point and looks for deviations from it. The prior's certainty about SP7 is a reason to look past it, not a reason to stop.

The agent lacks this meta-incentive. It doesn't reason about whether a finding is publishable or novel — it reasons about whether it is correct and biologically coherent. SP7 scores maximum on both. The prior knows SP7 is well-studied but the current prompt never asks the agent to apply that meta-knowledge to its search strategy.

The implicit stopping criterion in the current prompt is: *stop when you have a satisfying mechanistic narrative*. For OS, that criterion is satisfied at SP7. The OS prompt needs a different stopping criterion: *stop when you find something the prior would not have predicted without the data*. Well-studied genes are background, not because they are wrong, but because they are expected and therefore uninformative about what this specific dataset contributes beyond what was already known.

The TCGA prompt's Stage 1 instruction — "find top variably expressed genes" — directly engineers this failure mode for OS. For this specific dataset, the top-variance entry point leads immediately to the gene the prior is most certain about, and the prior's certainty provides immediate closure. The interesting OS biology (immune subtypes, HRD, MYC amplification) lives in secondary variance axes that SP7 absorbs when it dominates PC1. The paper found those axes by integrating CNA and methylation specifically to surface structure beyond the differentiation gradient.

### What the OS prompt needs to do differently

The OS-specific prompt (`prompts/agent_system_os.txt`, to be written) should:

1. **Acknowledge the dominant axis and explicitly instruct the agent to set it aside.** The single most important instruction change: "The osteoblast differentiation axis — SP7, RUNX2, ALPL — is the dominant source of variance in this dataset and is well-characterized in the literature. Confirm it is present, then set it aside. Your task is to find what structure exists in this cohort that is NOT explained by the differentiation gradient. Regress it out if necessary." This breaks the SP7 feedback loop by redefining it as background rather than signal.

2. **Separate marker-finding from mechanism-building.** Force the agent to commit to what is a marker vs. what is causal, and to distinguish correlation from direction.

3. **Require pre-registered predictions before survival analysis.** Before running any survival curve, the agent must state which cluster it predicts will have worst prognosis and why, based only on expression patterns. This creates an auditable record of whether the conclusion was data-driven or post-hoc.

4. **Make the prior-vs-data distinction auditable.** The agent should explicitly state, for each mechanistic claim, whether it is derived from data in this dataset or from prior biological knowledge. Training-knowledge claims are not invalid — they are often correct — but they need to be labeled as such so the benchmark can measure how much work the data is doing vs. how much the prior is doing.

5. **Focus on within-dataset novelty, not literature concordance.** The TCGA prompt asks for pathway names and network context — both of which reward literature-recall fluency. The OS prompt should ask: "What does this specific dataset show that a generic OS textbook entry would not predict?"

### The prior-data leverage problem and what discovery actually means

This is the central epistemological challenge for LLM-assisted scientific discovery — not specific to this benchmark.

In traditional data analysis, there is a clean separation: the analyst's domain knowledge frames the question, the data answers it. The prior informs *what to look for*; the data does the *inferential work*. These two contributions are separable by design.

With an LLM agent, the separation collapses. The prior is not just framing the question — it is generating the answer, and the data is used to support a conclusion the prior already reached. The agent observes that SP7 is high in cluster 1 and immediately the full BMP7→RUNX2→SP7→ALPL cascade activates from training memory, because that is what the OS literature says should happen when SP7 is high. The data confirmed the prior's prediction, so the prior fills in everything the data did not directly measure. The output looks data-driven because it contains real statistics, but the data was decorative — the inference was already made before the numbers arrived.

The leverage problem scales with how well-studied the biology is. For a rare disease or a novel perturbation, the prior has no precise prediction to make, so the data is forced to do real inferential work. For a well-characterized cancer like OS, the prior is so informative that it can generate a multi-step causal chain — named molecular actors, directionalities, effect sizes, a proposed experiment — all biologically plausible and mostly correct at the pathway level, without the data contributing anything beyond a cluster label.

The novelty control experiment (2026-05-07, LIHC) made this concrete: ~80% of Phase 2 answer content was correct from recall alone with no data. The agent with data was *less accurate* on one sub-question than the no-data baseline. This is not a failure of the agent — it is the prior doing its job. The problem is that from the output alone, you cannot tell which 20% the data contributed.

**What discovery means in this context.** The goal is not to find completely unknown biology — that is an unreasonable expectation from bulk RNA-seq and methylation data in a published cohort. The target is more specific and more realistic: *something real in the data that the original paper did not notice, characterize, or prioritize*, because the original analysis had a fixed analytical scope, a specific story to tell, and limited capacity to explore all directions simultaneously.

The agent's genuine advantage is the combination of **broader prior** (synthesizes more literature than any single research team, aware of findings across cancer types and modalities, knows candidate mechanisms outside the paper's focal hypothesis) and **data processing capacity** (runs 50+ analyses in one session, integrates multiple modalities flexibly, tests many more hypotheses without publication pressure or narrative commitment). Applied together to an already-published dataset, this can surface findings that are real, data-supported, and not in the original paper — not because the biology was unknown, but because the original analysis didn't look there.

For OS this could be: a subgroup within one of the paper's iCluster partitions with a distinct survival profile the coarser clustering absorbed; a CTA expression signature specific to the worst-prognosis cluster that the paper characterized by immune features alone; a convergence of mutation and CNA in the same gene within one subtype that appears as two-hit somatic evidence; a methylation pattern the paper captured statistically in iCluster but never interpreted mechanistically at the gene level.

None of that is unknown biology — it is all interpretable with existing knowledge. But it is not in Jia 2022. The prior tells you what the finding *could mean*; the data tells you whether it is *actually there*.

This reframes the prior as an asset rather than a confound. The prior is necessary: you need it to know what is already in the paper (so the agent does not "discover" it again) and to interpret what the data shows (so the agent can recognize significance). The problem arises only when the prior *substitutes* for data analysis rather than *extending* it — when the agent constructs a mechanism from training knowledge and uses the data only to avoid contradiction, rather than to derive the claim.

**Implication for benchmark design:** Measuring whether an LLM agent produces the right answer is insufficient. For well-studied domains, the prior will produce the right answer regardless of whether the data supports it. A rigorous benchmark must measure how much inferential work the data is doing — ideally by testing whether the agent's conclusions change when the data changes (perturbation experiments, inverted survival signals, swapped cohort identities). The G0/G1/G2 blinding ladder and the G3 mislead condition are both attempts to probe this.

**Implication for scientific credibility:** Any LLM-generated hypothesis should be evaluated against what the prior alone would predict. A finding that is consistent with the prior and does not require the data is not a discovery — it is a prior-confirmation. A finding that required the data to produce (the prior alone would not have pointed here, or would have pointed elsewhere) is the meaningful output of the system.

### Expected behavioral differences across G0 / G1 / G2

Under the prior-data leverage framework, the three modes should produce not just different scores but fundamentally different reasoning patterns — different CoT structure, different hypothesis-formation timing, and different partition derivation. These are testable predictions that the CoT extraction tool (`scripts/extract_cot.py`) can evaluate.

**G0 — Explicit retrieval.** Prior activates at call 1. The agent knows the cancer type and has real gene names from the start. Data analysis is confirmatory: the agent is looking for SP7/RUNX2/ALPL because the OS prior says that is what to look for. The partition may be data-derived but the hypothesis is selected from prior knowledge before the data is examined.

Expected CoT signature:
- Hypothesis stated confidently within the first 2–3 calls
- Hypothesis minimally updated across the run — high confidence throughout
- Mechanism fully specified early, data used to populate numbers into a pre-formed narrative
- Stage transitions rapid; little exploratory detour

**G1 — Implicit retrieval.** Prior activates at call 2–3 via gene-biology inference. The agent does not know the cancer type but receives real gene names immediately. SP7 appears in the top-variance list; the agent recognizes it as the osteoblast master TF and infers pediatric bone cancer. From that point behavior converges toward G0 — the same prior is now active, just activated 2–3 calls later.

Expected CoT signature:
- Brief exploratory phase (calls 1–3) with no disease commitment
- Rapid hypothesis convergence once SP7 or H3F3A is identified (calls 3–5)
- Post-inference CoT indistinguishable from G0
- Pediatric/age-narrowing signal may appear before explicit disease naming (`pediatric_at` call in index)

**G2 — Data-driven.** Prior is blocked for 7 calls — genes are opaque GENE_XXXXX labels. The agent must reason from expression variance patterns, survival correlations, clustering geometry, and clinical variable distributions. At call 8 the codebook is injected; the prior activates immediately and the mechanism fills in. The partition should be shaped by the data; the mechanism is constructed post-codebook.

Expected CoT signature:
- Calls 1–7: genuine pattern-driven reasoning — cluster labels, survival correlations, variance structure — without any biological vocabulary
- Sharp transition at call 8–9: biological gene names appear for the first time, disease is named within 2 calls of codebook reveal
- Partition committed before call 8 should be stable or only fine-tuned post-codebook (if the partition is rebuilt post-codebook to match the prior, the blinding is ineffective)
- Mechanism assembled post-codebook, not derived from calls 1–7

**The key testable distinction between G1 and G2** is not the mechanism (both converge to the same prior-driven narrative) but whether the *partition* was shaped by the blind data phase. G2's 7-call blind period is only meaningful if the cluster structure it produces is carried forward rather than discarded when the codebook arrives.

**What run8 shows.** All 13 episodes (G0/G1/G2) converge on SP7 as the top marker gene. All G2 episodes name the disease at approximately call 11 — two calls after codebook reveal at call 9 — confirming the prior activates at codebook injection and overwhelms whatever was building in the blind phase. One G2 episode (`a9e7083e`, seed=7) shows pediatric/age-narrowing at call 6 — three calls *before* codebook reveal — indicating the prior leaked through clinical metadata (age distribution ~27 years, consistent with AYA bone cancer).

The run8 data does not yet confirm whether the G2 partition is genuinely data-driven or rebuilt post-codebook. This requires comparing the cluster assignments at call 7 (pre-codebook) vs. the final submitted grouping. That analysis is pending.

---

### What this means for the benchmark

The OS cohort should be repositioned: it is not a held-out test of subtype recovery (where the "correct" answer is the paper's iCluster partition), but a **prognostic and predictive biomarker discovery task** — can the agent identify molecular features that predict patient outcome in this specific cohort beyond what is already reported in the OS literature?

This framing directly addresses the SP7 problem. SP7 is expressed in all osteosarcomas because they are all osteoblastic tumors by definition — it is a histological identity marker, not a biomarker. A biomarker must vary meaningfully across patients and that variation must predict something clinically relevant. The task is to find features that do this and that the original paper did not report as primary findings.

The scoring for OS runs will need its own rubric — one that rewards survival-anchored findings, clinical measurability, and novelty relative to the published literature, over narrative completeness and pathway enumeration.

---

## What's Next

**OS run7 (next):**
- All three bugs from run6 fixed: H3F3A leak, G2 codebook trigger, `data/external` block
- Unified prompt (`agent_system.txt`), multimodal_cluster tool, HR+CI in survival
- Smoke test first: `bash scripts/run_cohort.sh --smoke-test --cohort OS`
- Full run: `bash scripts/run_cohort.sh --tag run7_unified --cohort OS`

**Pending:**
- Obtain WES/CNA approval (GSA HRA003260) → re-run with full multi-omic data
- Stage 3/4 retrofit guard (hold off — revisit if run7 still shows retconning)

**TCGA benchmark (future):**
- Fund and run 67-episode benchmark (~$201 on Sonnet)
- Analyze G0 vs G1 vs G2 mode effect; analyze G3 mislead fraction
