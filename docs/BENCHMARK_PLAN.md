# BioDiscoveryGym — Task A Benchmark Plan

**Last updated:** 2026-05-14
**Status:** Ready to run. Awaiting budget approval.

---

## Goal

Evaluate whether frontier LLMs can perform genuine data-driven biological discovery, or whether correct answers are produced primarily by parametric recall of training knowledge. We measure this by varying how much identity information is leaked to the agent (G0→G3) and by comparing performance across model families.

**Primary research questions:**
1. Does the data-driven blind phase (G2) improve discovery quality over pure recall (G0)?
2. Are agents robust to misleading provenance signals (G3)?
3. Do model families differ in data-following vs. recall-relying behavior?
4. Does performance on the held-out osteosarcoma cohort (no TCGA contamination) diverge from TCGA performance?

---

## Method

### Protocol

Each episode: agent receives an anonymized patient cohort (expression ± mutations ± RPPA), discovers molecular subtypes, and submits a structured report. No ground truth labels are given. No scoring criteria are revealed.

**Identity blinding (5 layers):** cancer-type columns stripped, demographics removed, sample IDs → `SAMPLE_XXXX`, gene symbols → `GENE_XXXXX`, data served from neutral path.

**4 experimental groups (40 runs, TCGA set; G3 splits into G3a + G3b sub-arms):**

| Group | Label | Gene names | Cohort name | Gate | Seeds | Runs |
|-------|-------|------------|-------------|------|-------|------|
| G0 | Explicit retrieval | Real (forced) | **Revealed** | episode start | 42 | 4 |
| G1 | Implicit retrieval | Real | Hidden | episode start | 42, 7, 123 | 12 |
| G2 | Data-driven | GENE_XXXXX → real at 3rd `record_observation` | Hidden | action-based | 42, 7, 123 | 12 |
| G3a | Mislead, early drop | GENE_XXXXX → real at 3rd `record_observation` | Hidden + fake barcodes (OV:BRCA, LUAD:LIHC) subtly dropped at **3rd RO** alongside gene codebook | action-based | 42, 7, 123 | 6 |
| G3b | Mislead, late drop | GENE_XXXXX → real at 3rd `record_observation` | Hidden + fake barcodes (OV:BRCA, LUAD:LIHC) subtly dropped at **5th RO** (mid-Stage 3) | action-based | 42, 7, 123 | 6 |

**4 TCGA cohorts:** BRCA, LIHC, LUAD, OV (trimmed from 7 on 2026-06-18 for cost — dropped LUSC/PRAD/UCEC; OV + LUAD retained as the G3 true cohorts)

**Held-out test set:** SGH-OS (Jia et al. 2022, 91 samples, multi-omics). Run G0/G1/G2 only (no G3 — single cohort). Discovery rubric scored against TARGET-OS external validation (Phase 3) rather than the paper's reported markers.

### Models

| # | Model | Family | API ID | Role | Episodes |
|---|-------|--------|--------|------|----------|
| M1 | Claude Sonnet 4.6 | Claude | `claude-sonnet-4-6` | Fast/cheap reference | 40 |
| M2 | Claude Opus 4.7 | Claude | `claude-opus-4-7` | High-capability Claude | 40 |
| M3 | GPT-5.4 | OpenAI | `gpt-5.4-2026-03-05` | Cross-family reference | 40 |
| M4 | GPT-5.5 | OpenAI | `gpt-5.5-2026-04-23` | High-capability OpenAI | 40 |
| M5 | Gemini 3.1 Pro | Google | `gemini-3.1-pro` | Cross-family reference | 40 |

**Total episodes:** 40 × 5 models = **200 episodes**

### Infrastructure

- Runners: `bash scripts/run_tcga.sh --tag <run>` (G0-G3, TCGA cohorts) and `bash scripts/run_cohort.sh --tag <run> --cohort OS` (G0-G2, SGH-OS)
- Results saved to `results/tcga/<run>/<uuid>/` (TCGA) or `results/external/<run>/<uuid>/` (OS)
- Scorers: `scripts/score_tcga_episode.py` (TCGA faithfulness, 16 pts) and `scripts/score_sghos_episode.py` (OS discovery, 24 pts)

