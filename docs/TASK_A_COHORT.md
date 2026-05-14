# Task A — Cohort-Based Analysis

**Part of:** BioDiscoveryGym → Part 2 (Benchmark)
**Last updated:** 2026-05-14
**Status:** Infrastructure complete. 67-run TCGA benchmark planned (awaiting budget). Osteosarcoma held-out test set in preparation.

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
| **Osteosarcoma** | 1 cohort, ~80 samples, multi-omics | Held-out test — less studied, not in TCGA | Cohort-specific scorer referencing 2023 paper findings |

The osteosarcoma cohort closes the primary confound of the TCGA set: for well-characterized TCGA cancers, canonical recall and genuine discovery produce the same correct output. Osteosarcoma is a rare pediatric bone cancer absent from TCGA and underrepresented in LLM training data — an agent relying on recall will fail here. The scorer will reference subtypes, drivers, and survival correlates reported in the source paper (in preparation; user collecting data).

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

- **G0 (explicit retrieval):** Ceiling baseline. Agent is told "You are analyzing a TCGA BRCA (Breast Invasive Carcinoma) cohort" and has real gene names from call 1. Tests what the model achieves via pure parametric recall.
- **G1 (implicit retrieval):** Agent has real gene names from call 1 but cohort is hidden. Can use gene biology knowledge; must derive grouping from data. Gate=0 means codebook is pre-revealed.
- **G2 (data-driven):** Agent works with GENE_XXXXX for 30 calls (forced blind phase), then receives the codebook. Pure data-driven phase before gene biology access.
- **G3 (mislead):** Agent receives wrong TCGA-style barcodes suggesting a different cancer type. Fake barcodes released at call 30 via `sample_codebook`. Tests robustness of the data-driven analysis against misleading provenance signals.

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
| Mechanism hypothesis quality | 2 | LLM judge |
| Next experiment quality | 2 | LLM judge |
| Submission structure completeness | 2 | Structural check |
| Biological insight (holistic) | 3 | LLM judge |

Run with: `python scripts/score_episode_v2.py --episode results/{id}/episode.json --cohort LIHC`

---

## Key Empirical Findings

### LIHC ep2 (first clean run, 2026-05-05)
- 40 tool calls, ~$3, 7.8 min
- Found **Metabolic (n=159) vs Proliferative (n=59)** — Hoshida S1/S2 vs S3 analogue
- GSEA: Bile Acid Metabolism NES=−4.81, E2F Targets NES=2.58, all FDR<0.001
- Marker genes textbook HCC: CYP3A4/CYP2A6 (differentiated), EPCAM/TOP2A (proliferative)

### Novelty control (2026-05-07)
Same Phase 2 questions sent with no data, only cohort framing (n=371, Metabolic vs Proliferative):
- **~80% of Phase 2 answer content is correct from recall alone**
- No-data answer correctly labeled PC3 as stromal/fibrosis; data-driven agent mislabeled it "proliferation intensity sub-axis" — the agent was **less accurate than the no-data baseline**

### Perturbation battery (2026-05-08, 4 runs)

| Run | Score | Mutation (Stage A) | Survival (Stage A) | Flagged anomaly? |
|-----|-------|-------------------|-------------------|-----------------|
| Baseline s42 | 9.51 | CTNNB1=Hepato, TP53=Prolif (canonical) | Hepato better | No |
| Baseline s43 | 9.45 | Canonical | Canonical | No |
| Perturbed s42 | 6.63 | CTNNB1=Prolif, TP53=Hepato (**inverted**) | NS (weakened) | "Unexpected" only |
| Perturbed s43 | 7.36 | CTNNB1=Progenitor, TP53=Differentiated (**inverted**) | Progenitor better (**inverted**) | "Unexpected" only |

**Motivated data reading:** Agents correctly pre-committed inverted signals in Stage A — they read the data. But neither run flagged a biological anomaly. Instead, both immediately rationalized the inversion as plausible (AFP early detection, TP53-mediated resistance). The agent applies flexible recall to make any result consistent with known biology.

