# Phase 2 Redesign — Data-Only-Discoverable Questions

> **Superseded by `IMPLEMENTATION_PLAN_v4.md` (2026-05-08)**
>
> This document proposed redesigning Phase 2 questions to require data access. That
> approach was abandoned because it tries to force data-dependency through question
> phrasing — making questions cohort-specific, requiring expert authorship per cohort,
> and still measuring outcomes rather than process.
>
> The v4 design instead measures reasoning process directly through three instruments:
> Stage A pre-commitment, consistency audit, and data perturbation. Phase 2 questions
> are scaffolding; the specific content is secondary. See IMPLEMENTATION_PLAN_v4.md.
>
> This document is retained as a record of the design iteration.

---

**Date:** 2026-05-07  
**Motivation:** Novelty control experiment showed ~80% of Phase 2 answers are literature
recall. Current questions ask about canonical mechanisms in a well-studied cancer type;
the model already knows the answers before seeing the data.

---

## The Core Problem

A good Phase 2 question must have the property:

> **The correct answer cannot be stated without running code on this specific dataset.**

Current questions fail this test. "What is the primary driver — TP53 or WNT?" is
answerable from TCGA-LIHC literature without any data access. The agent retrieves the
answer and then confirms it with numbers.

---

## Design Principles for Data-Dependent Questions

### 1. Ask for a specific quantity from this cohort
Not: "What drives the survival difference?"  
Yes: "At what expression threshold of ALB does survival benefit disappear?
Report the cutoff value, sample sizes on each side, and log-rank p-value."

The answer is a number that exists only in this dataset.

### 2. Ask about anomalies and exceptions
Not: "What is the dominant subtype mechanism?"  
Yes: "Identify samples that score high on both the Metabolic and Proliferative gene
programs simultaneously. How many are there, what is their survival relative to pure
subtypes, and which single gene best discriminates them from the pure clusters?"

Edge cases are not in the literature.

### 3. Ask about cross-modal discordance in this cohort specifically
Not: "What mechanism explains low-mutation aggressive tumors?" (textbook Hippo answer)  
Yes: "Among the 20 samples with the highest proliferation score and lowest TMB,
what is the single RPPA marker most elevated relative to TMB-high proliferative tumors?
Does it reach significance after multiple-test correction?"

Requires running the actual comparison.

### 4. Ask about residuals that require the agent's own grouping
Not: "Does residual prognostic structure exist?" (yes, always, by design)  
Yes: "Fit a Cox model with your subtype labels. What is the largest residual?
What is biologically unusual about that patient's molecular profile compared to
their assigned subtype?"

Forces interrogation of the actual model output, not general biology.

### 5. Ask the agent to contradict itself
Not: "What supports your hypothesis?"  
Yes: "Identify the single strongest piece of evidence in the data that is
inconsistent with your proposed mechanism. Quantify its effect size."

Selective reporting cannot survive this question.

---

## Revised LIHC Phase 2 Questions

### Q1 — TP53 vs CTNNB1: Quantify the Overlap

> In the Proliferative subtype you identified, what fraction of samples have
> BOTH TP53 mutation AND CTNNB1 mutation? What is the survival of this
> double-mutant subgroup relative to single-mutant and wild-type tumors?
> Report exact sample counts, Kaplan-Meier log-rank p-values, and state whether
> the interaction is synergistic, additive, or antagonistic.

*Why this works:* The co-occurrence rate is specific to this cohort. Literature reports
TP53 and CTNNB1 are mutually exclusive in HCC (Guichard et al. 2012) — if this cohort
shows a different pattern, that's a genuine finding.

### Q2 — Find the Outlier, Not the Axis

> Within your Metabolic subtype, identify the 10 samples with the worst survival
> (bottom decile). How do their expression profiles differ from the Metabolic median?
> Which gene signature or pathway is most upregulated in these outliers, and does
> it overlap with the Proliferative signature?

*Why this works:* The specific outlier samples and their molecular profiles are
not in any paper. Forces inspection of actual sample-level data.

### Q3 — Quantify the Conflict, Don't Explain It Away

> Report the exact Spearman correlation between TMB (total somatic mutation count)
> and each of the following in the Proliferative subtype: (a) proliferation score
> [mean of TOP2A, CDK1, MKI67 expression], (b) EPCAM expression, (c) OS months.
> For each, state whether the correlation is significant after Bonferroni correction.
> Then: identify which RPPA protein is most positively correlated with proliferation
> score among TMB-low samples (bottom tertile). Report the r value.

*Why this works:* Forces the agent to report actual correlations — including
non-significant ones — before interpreting. The specific RPPA protein answer
cannot be recalled from literature.

---

## General Template for Any Cohort

These question types generalize beyond LIHC:

| Type | Template |
|---|---|
| Threshold | "At what [gene/score] value does [outcome] cross significance? Report n on each side." |
| Overlap anomaly | "How many samples are high on both [subtype A markers] and [subtype B markers]? What is their outcome?" |
| Cross-modal discordance | "Among [extreme subgroup], which single [modality B] marker deviates most from [modality A] prediction?" |
| Outlier inspection | "Identify the N worst survivors in [good-prognosis] subtype. What gene most distinguishes them?" |
| Forced contradiction | "Report the strongest data point inconsistent with your hypothesis. Quantify it." |

---

## Implementation Plan

1. Replace `biodiscoverygym/phases/lihc.py` QUESTIONS with revised Q1/Q2/Q3 above
2. Re-run Phase 2 episode on LIHC; compare to novelty control
3. Re-run novelty control with new questions — should fail (no data, no answer)
4. Devise equivalent questions for OV and LUSC using same templates
5. Phase 2 scoring: evaluate whether reported numbers match `run_code` outputs
   (automated: parse numbers from final answer, cross-check against tool outputs)
