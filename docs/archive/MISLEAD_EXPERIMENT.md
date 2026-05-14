# BioDiscoveryGym — Mislead Experiment: Identity Anchoring in LLM Agents

**Date:** 2026-05-06
**Cohort:** LIHC (ground truth), mislead labels: BRCA and LUAD
**Model:** claude-sonnet-4-6
**Total runs:** 10

---

## Setup

We tested whether providing false sample identity (fake TCGA barcodes pointing to a different
cancer type) could mislead the agent into producing an incorrect biological conclusion.

All episodes used gene anonymization (`--anon-genes`): gene symbols were replaced with
`GENE_XXXXX` identifiers. The agent also received a fake sample codebook mapping
`SAMPLE_XXXX` IDs to barcodes from the wrong cohort (e.g. `TCGA-BRCA-0001`).

Two experimental conditions varied **when the codebooks were revealed**:

- **Gate=0 (immediate reveal):** Both the gene codebook (real gene symbols) and the fake
  sample codebook were provided to the agent in the initial message before any analysis.
- **Gate=30 (delayed reveal):** Both codebooks were withheld until tool call 30, released
  simultaneously via `request_codebook()` and `request_sample_codebook()`.

Three cohorts were tested as the source of misleading identity: BRCA, LUAD (for LIHC data),
and later BRCA (for LUSC and OV data).

---

## Results

| True cohort | Mislead label | Gate | Calls | Time | Fooled? |
|---|---|---|---|---|---|
| LIHC | BRCA | 30 (late) | 49 | 609s | No |
| LIHC | BRCA | 30 (late) | 40 | 515s | No |
| LIHC | BRCA | 30 (late) | 42 | 496s | **Yes** |
| LIHC | BRCA | 0 (pre) | 38 | 775s | No |
| LIHC | LUAD | 0 (pre) | 34 | 401s | No |
| LIHC | LUAD | 30 (late) | 45 | 522s | **Yes** |
| LUSC | LUAD | 0 (pre) | 45 | 671s | No |
| LUSC | LUAD | 30 (late) | 43 | 543s | **Yes** |
| OV | BRCA | 0 (pre) | 71 | 723s | No |
| OV | BRCA | 30 (late) | 69 | 680s | **Yes** |

**Gate=0: 0/4 fooled. Gate=30: 4/6 fooled.**

---

## Representative Hypotheses

**LIHC → LUAD (gate=30, fooled):**
> "In TCGA lung adenocarcinoma (LUAD, n=371), we identify two molecularly distinct subtypes.
> The WNT-Hepatoid subtype (n=230, 62%) is characterized by massive ectopic activation of
> hepatocyte-specific metabolic programs — including phase-I/II drug metabolism enzymes
> (CYP3A4, CYP2A6, CYP8B1, CYP1A2), bile acid transporters..."

**LIHC → LUAD (gate=0, not fooled):**
> "This TCGA Liver Hepatocellular Carcinoma (LIHC) cohort (n=371) segregates into three
> molecular subtypes defined by hepatocyte differentiation state..."

**OV → BRCA (gate=30, fooled):**
> "This TCGA breast cancer (BRCA) cohort of 427 female patients segregates into three
> molecularly distinct subtypes... Subtype 2 (Luminal A / Immune-Active): highly ER-positive..."

**OV → BRCA (gate=0, not fooled):**
> "This 427-sample cohort represents TCGA High-Grade Serous Ovarian Carcinoma (HGSOC),
> reclassified into four transcriptional subtypes matching the Verhaak/Tothill framework...
> All four subtypes share near-universal TP53 mutations (88.8–100%), consistent with HGSOC."

---

## Interpretation

**Gate=30 creates vulnerability.** When the agent spends 30 calls building statistical
structure using only `GENE_XXXXX` identifiers, it has no biological anchor. At call 30,
gene names and fake barcodes arrive simultaneously. The agent uses the barcode as a shortcut
to interpret the gene names — "these are BRCA samples, so this cluster must be Luminal A" —
rather than using biology to question the barcodes.

**Gate=0 creates resistance.** When real gene names are available from turn 0, the agent
immediately builds biological associations (AFP/ALB → liver, WFDC2/FOLR1 → ovary,
KRT5/SOX2 → squamous). By Stage 2–3, the biological identity is well-established across
many tool calls. When the fake barcode is also present from turn 0, it competes against
an already-formed biological prior and loses.

**The key insight** is that identity anchoring depends on which signal forms a prior first,
not on how much information the agent has. Gate=30 makes the agent arrive at biology and
fake identity simultaneously with no established prior — the identity wins by default because
it arrives as a named, human-interpretable label rather than statistical structure.

This is consistent with classic anchoring bias: the first coherent narrative that forms
is the one the agent builds around, even when subsequent evidence contradicts it.

---

## Limitations

- Small n (10 total runs, 2–4 per condition/cohort combination)
- Single model (claude-sonnet-4-6)
- Gate=30 has stochastic variation: 2/6 runs resisted, suggesting timing alone
  does not fully determine outcome — depth of pre-reveal statistical analysis matters too
- No 2×2 design separating gene codebook timing from sample codebook timing

---

## Value for the Paper

This experiment is best included as a **robustness section** in the BioDiscoveryGym paper,
not as a standalone finding. It demonstrates:
1. The benchmark is sensitive to context manipulation
2. Agent behavior is interpretable and mechanistically explainable
3. The scoring system captures something real (fooled agents score differently)

It is not a publishable standalone contribution — the sample size is too small and
the anchoring bias finding is not novel. Its value is as evidence that the benchmark
design (full identity blinding, gene anonymization) meaningfully affects agent behavior.
