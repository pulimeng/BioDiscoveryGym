# BioDiscoveryGym Implementation Plan v3

> Supersedes `IMPLEMENTATION_PLAN_v2.md`.
> Major additions: real scoring system, multi-modal data (mutation + RPPA),
> gene anonymization mode, mislead experiments, and Phase 2 interrogation.

---

## What Changed from v2

| Area | v2 | v3 |
|---|---|---|
| Scoring | Quality-based stubs (all return 0) | NMI/ARI vs ground-truth subtypes + survival + AUC |
| Data modalities | Expression + metadata only | Expression + metadata + mutations + RPPA |
| Ground truth | None (quality-only scoring planned) | TCGA molecular subtypes from UCSC Xena |
| Gene anonymization | Not implemented | `--anon-genes`: GENE_XXXXX identifiers, codebook gating |
| Sample mislead | Not implemented | Fake TCGA barcodes from wrong cohort, codebook gating |
| Phase 2 | Not planned | Post-submission interrogation: 3 mechanistic questions |
| Cohorts | BRCA, PRAD, UCEC, LUAD, LIHC | + LUSC, OV |

---

## Current Architecture

### Episode Flow

```
Episode.from_cohort(cohort, seed, anonymize_genes, mislead_cohort)
  │
  ├── DataLoader.load_tcga()         → expression, metadata, mutations, rppa
  ├── DataAnonymizer.mask()          → strip leaky clinical columns
  ├── _anonymize_sample_ids()        → SAMPLE_XXXX
  ├── _anonymize_gene_ids()          → GENE_XXXXX (if anonymize_genes=True)
  └── _inject_cohort_mislead()       → fake barcodes + wrong diagnosis (if mislead_cohort set)

Episode.run(agent)
  │
  ├── _write_episode_data()          → data/episode/{expression,metadata,mutations,rppa}.parquet
  ├── agent.run()                    → tool-use loop (Phase 1 + optional Phase 2)
  ├── Evaluator.score()              → EpisodeResult with 5 component scores
  └── _cleanup_episode_data()        → remove data/episode/
```

### Scoring Components

| Component | Max | Method |
|---|---|---|
| `subtype_recovery` | 5.0 | NMI vs TCGA molecular subtypes (Xena pancan) |
| `survival_separation` | 3.0 | Multivariate log-rank test, −log10(p)/5 capped at 1 |
| `marker_discriminability` | 3.0 | Mean per-gene ROC-AUC for top_genes |
| `grouping_coverage` | 2.0 | Fraction of expression samples assigned a label |
| `submission_quality` | 2.0 | No GENE_XXXXX in top_genes, ≥3 pathway_evidence, ≥50 char hypothesis |
| **Total** | **15.0** | |

### Agents

| Agent | When to use |
|---|---|
| `ClaudeAgent` | Standard episodes (real gene names throughout) |
| `ClaudeAgentCohort` | Gene-anonymized episodes; supports mislead codebook gating |

Both agents support `phase2_questions` and `phase2_max_calls` for Phase 2 injection.

### Data

| Cohort | Expression | Mutations | RPPA | Subtypes |
|---|---|---|---|---|
| BRCA | ✅ 1090×19938 | ✅ | ✅ 871×258 | ✅ PAM50 (5 classes) |
| PRAD | ✅ 499×19938 | ✅ | ✅ 350×258 | ✅ Fusion/mutation (8 classes) |
| UCEC | ✅ 545×19938 | ✅ | ✅ 403×258 | ✅ POLE/MSI/CN (4 classes) |
| LUAD | ✅ 513×19938 | ✅ | ✅ 359×258 | ✅ iCluster 1–6 |
| LIHC | ✅ 371×19938 | ✅ | ✅ 371×258 | ✅ iCluster 1–3 |
| LUSC | ✅ 501×19938 | ✅ | ✅ 322×258 | ✅ 4 classes |
| OV | ✅ 427×19938 | ✅ | ✅ 298×258 | ✅ 4 classes (Verhaak) |

---

## Phase 2 — Mechanistic Interrogation

### Design

After `submit_discovery` completes Phase 1, Phase 2 injects a set of follow-up questions
as a tool result. The agent retains full Phase 1 context and continues using `run_code`
to answer them. Budget: 30 additional tool calls (configurable).

Phase 2 questions are cohort-specific and defined in `biodiscoverygym/phases/{cohort}.py`.

### LIHC Phase 2 Questions

Defined in `biodiscoverygym/phases/lihc.py`:

