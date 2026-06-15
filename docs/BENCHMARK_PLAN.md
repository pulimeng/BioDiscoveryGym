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

**4 experimental groups (67 runs, TCGA set):**

| Group | Label | Gene names | Cohort name | Gate | Seeds | Runs |
|-------|-------|------------|-------------|------|-------|------|
| G0 | Explicit retrieval | Real (forced) | **Revealed** | 0 | 42 | 7 |
| G1 | Implicit retrieval | Real | Hidden | 0 | 42, 7, 123 | 21 |
| G2 | Data-driven | GENE_XXXXX → real at call 30 | Hidden | 30 | 21 |
| G3 | Mislead | GENE_XXXXX → real at call 30 | Hidden + wrong barcodes | 30 | 42, 7, 123 | 18 |

**7 TCGA cohorts:** BRCA, PRAD, UCEC, LUAD, LIHC, LUSC, OV

**Held-out test set:** Osteosarcoma (~80 samples, multi-omics, 2023 paper). Run G0/G1/G2 only (no G3 — single cohort). Scored against paper-specific ground truth; in preparation.

### Models

| # | Model | Family | API ID | Role | Episodes |
|---|-------|--------|--------|------|----------|
| M1 | Claude Sonnet 4.6 | Claude | `claude-sonnet-4-6` | Fast/cheap reference | 67 |
| M2 | Claude Opus 4.7 | Claude | `claude-opus-4-7` | High-capability Claude | 67 |
| M3 | GPT-5.4 | OpenAI | `gpt-5.4-2026-03-05` | Cross-family reference | 67 |
| M4 | GPT-5.5 | OpenAI | `gpt-5.5-2026-04-23` | High-capability OpenAI | 67 |
| M5 | Gemini 3.1 Pro | Google | `gemini-3.1-pro` | Cross-family reference | 67 |

**Total episodes:** 67 × 5 models = **335 episodes**

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

| Model | API pricing | Est. cost/ep | 67 episodes |
|-------|------------|-------------|-------------|
| Claude Sonnet 4.6 (M1) | $3/M in · $15/M out | ~$6 | ~$402 |
| Claude Opus 4.7 (M2) | $15/M in · $75/M out | ~$28 | ~$1,876 |
| GPT-5.4 (M3) | $2.50/M in · $15/M out | ~$6 | ~$402 |
| GPT-5.5 (M4) | $5/M in · $30/M out | ~$12 | ~$804 |
| Gemini 3.1 Pro (M5) | $2/M in · $12/M out | ~$5 | ~$335 |

| Line item | Amount |
|-----------|--------|
| TCGA 335 episodes (5 models) | ~$3,819 |
| Osteosarcoma runs (~3 models × ~25 eps) | ~$400 |
| Scoring API cost (LLM judge, 335 eps) | ~$300 |
| Reruns / debugging | ~$100 |
| **Total budget** | **~$4,619** |

---

## Timeline

| Milestone | Dependency |
|-----------|-----------|
| Run M1 (Sonnet) — all 67 eps | Budget approved |
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