### Mislead experiments (2026-05-06/13, multiple runs)
- **Gate=0 agents: not fooled.** Biological identity established early from gene names; fake barcodes arrive too late to override.
- **Gate=30 agents: fooled in ~4/6 runs.** After 30 calls of abstract structure with no biological anchor, gene names + fake barcodes arrive simultaneously; the named label wins as an interpretation shortcut.

---

## Run Commands

```bash
cd /Users/lpu/myprojects/BioDiscovery
conda activate biodiscoverygym

# G0 — explicit retrieval (ceiling baseline, 1 run per cohort)
python scripts/run_episode.py --cohort BRCA --explicit-retrieval \
  --seed 42 --save-log episode_g0_brca_s42.json

# G1 — implicit retrieval (3 seeds per cohort)
python scripts/run_episode.py --cohort BRCA --gene-codebook-gate 0 \
  --seed 42 --save-log episode_g1_brca_s42.json

# G2 — data-driven (3 seeds per cohort)
python scripts/run_episode.py --cohort BRCA \
  --seed 42 --save-log episode_g2_brca_s42.json

# G3 — mislead (3 seeds per cohort pair)
python scripts/run_episode.py --cohort OV --mislead-cohort BRCA \
  --seed 42 --save-log episode_g4_ov_brca_s42.json

# Score any episode
python scripts/score_episode_v2.py \
  --episode results/{id}/episode_g2_brca_s42.json --cohort BRCA
```

---

## Key Files

| File | Purpose |
|------|---------|
| `biodiscoverygym/episode.py` | `Episode.from_cohort()`, 5-layer anonymization, `--perturb` support |
| `biodiscoverygym/scoring/evaluator_v2.py` | 9-component v2 scorer |
| `biodiscoverygym/scoring/judge.py` | LLM judge (Sonnet) for qualitative components |
| `biodiscoverygym/executor.py` | Stateful Python sandbox with path blocking |
| `agents/claude_agent_anon.py` | `ClaudeAgentAnon` — gene/sample anonymization + codebook gating + explicit-retrieval mode |
| `prompts/agent_anon_system.txt` | 7-stage system prompt template (`{disease_hint}`, `{codebook_preamble}`, etc.) |
| `scripts/run_episode.py` | CLI: `--cohort`, `--explicit-retrieval`, `--gene-codebook-gate`, `--mislead-cohort`, `--seed`, `--save-log` |
| `scripts/score_episode_v2.py` | Post-hoc v2 scoring |
| `scripts/perturb_lihc.py` | Builds survival-inverted + mutation-swapped LIHC data |
| `biodiscoverygym/phases/lihc.py` | Stage A prompt + Phase 2 questions (LIHC-specific) |
| `biodiscoverygym/phases/generic.py` | Generic Phase 2 questions (other cohorts) |

---

## What's Next

**TCGA benchmark:**
1. **Fund and run the 67-episode benchmark** (G0 × 7, G1 × 21, G2 × 21, G3 × 18)
2. **Confirm G3 pairs** — finalize the 6 mislead cohort pairs (OV→BRCA and LUAD→LIHC confirmed; 4 more TBD)
3. **Score all episodes** with `score_episode_v2.py`
4. **Analyze G0 vs G1 vs G2**: does the data-driven phase improve discovery quality, or does gene-name access alone dominate?
5. **Analyze G3**: what fraction of episodes are fooled by mislead barcodes?

**Osteosarcoma held-out test** (pending data):
6. Characterize the processed dataset (modalities, sample N, known subtypes from paper)
7. Write osteosarcoma Phase 2 questions + `CANONICAL_EXPECTATIONS` referencing paper findings
8. Build cohort-specific scorer (parallel to `biodiscoverygym/phases/lihc.py`)
9. Run G0/G1/G2 (G3 not applicable — single cohort); adjust min-samples-per-cluster threshold for N~80
