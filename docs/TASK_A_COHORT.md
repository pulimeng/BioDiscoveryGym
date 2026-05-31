# Task A — Cohort-Based Analysis

**Part of:** BioDiscoveryGym → Part 2 (Benchmark)
**Last updated:** 2026-05-28
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
| Gene names | Real symbols → `GENE_XXXXX` (shuffled with seed); real names revealed via codebook at call 25 (G2) or call 0 (G0/G1) |
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
| **G0** | Explicit retrieval | Call 0 | **Revealed** | 42 | 7 × 1 = 7 | ~$21 |
| **G1** | Implicit retrieval | Call 0 | Hidden | 42, 7, 123 | 7 × 3 = 21 | ~$63 |
| **G2** | Data-driven | Call 25 | Hidden | 42, 7, 123 | 7 × 3 = 21 | ~$63 |
| **G3** | Mislead | Call 25 | Hidden + wrong barcodes | 42, 7, 123 | 6 pairs × 3 = 18 | ~$54 |
| **Total** | | | | | **67** | **~$201** |

### Group definitions

The three groups form a clean ablation over what recall channels are open:

- **G0 (explicit retrieval) — pure recall baseline.** The agent is told the cancer type upfront and receives the gene codebook immediately (call 0). Clinical metadata uses real column names and real categorical values. G0 measures how much a model *already knows* from pretraining.

- **G1 (implicit retrieval) — gene-biology-mediated recall.** Cohort identity is hidden; gene codebook is pre-revealed (call 0). The agent can infer the cancer type from gene signatures (e.g., H3F3A → pediatric bone tumor, SP7 → osteoblast) and recall subtype structure indirectly. Staging values are remapped to CAT_X to prevent Enneking-specific leakage.

- **G2 (data-driven) — data-first discovery.** Genes are anonymized as GENE_XXXXX until call 25; cohort is hidden. The agent must form its grouping from expression patterns, correlations, and clustering before any biological context is available. G1→G2 isolates the effect of gene-biology recall.

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
- Data available to agent: mRNA expression (18,869 genes) + sparse mutation panel (41 genes)
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

# G0 — explicit retrieval
python scripts/run_episode.py --cohort BRCA --explicit-retrieval --seed 42

# G1 — implicit retrieval
python scripts/run_episode.py --cohort BRCA --gene-codebook-gate 0 --seed 42

# G2 — data-driven (default)
python scripts/run_episode.py --cohort BRCA --seed 42

# G2 + PrimeKG (PCST + path-finding for mechanistic reasoning)
python scripts/run_episode.py --cohort BRCA --seed 42 --primekg

# G3 — mislead
python scripts/run_episode.py --cohort OV --mislead-cohort BRCA --seed 42

# Score
python scripts/score_episode_v2.py --episode results/{id}/episode.json --cohort BRCA

# OS multi-seed (9 runs: 3 modes × 3 seeds)
bash scripts/run_os_multiseed.sh
```

---

## Key Files

| File | Purpose |
|------|---------|
| `biodiscoverygym/episode.py` | `Episode.from_cohort()`, 5-layer anonymization, `--perturb` support |
| `biodiscoverygym/scoring/evaluator_v2.py` | 9-component v2 scorer |
| `biodiscoverygym/scoring/judge.py` | LLM judge (Sonnet) — 3-axis mechanism_grounding (coherence + data_grounding + mechanistic_logic) |
| `biodiscoverygym/executor.py` | Stateful Python sandbox for Task A — blocks raw TCGA source files, gene maps, prior results; reference databases (DepMap, GTEx, etc.) are accessible after Stage 5 codebook reveal |
| `biodiscoverygym/tools/pcst.py` | Prize-Collecting Steiner Tree via networkx KMB approximation |
| `biodiscoverygym/tools/opentargets.py` | OpenTargets actionability lookup — `get_actionability()`, `batch_actionability()` |
| `agents/claude_agent_cohort.py` | `ClaudeAgentCohort` — anonymization + codebook gating + PrimeKG pre-reveal + OT at Stage 5 |
| `prompts/agent_g0_system.txt` | G0 system prompt — cohort known, both codebooks pre-revealed, recall+validate framing |
| `prompts/agent_g1_system.txt` | G1 system prompt — cohort hidden, gene codebook pre-revealed, discovery with gene biology |
| `prompts/agent_g2_system.txt` | G2 system prompt — cohort hidden, gene codebook gated at call 25, data-first discovery |
| `scripts/run_episode.py` | CLI: `--cohort`, `--explicit-retrieval`, `--gene-codebook-gate`, `--mislead-cohort`, `--seed`, `--primekg` |
| `scripts/score_episode_v2.py` | Post-hoc v2 scoring |
| `scripts/run_os_multiseed.sh` | Multi-seed OS benchmark runner |
| `scripts/download_primekg.py` | PrimeKG download + split (Harvard Dataverse) |
| `scripts/download_opentargets.py` | OpenTargets download via GraphQL API (no auth) |
| `data/subtypes/pancan_subtypes.tsv` | Reference subtypes — TCGA pancan + 91 OS samples (S-IA/S-IS/S-HRD/S-MD) |

---

## What's Next

**OS run6 (next):**
- Metadata now cleaned: `pathology`, `icluster`, `hrd_score`, `tmb`, `subtype` stripped; `tumor_stage` values remapped to CAT_X in G1/G2; no CLIN_XX column renaming
- Enable Examination stage (Data Lock → Q1-Q4) with Q4 split fix
- Obtain WES/CNA approval (GSA HRA003260) → re-run with full multi-omic data
- Run: `bash scripts/run_cohort.sh --tag run6 --cohort OS`

**TCGA benchmark (future):**
- Fund and run 67-episode benchmark (~$201 on Sonnet)
- Analyze G0 vs G1 vs G2 mode effect; analyze G3 mislead fraction
