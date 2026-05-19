# Task A — Cohort-Based Analysis

**Part of:** BioDiscoveryGym → Part 2 (Benchmark)
**Last updated:** 2026-05-19
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

Five layers prevent the agent from knowing what it is looking at:

| Layer | What is stripped/replaced |
|-------|--------------------------|
| `DataAnonymizer._ALWAYS_STRIP` | Cancer-type clinical columns (`primary_diagnosis`, `OncotreePrimaryDisease`, lineage, subtype) |
| Demographics | `gender`, `race`, `ethnicity` (cohort identity leakage — e.g. LIHC is >50% Asian from HBV-endemic regions) |
| Sample IDs | TCGA barcodes → `SAMPLE_XXXX` (shuffled with seed) |
| Gene names | Real symbols → `GENE_XXXXX` (shuffled with seed); real names revealed via codebook |
| Data path | Served from neutral `data/episode/` path, not `data/tcga/lihc/` |

Survival columns (`vital_status`, `days_to_death`) are intentionally kept — they're needed for biological reasoning, not identity.

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

| Group | Label | Gene names | Cohort name | Gate | Seeds | Runs | Cost (~$3/ep) |
|-------|-------|------------|-------------|------|-------|------|---------------|
| **G0** | Explicit retrieval | Real (forced) | **Revealed** | 0 | 42 | 7 × 1 = 7 | ~$21 |
| **G1** | Implicit retrieval | Real | Hidden | 0 | 42, 7, 123 | 7 × 3 = 21 | ~$63 |
| **G2** | Data-driven | GENE_XXXXX → real at call 30 | Hidden | 30 | 42, 7, 123 | 7 × 3 = 21 | ~$63 |
| **G3** | Mislead | GENE_XXXXX → real at call 30 | Hidden + wrong barcodes | 30 | 42, 7, 123 | 6 pairs × 3 = 18 | ~$54 |
| **Total** | | | | | | **67** | **~$201** |

### Group definitions

- **G0 (explicit retrieval):** Ceiling baseline. Agent is told "You are analyzing a TCGA BRCA (Breast Invasive Carcinoma) cohort" and has real gene names from call 1.
- **G1 (implicit retrieval):** Agent has real gene names from call 1 but cohort is hidden.
- **G2 (data-driven):** Agent works with GENE_XXXXX for 30 calls, then receives the codebook. Pure data-driven phase before gene biology access.
- **G3 (mislead):** Agent receives wrong TCGA-style barcodes suggesting a different cancer type. Fake barcodes released at call 30. Tests robustness against misleading provenance signals.

### G3 cohort pairs

| True cohort | Mislead as |
|-------------|-----------|
| OV | BRCA |
| LUAD | LIHC |
| (4 more TBD) | |

---

## Scoring (v2, post-hoc)

9 components, 18 points maximum. All scoring is post-hoc — agent is not told how it is scored.

| Component | Points | Method |
|-----------|--------|--------|
| Grouping quality (NMI vs TCGA subtypes) | 2 | Numeric |
| Survival separation | 2 | Log-rank p-value |
| Marker discriminability (AUROC) | 2 | Per-gene ROC |
| Coverage (fraction of samples assigned) | 1 | Numeric |
| Pathway evidence quality | 2 | LLM judge |
| Mechanism hypothesis quality | 3 | LLM judge — 3 axes (see below) |
| Next experiment quality | 2 | LLM judge |
| Submission structure completeness | 2 | Structural check |
| Biological insight (holistic) | 2 | LLM judge |

Run with: `python scripts/score_episode_v2.py --episode results/{id}/episode.json --cohort BRCA`

### Mechanism hypothesis judge (3 axes, /12 raw → 0–1 normalized)

The `mechanism_grounding` judge evaluates each cluster's mechanistic hypothesis on three axes:

| Axis | Max | Evaluates |
|------|----:|-----------|
| `internal_coherence` | 4 | Are all claims mutually consistent? |
| `data_grounding` | 4 | Are claims anchored to data-derived findings (expression, survival, pathway p-values)? |
| `mechanistic_logic` | 4 | Is an explicit directional causal chain traced? (A activates B → B phosphorylates C → C drives phenotype) |

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

### Key observations

**Partition stability:** All 9 runs converge to a 4-cluster solution with sizes 25/25/21/20 (paper: 25/22/23/21). Structural, survival, and reference-concordance scores are byte-identical across runs. Variation between runs lives entirely in qualitative outputs.

**Consistent marker recovery:** Top markers appearing in ≥7/9 runs — `SP7, DLX3, S100A9, HMOX1, ALPL, FCGR3A, VWF, SELP, ACKR1, IFITM5, BAMBI, CXCL12, SYNPO2`. These trace four reproducible biological axes (osteoblastic-differentiated, immune-myeloid, stromal/endothelial, proliferative/undifferentiated).

**What the agents miss (information-gap misses, not failures):**
- MYC amplification → S-MD (CNA-defined; agents see OXPHOS/G2M signature but cannot name amplification)
- HRD as a distinct subtype (requires CNA/methylation)
- S-IA vs S-IS split (requires deeper immune deconvolution)

**No mode effect:** G0–G1–G2 differences (≤0.35 pts) are smaller than G1 seed-to-seed variability (~1 pt). The seed-42 (stale) result that G1 > G0 does not replicate at multiple seeds.

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
| `biodiscoverygym/executor.py` | Stateful Python sandbox with path blocking |
| `biodiscoverygym/tools/pcst.py` | Prize-Collecting Steiner Tree via networkx KMB approximation |
| `biodiscoverygym/tools/opentargets.py` | OpenTargets actionability lookup — `get_actionability()`, `batch_actionability()` |
| `agents/claude_agent_anon.py` | `ClaudeAgentAnon` — anonymization + codebook gating + PrimeKG pre-reveal + OT at Stage 5 |
| `prompts/agent_anon_system.txt` | 7-stage system prompt template |
| `scripts/run_episode.py` | CLI: `--cohort`, `--explicit-retrieval`, `--gene-codebook-gate`, `--mislead-cohort`, `--seed`, `--primekg` |
| `scripts/score_episode_v2.py` | Post-hoc v2 scoring |
| `scripts/run_os_multiseed.sh` | Multi-seed OS benchmark runner |
| `scripts/download_primekg.py` | PrimeKG download + split (Harvard Dataverse) |
| `scripts/download_opentargets.py` | OpenTargets download via GraphQL API (no auth) |
| `data/subtypes/pancan_subtypes.tsv` | Reference subtypes — TCGA pancan + 91 OS samples (S-IA/S-IS/S-HRD/S-MD) |

---

## What's Next

**OS (held-out test):**
1. Obtain WES/CNA approval (GSA HRA003260) → re-run without `_noCNA_noSNV` tag
2. Write OS-specific `CANONICAL_EXPECTATIONS` referencing paper (S-HRD/S-MD biology)
3. Test `--primekg` effect on OS mechanistic_logic scores (2 matched episodes)

**TCGA benchmark:**
4. Fund and run 67-episode benchmark (~$201 on Sonnet)
5. Analyze G0 vs G1 vs G2 mode effect; analyze G3 mislead fraction
6. Score all episodes with v2 scorer (mechanistic_logic axis)