**Q1 — Competing Causal Mechanisms**
What is the primary driver of the survival-associated transcriptional program —
TP53 dysfunction, WNT/CTNNB1 activation, immune exclusion, or metabolic adaptation?
Compare evidence across modalities and provide one falsification test.

**Q2 — Residual Biology Beyond Known Taxonomy**
After accounting for the dominant subtype axis, does meaningful prognostic structure remain?
If so, what biological process underlies it, and does it predict survival independently?

**Q3 — Multi-Omic Conflict Resolution**
A subgroup shows aggressive transcriptional behavior but low mutational burden.
What mechanism explains this phenotype? Identify the strongest supporting modality,
explain why simpler explanations fail, and propose one validation experiment.

### Goals

- Q1 tests causal adjudication (not just subtype recognition)
- Q2 prevents ontology shortcutting; forces residual mechanistic discovery
- Q3 forces cross-modal reasoning under ambiguity

### Usage

```bash
python scripts/run_episode.py --cohort LIHC --phase2 LIHC \
  --phase2-max-calls 30 --save-log lihc_phase2_ep1.json
```

### Scoring Phase 2

Not yet implemented. Phase 2 answers are saved in the message log for human evaluation.
Future: LLM-as-judge scoring for mechanistic correctness, use of ≥2 modalities, and
specificity of falsification test.

---

## Run Modes

```bash
# Standard episode
python scripts/run_episode.py --cohort LIHC --save-log out.json

# Gene-anonymized (GENE_XXXXX, codebook at call 30)
python scripts/run_episode.py --cohort LIHC --anon-genes --save-log out.json

# Gene-anonymized + immediate reveal (codebook at call 0)
python scripts/run_episode.py --cohort LIHC --anon-genes \
  --gene-codebook-gate 0 --save-log out.json

# Mislead: fake LUAD barcodes, delayed reveal
python scripts/run_episode.py --cohort LIHC --anon-genes \
  --mislead-cohort LUAD --gene-codebook-gate 30 --sample-codebook-gate 30 \
  --save-log out.json

# Mislead: fake LUAD barcodes, immediate reveal
python scripts/run_episode.py --cohort LIHC --anon-genes \
  --mislead-cohort LUAD --gene-codebook-gate 0 --sample-codebook-gate 0 \
  --save-log out.json

# Phase 2 interrogation
python scripts/run_episode.py --cohort LIHC --phase2 LIHC --save-log out.json

# Opus for final runs (~$15/ep)
python scripts/run_episode.py --cohort LIHC --model claude-opus-4-7 --save-log out.json
```

---

## Key Files

| File | Purpose |
|---|---|
| `biodiscoverygym/episode.py` | Episode orchestration, anonymization, mislead injection |
| `biodiscoverygym/evaluator.py` | 5-component scoring against ground truth subtypes |
| `biodiscoverygym/executor.py` | Sandboxed Python executor, pre-loaded namespace |
| `biodiscoverygym/utils/data_loader.py` | Loads expression + mutations + RPPA from parquet |
| `biodiscoverygym/utils/hidden_context.py` | DataAnonymizer strips leaky clinical columns |
| `biodiscoverygym/phases/lihc.py` | LIHC Phase 2 questions |
| `agents/claude_agent.py` | Standard agent (real gene names) |
| `agents/claude_agent_cohort.py` | Gene-anonymized agent with codebook gating |
| `scripts/run_episode.py` | CLI runner with all flags |
| `scripts/download_tcga.py` | Download expression + clinical from GDC |
| `scripts/download_mutations.py` | Download MAF files from GDC |
| `scripts/download_rppa.py` | Download RPPA from UCSC Xena |
| `scripts/download_subtypes.py` | Download molecular subtypes from UCSC Xena |
| `data/subtypes/pancan_subtypes.tsv` | Ground truth subtypes (3017 samples, 7 cohorts) |

---

## Remaining Work

### Immediate
- [ ] Run Phase 2 episodes on LIHC and evaluate quality of answers qualitatively
- [ ] Devise Phase 2 questions for other cohorts (OV, LUSC) — currently LIHC only
- [ ] Phase 2 scoring: LLM-as-judge or rubric-based evaluation

### Near-term
- [ ] Multi-cohort benchmark runs: all 7 cohorts × 3 seeds × standard mode
- [ ] Negative controls: shuffled gene labels, shuffled sample labels
- [ ] `ClaudeAgentCohort` Phase 2: verify codebook is still available in Phase 2 context

### Future
- [ ] Other models (GPT-4o, Gemini) for comparison
- [ ] Phase 2 questions for remaining cohorts
- [ ] Preprint