---

## Evaluation Metrics

Scoring is now bifurcated between the two experiments. See `docs/TASK_A_COHORT.md § Scoring (post-hoc, bifurcated)` and the `README.md` Scoring section for the canonical component-level rubrics.

- **TCGA faithfulness rubric** — 16 pts, 8 Phase 1 components (no Phase 2). Reference concordance against known TCGA subtypes is the faithfulness anchor.
- **SGH-OS discovery rubric** — 24 pts: Phase 1 = 16 pts (7 components) + Phase 2 Examination = 3 pts + Phase 3 TARGET-OS external validation = 5 pts. Reference concordance deliberately absent.

### Secondary metrics

| Metric | What it measures |
|--------|-----------------|
| G0 − G2 score delta | How much recall contributes vs. data reasoning |
| G3 mislead rate | Fraction of G3 episodes where agent adopts the false identity |
| TCGA vs. osteosarcoma score gap | Recall confound magnitude — models that score well on TCGA but poorly on osteosarcoma are relying on memorization |
| Score variance across seeds | Stability of each model's reasoning |

---

## Budget

After the G3a/G3b sub-arm split (2026-06-15) and the cohort trim from 7 → 4 (2026-06-18, dropped LUSC/PRAD/UCEC for cost), the per-model TCGA episode count is **40** (G0×4 + G1×12 + G2×12 + G3a×6 + G3b×6).

| Model | API pricing | Est. cost/ep | 40 episodes (1 model) |
|-------|------------|-------------|-------------|
| Claude Sonnet 4.6 (M1) | $3/M in · $15/M out | ~$3 | ~$120 |
| Claude Opus 4.7 (M2) | $15/M in · $75/M out | ~$15 | ~$600 |
| GPT-5.4 (M3) | $2.50/M in · $15/M out | ~$3 | ~$120 |
| GPT-5.5 (M4) | $5/M in · $30/M out | ~$6 | ~$240 |
| Gemini 3.1 Pro (M5) | $2/M in · $12/M out | ~$2 | ~$80 |

| Line item | Amount |
|-----------|--------|
| TCGA 5-model × 40 episodes (200 episodes) | ~$1,160 |
| Osteosarcoma — 5 models × 9 episodes (45 episodes), incl. Phase 3 | ~$300 |
| Scoring API cost (LLM judge) — all episodes | ~$80 |
| Reruns / debugging | ~$100 |
| **Total budget** | **~$1,640** |

---

## Timeline

| Milestone | Dependency |
|-----------|-----------|
| Run M1 (Sonnet) — all 40 eps | Budget approved |
| Score M1, verify pipeline end-to-end | M1 complete |
| Run M2–M5 in parallel | M1 pipeline verified |
| Osteosarcoma data ready → build scorer | Data collection complete |
| Run osteosarcoma episodes (M1, M2, M3) | Scorer built |
| Analysis and writeup | All scoring complete |

---

## Key Files

| File | Purpose |
|------|---------|
| `scripts/run_tcga.sh` | TCGA G0-G3 benchmark runner (resume-safe; `--smoke-test` for pipeline check) |
| `scripts/run_cohort.sh` | OS G0-G2 benchmark runner (resume-safe; `--smoke-test` for pipeline check) |
| `scripts/run_episode.py` | Single-episode CLI (cohort-aware default results-base) |
| `scripts/score_tcga_episode.py` | TCGA faithfulness scorer (Phase 1, 16 pts) |
| `scripts/score_sghos_episode.py` | OS discovery scorer (Phase 1+2+3, up to 24 pts) |
| `docs/TASK_A_COHORT.md` | Full task design and empirical findings |
| `docs/GRAND_DESIGN.md` | Overall benchmark architecture |
