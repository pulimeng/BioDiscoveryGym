# BioDiscoveryGym — Grand Design

**Last updated:** 2026-05-14
**Status:** Living document — architecture and open design decisions

---

## Overview

BioDiscoveryGym is a benchmark for evaluating LLM-driven biological discovery. Three parts work together:

```
Part 1: Skills Library   →  defines what good reasoning looks like
Part 2: Benchmark Tasks  →  tests whether agents can reason in novel settings
Part 3: LLM Evaluator    →  scores quality where ground truth doesn't exist
```

---

## Part 1 — Skills Library

A curated library of biological reasoning chains distilled from recent publications. Each skill captures how an expert reasoned from data to a novel finding — not just the conclusion, but the analytical steps, cross-dataset integrations, and explicit acknowledgment of evidence gaps.

Prototype: the IRS4 paper (Science Advances 2024) — CRISPR selective dependency → cancer specificity (GTEx) → human tolerability (gnomAD) → mechanism (STRING) → patient frequency (TCGA) → evidence gaps stated → ordered experimental roadmap.

Skills are injected into the benchmark to test whether they improve agent performance. This allows causal attribution: does the skill actually help?

**Status:** Future work — after benchmark is validated.

---

## Part 2 — Benchmark Tasks

### Task A: Cohort-Based Analysis

Given an anonymized patient cohort (expression ± mutations ± RPPA), can an LLM discover real molecular subtypes without being told the cancer type, number of groups, or scoring criteria?

Five-layer identity blinding: clinical columns stripped, demographics removed, TCGA barcodes → `SAMPLE_XXXX`, gene symbols → `GENE_XXXXX`, data served from neutral path. The core instrument is the 4-group experiment (G0/G1/G2/G3, 67 runs, 3 seeds).

**Full design and run commands: `docs/TASK_A_COHORT.md`**

---

### Task B: Target Discovery (no-sample)

Given population-scale cancer dependency and normal tissue data, can an LLM reason to a computationally supported therapeutic target without being told what criteria define a good target?

**What it tests:** Does the agent construct a principled, multi-step evidence chain? Does it check cancer selectivity, normal tissue tolerance, human tolerability (gnomAD), and explicitly state what the data does *not* prove?

**The reasoning chain it should discover** (IRS4 paper as reference):
```
DepMap CRISPR selective dependency
  → cancer-specific? (compare other lineages)
  → normal tissue tolerance? (GTEx expression low)
  → humans survive without it? (gnomAD pLI ~0)
  → mechanism? (STRING, pathway DBs)
  → known driver? (OncoKB)
  → patient frequency? (TCGA)
  → evidence gaps stated explicitly
  → ordered experimental roadmap
```

**Anonymization:** All gene symbols → `GENE_XXXXX` across every dataset (DepMap, GTEx, gnomAD). Disease labels and cell line lineages are kept — the agent needs to reason about selectivity ("essential in AML but not in other cancers"). The agent can cross-reference by `GENE_XXXXX` identifier across datasets.

**Data available to agent:**

| Variable | Source | Notes |
|----------|--------|-------|
| `depmap_crispr` | DepMap 23Q4 | 1100 × 18443 CERES scores |
| `depmap_expr` | DepMap 23Q4 | 1479 × 19193, log2(TPM+1) |
| `depmap_meta` | DepMap 23Q4 | lineage/disease kept |
| `gtex_median` | GTEx v8 | 56200 × 54 tissues |
| `gnomad` | gnomAD v2.1.1 | pLI, LOEUF, obs/exp_lof |

Plus file-based: MSigDB, STRING PPI, OncoKB, COSMIC.

**Evaluation (5 dimensions, 0–2 each, 10 pts max):**

| Dimension | Score 2 requires |
|-----------|-----------------|
| `evidence_chain` | All steps with quantitative criteria and justification |
| `cancer_selectivity` | Quantitative cancer-vs-normal contrast; candidates filtered by GTEx |
| `tolerability_check` | gnomAD used as explicit filter with stated rationale |
| `evidence_gaps` | Specific gaps + the experiment that would address each |
| `roadmap_quality` | Ordered roadmap with model, perturbation, and readout specified |

**Key design decision — mutation-stratified indications:** Real precision oncology targets are often mutation-stratified (e.g., "AML with FLT3-ITD"). Passing a mutation name in the indication string breaks gene anonymization. v1 uses lineage-only indications; mutation stratification is deferred to v2.

**Status:**
- v1 implemented (`agents/claude_agent_target.py`, `scripts/run_target_discovery.py`), not yet run systematically
- LLM judge scorer not yet written
- v2 (mutation stratification, novelty control, Stage A pre-commitment) deferred

---

## Part 3 — LLM Evaluator Harness

An LLM judge for benchmark components that cannot be scored quantitatively: biological insight quality, reasoning chain coherence, hypothesis plausibility, evidence gap identification.

**Adversarial framing (critical):** A naive LLM evaluator rewards confident, well-cited answers — including wrong ones. The evaluator must be given an explicit adversarial role: *find evidence that contradicts the agent's claims*. If a claim survives adversarial scrutiny, it scores well.

**Shared dimensions (both tasks):**
- Factual accuracy — claims against literature
- Reasoning chain quality — steps logically ordered and complete
- Evidence gap honesty — agent correctly identifies what the data does *not* prove
- Novelty — conclusion goes beyond training-data recall (measured against no-data baseline)
- Biological plausibility — proposed mechanism coherent given evidence

**Status:** v2 scorer with LLM judge implemented for Task A (9 components, 18 pts). Full adversarial harness and internet-enabled evaluator not yet built.

---

## What Is Built vs. What Is Planned

| Component | Status |
|-----------|--------|
| Task A: 7-cohort benchmark (BRCA, PRAD, UCEC, LUAD, LIHC, LUSC, OV) | Implemented |
| Task A: 4-group design (G0/G1/G2/G3, 67 runs, 3 seeds) | Designed — awaiting budget |
| Task A: v2 scoring (9 components, LLM judge) | Implemented, validated on LIHC |
| Task A: perturbation battery (LIHC, motivated data reading confirmed) | Complete |
| Task B: no-sample target discovery (v1) | Implemented, not yet run systematically |
| Task B: mutation-stratified indications (v2) | Deferred |
| Part 3: LLM evaluator (Task A scoring) | Partial — quantitative + LLM judge working |
| Part 3: adversarial internet-enabled evaluator | Not started |
| Part 1: skills library | Future work |

---

## Immediate Next Steps

1. Run the 67-episode Task A benchmark (G0/G1/G2/G3, ~$201 on Sonnet)
2. Finalize G3 mislead pairs — OV→BRCA and LUAD→LIHC confirmed; 4 more TBD
3. First systematic Task B runs across 2–3 indications
4. Build adversarial LLM evaluator harness with internet access
