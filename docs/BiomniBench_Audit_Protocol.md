# Auditing BiomniBench-DA: Does the Anti-Recall Instruction Work?

*Pre-registered experimental protocol — May 2026*

## Background

BiomniBench-DA (Qu et al., bioRxiv May 12, 2026) is a process-level benchmark for biomedical research agents from a Stanford-led collaboration (Phylo, Humanlaya Data Lab, xbench, Laude Institute, Stanford, Virginia Tech, Harvard, Peking University; senior authors Jure Leskovec and Kexin Huang). It builds on the open-source Biomni agent platform (Huang et al. 2025, also from the Leskovec lab) and uses 100 data-analysis tasks drawn from 21 high-impact published papers (Nature, Cell, Science, Nature Medicine, Cancer Cell, Science Immunology, etc.). Each task hands the agent a publicly-deposited dataset and asks it to perform an analysis derived from the source paper. Scoring is fully LLM-driven: Gemini 3.1 Pro judges each agent trace against an expert-authored rubric of 5–10 A/B/C criteria.

BiomniBench's only anti-memorization mechanism is a prompt-level instruction:

> *"Do not search for or read the specific source paper, figures, or supplementary materials that the dataset comes from. Solve the task directly from the provided data and domain knowledge."*

However, every task prompt **discloses identifying metadata** for the source dataset — e.g., *"Cell 2024; GSE236581"* — which uniquely identifies the underlying paper. The instruction prevents runtime retrieval but cannot prevent parametric recall from pretraining, where the source papers and their derivative literature are present in essentially every frontier model's training corpus.

## Prior evidence (BioDiscoveryGym, internal report)

In our cohort-substitution stress test we replaced informative cohort labels with misleading ones and varied the agent's analysis budget (Gate). At Gate=0 (low analysis), 0 of 4 cohort pairs were fooled. At Gate=30 (high analysis), 3 of 4 were fully fooled; LIHC↔BRCA was partially fooled (1 of 3 trials). The asymmetric fooling pattern implicates pretrained gene → cancer-type associations: pairs that are biologically incompatible (LIHC's liver-specific markers vs. BRCA) resist fooling; biologically compatible pairs do not. By the same mechanism, BiomniBench's named-accession prompts should leak even more strongly because they directly identify the answer-key paper.

## Hypotheses

**H1 (Recall-as-reasoning).** On BiomniBench-DA tasks, removing paper-identifying metadata from the prompt will significantly reduce LLM-judge scores. The magnitude of the drop measures the contribution of memorized recall to benchmark performance.

**H2 (Content-mediated leakage).** Additionally scrambling gene names — the primary content-level cue — will reduce scores beyond what metadata removal alone achieves, indicating that recall is driven by gene-pattern priors, not only by named metadata.

## Experimental design

### Task selection

- **N = 5–10 BiomniBench-DA tasks**, sampled across disease domains (oncology, immunology, neurology / metabolic) and publication years (≥ 3 distinct years).
- Tasks chosen to span low and high pretraining exposure (e.g., Hugo et al. 2016 melanoma vs. a 2024 task).

### Conditions (3 arms, applied per task)

1. **Control** — original BiomniBench prompt verbatim, including journal, year, dataset accession (e.g., "Cell 2024; GSE236581").
2. **Identity-stripped** — remove journal, year, accession number, and any paper-identifying language. Replace with generic descriptors (e.g., *"A single-cell tumor cohort from a clinical immunotherapy study"*). Data file contents unchanged.
3. **Identity-stripped + Scrambled** — additionally permute gene symbols via a random bijection over the gene vocabulary, applied consistently to all data files for that task.

All other prompt elements (rubric scoring, environment, output format) held identical across conditions.

### Models

- **Claude Opus 4.7**
- **GPT-5.5**
- **Gemini 3.1 Pro**

Matches BiomniBench's frontier set. Open-weight models optional in a second round.

### Runs and harness

- **n ≥ 5 seeds per (task × agent × condition)** to estimate variance.
- **Harness:** BiomniBench's published Harbor framework on HuggingFace, unmodified for Control; minimally patched for Identity-stripped and Scrambled conditions.
- **Execution budget:** 1 hour per run (BiomniBench default).

### Scoring

Use **BiomniBench's own LLM judge (Gemini 3.1 Pro) with their published rubrics**, applied identically across all conditions. This isolates the manipulated variable to the *prompt*, not the *scorer*, and means we are auditing their pipeline on its own terms.

## Metrics

- Mean and standard deviation of total rubric score across seeds, per (task × agent × condition)
- Per-dimension breakdown: data handling, method selection, statistical rigor, biological interpretation, scientific reasoning, source reliability
- **ΔScore_meta** = Control − Identity-stripped
- **ΔScore_full** = Control − (Identity-stripped + Scrambled)
- Distribution of ΔScore across (task, agent) pairs

## Statistical analysis (pre-registered)

- Primary test: paired Wilcoxon signed-rank on ΔScore_meta across (task, agent) pairs. One-sided α = 0.01.
- Secondary test: same on ΔScore_full.
- Decomposition: nested mixed-effects model with task and agent as random effects, condition as fixed effect.
- Report 95% CI on mean ΔScore (bootstrap).
- All raw scores, prompts, and analysis code released alongside the report.

## Expected outcomes and interpretation

- **If ΔScore_meta is significantly > 0:** BiomniBench's anti-recall instruction is ineffective; scores reflect partial leakage of pretrained paper knowledge. Report by-dimension breakdown — *biological interpretation* and *scientific reasoning* likely show the largest drops; *data handling* should be least affected.
- **If ΔScore_full > ΔScore_meta:** gene-name priors are an additional, independent leakage channel beyond named metadata. Supports the gene-pattern back-channel hypothesis.
- **If ΔScore ≈ 0:** agents do not rely on recall; BiomniBench's scoring reflects genuine analytical capability. (Falsifies our hypothesis; informative either way.)

## Deliverable

A short note titled *"How much of BiomniBench is recall?"* — pre-registered design, raw scores, ΔScore distribution, by-dimension breakdown, and a recommendation: any biomedical benchmark derived from published papers should ship identity-stripped and content-scrambled control conditions alongside its primary task set.

## Why this matters

This is the cleanest empirical test of process-level evaluation on the most prominent biomedical-agent benchmark in the field. The result is informative either direction:

- If our hypothesis holds, every benchmark built from published literature needs an identity-stripped control, and the field has been over-estimating agent capability on a structurally compromised scoring substrate.
- If it doesn't, BiomniBench's anti-recall instruction is robust under adversarial probing, and that's a finding worth publishing in its own right.

In either case, the result establishes BioDiscoveryGym's stress-test methodology as the *audit layer* the biomedical-agent benchmark ecosystem currently lacks.

## Resource estimate

- ~50–100 agent runs × moderate token consumption: hundreds of dollars in API calls
- ~1 week of engineer time to wire the prompt-rewriting and gene-scrambling harness on top of BiomniBench's published artifacts (HuggingFace)
- LLM judge calls: hundreds of additional Gemini 3.1 Pro calls; negligible cost

## Timeline

- Week 1: Harness build, task selection finalized, prompt-rewriting pipeline implemented and validated
- Week 2: Pilot runs (n=2 seeds) to verify scoring stability and harness correctness
- Week 3: Full sweep (n=5+ seeds, 3 agents, 3 conditions, 5–10 tasks)
- Week 4: Analysis, writeup, public release on bioRxiv

---

*Contact: [author] · Code and prompts will be released at github.com/[org]/biomnibench-audit upon completion.*
