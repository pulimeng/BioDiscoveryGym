# BioDiscoveryGym Implementation Plan v4

> Supersedes `IMPLEMENTATION_PLAN_v3.md`.
> Central thesis: three process-level instruments to expose recall-driven discovery.

---

## The Core Claim

Many recent papers claim LLMs can perform autonomous biomedical discovery. This benchmark
challenges that claim with a specific, measurable critique:

> **For well-studied cancer types, LLM agents produce correct biological conclusions
> not by reasoning from data, but by retrieving training knowledge and selectively
> fitting numbers to predetermined conclusions.**

The key insight is that for well-known biology, **recall and discovery produce the same
outcome**. Correct outcomes cannot distinguish the two. We measure the **reasoning process**
instead — and we design three instruments that force recall and discovery to diverge.

---

## Why Question Design Is Not the Solution

An earlier approach (PHASE2_REDESIGN.md) tried to make Phase 2 questions "data-dependent"
by asking for specific quantities not available in training data (co-occurrence counts,
RPPA correlations, outlier profiles). This was the wrong frame.

**Why it doesn't work as a harness:**
- Questions become cohort-specific (naming TP53/CTNNB1, Proliferative subtype, etc.)
- Requires expert knowledge to write new questions for each cohort
- Still brute-forces data access through question phrasing rather than measuring process

**The right frame:**
The process property we want to measure — does the conclusion follow from the data or
precede it? — doesn't require specific questions. It requires experimental design that
forces the two reasoning paths to produce different outputs.

Phase 2 questions are **scaffolding**: they give the agent something to answer so the
reasoning process is observable. The specific content is secondary. What matters is
whether the answer is traceable to Stage A pre-committed values, and whether it
survives data perturbation.

---

## The Reasoning Process Has Observable Signatures

Two paths to the same correct answer:

**Recall path:** retrieve canonical answer → run confirming code → attach numbers

**Discovery path:** observe data pattern → form hypothesis → report pattern, then name it

These diverge in two observable ways:

**Order of operations:** Stage A pre-commitment makes this measurable. Agent commits to
raw quantities (PC loadings, survival direction, mutation enrichment) before knowing what
questions will be asked. Contradictions between Stage A values and Phase 2 claims are
detectable recall overrides.

**Perturbation response:** when canonical signals are flipped in the data, recall and
discovery diverge. Recall agent reports canonical biology. Discovery agent reports
the data — even when it contradicts the prior.

---

## The Three Instruments

### Instrument 1 — Stage A Pre-Commitment

**What it measures:** Does Phase 2 reasoning hold to data-derived pre-committed values,
or does it drift back to canonical biology?

**How it works:**
- After Phase 1, agent runs a blind data sweep before questions are revealed
- Commits to: PC loadings (gene + r values), survival direction per subtype,
  mutation enrichment per subtype (top genes + Fisher's p)
- Phase 2 answers are then checked against these committed values
- Any contradiction = detectable recall override

**Example caught in first LIHC run:**
- Stage A committed: PC3 top loadings = DCN, LUM, MFAP4 (fibrosis/stellate cell markers)
- Phase 2 reported: "PC3 = proliferation intensity sub-axis"
- Contradiction: the agent expected a proliferation PC and named it before reading loadings

**Already implemented.** Run with `--phase2-stage-a`.

### Instrument 2 — Consistency Audit

**What it measures:** Automated detection of Stage A vs Phase 2 contradictions.

**How it works:**
- LLM judge receives Stage A report + Phase 2 final answer
- Flags contradictions by type: direction_flip, axis_mislabeling, numerical_discrepancy,
  absent_from_stage_a
- Scores 0–5 (5 = zero contradictions)

**To build:** `scripts/score_stage_a_consistency.py` (~80 lines)

### Instrument 3 — Data Perturbation

**What it measures:** Does the agent follow the data when it contradicts training priors?

**The perturbation:**
Flip two canonical signals in the LIHC metadata — survival direction and mutation
enrichment — between the two subtype groups. Expression data unchanged.

- Survival: swap vital_status + days_to_death between Metabolic and Proliferative groups
- Mutations: swap TP53 and CTNNB1 mutation status between groups

Stage A pre-commitment must include survival direction and top mutation per subtype.
These are the quantities that diverge between recall and discovery after perturbation.

**Score per run:**
- 2 = both perturbed signals correctly reported (data-following)
- 1 = one correct, one reverted (partial recall)
- 0 = both reverted to canonical (recall override)

**Run design:** 2 baseline + 2 perturbed LIHC = 4 episodes (~$12 Sonnet)

**To build:** `scripts/perturb_lihc.py` + `--perturb` flag

---

## Phase 2 Questions

Questions are scaffolding — they prompt the agent to reason about its findings so the
process is observable. They do not need to be "data-dependent" by design; the perturbation
and consistency audit do the measurement work.

**Requirements for questions:**
1. Ask the agent to reason about its own Phase 1 findings (not named biology)
2. Require reporting numbers before interpretation
3. Cover the signals the perturbation tests (survival, mutation enrichment)

Current LIHC questions satisfy these requirements. Stage A prompt updated to require
explicit pre-commitment of survival direction and mutation enrichment per subtype,
which are the quantities the perturbation tests directly.

---

## Stage A Prompt Requirements

The Stage A prompt must require pre-commitment of:
1. PC loadings (genes + r values) — for consistency audit on axis labeling
2. **Survival by subtype** (median OS, log-rank p, which subtype is better) — for perturbation test
3. **Top mutation per subtype** (gene, Fisher's p, counts) — for perturbation test
4. RPPA differences — for consistency audit on cross-modal claims
5. One unexpected finding — forces honest reporting

Items 2 and 3 are the critical ones for perturbation. A perturbed agent that pre-commits
the wrong survival direction has demonstrably ignored the data.

---

## Cost Budget

| Item | Count | Cost | Total |
|---|---|---|---|
| Baseline LIHC (Stage A + Phase 2) | 2 | $3 | $6 |
| Perturbed LIHC (Stage A + Phase 2) | 2 | $3 | $6 |
| Consistency scoring | 4 | $0.20 | $0.80 |
| Delta scoring | 4 | $0.20 | $0.80 |
| **Minimum viable** | | | **~$14** |

No novelty control needed for v2 questions — the measurement is now perturbation-based,
not question-design-based.

---

## Implementation Order

### Step 1 — Update Stage A prompt in lihc.py
Ensure Stage A explicitly requires survival direction and top mutation per subtype.
These are the pre-committed values the perturbation checks. ✅ Done.

### Step 2 — Build perturbation data
```
scripts/perturb_lihc.py  (~60 lines)
  - load data/subtypes/pancan_subtypes.tsv → iCluster 1/2 (Metabolic) vs 3 (Proliferative)
  - load data/tcga/lihc/clinical.tsv → swap vital_status, days_to_death, days_to_last_follow_up
  - load mutations parquet → swap TP53 / CTNNB1 columns between groups
  - write clinical_perturbed.tsv + mutations_perturbed.parquet
```

Small edits (~5 lines each):
- `biodiscoverygym/utils/data_loader.py`: add `perturb: bool = False`
- `biodiscoverygym/episode.py`: pass `perturb` to `load_tcga()`
- `scripts/run_episode.py`: add `--perturb` flag

Gate: run 1 perturbed episode, verify agent sees inverted survival + mutations in raw data.

### Step 3 — Build consistency judge
```
scripts/score_stage_a_consistency.py  (~80 lines)
  - extract Stage A report from episode JSON
  - extract Phase 2 final answer
  - LLM judge: compare values, flag contradictions by type
  - output: contradiction list + consistency score 0-5
```

Gate: run on first LIHC baseline, verify it catches known inconsistencies.

### Step 4 — Run full battery
```bash
# Baseline
python scripts/run_episode.py --cohort LIHC --seed 42 \
  --phase2 LIHC --phase2-stage-a --save-log lihc_base_s42.json

python scripts/run_episode.py --cohort LIHC --seed 43 \
  --phase2 LIHC --phase2-stage-a --save-log lihc_base_s43.json

# Perturbed
python scripts/run_episode.py --cohort LIHC --seed 42 \
  --phase2 LIHC --phase2-stage-a --perturb \
  --save-log lihc_perturbed_s42.json

python scripts/run_episode.py --cohort LIHC --seed 43 \
  --phase2 LIHC --phase2-stage-a --perturb \
  --save-log lihc_perturbed_s43.json
```

### Step 5 — Score all runs
```bash
python scripts/score_stage_a_consistency.py \
  --episode results/{id}/lihc_base_s42.json \
  --save results/{id}/consistency_s42.json

python scripts/score_phase2_delta.py \
  --episode results/{id}/lihc_base_s42.json \
  --baseline results/novelty_lihc.json \
  --save results/{id}/delta_s42.json
```

---

## What We Measure and Report

| Metric | Source | Meaning |
|---|---|---|
| Perturbation accuracy | Instrument 3 | Fraction of perturbed runs correctly reporting inverted signal |
| Consistency score | Instrument 2 | Mean 0–5 across runs; contradictions between Stage A and Phase 2 |
| Phase 1 score | `Evaluator.score()` | NMI + survival + AUC + coverage (0–15) |

**The key result pattern:**
Phase 1 score high (correct outcomes) + perturbation accuracy low + consistency score low
= "correct outcome, wrong process" = recall-driven discovery.

---

## Null Hypothesis

> H0: The agent's Phase 2 answers are generated by reasoning from the data,
> independent of training priors.

The perturbation test is a direct test of H0. If the agent correctly reports the
inverted survival and mutation signals in perturbed runs, H0 is not rejected.
If it reverts to canonical biology, H0 is rejected.

---

## Scope Boundaries

- Multi-cohort (OV, LUSC): deferred. LIHC alone sufficient for core claim.
- Opus runs: deferred to publication. All development on Sonnet.
- Other models: deferred. Single-model characterization first.
- Novelty control: not needed for the revised design — perturbation does the work.

---

## Key Files

| File | Status | Purpose |
|---|---|---|
| `biodiscoverygym/phases/lihc.py` | ✅ Updated | Stage A prompt + Phase 2 questions |
| `scripts/perturb_lihc.py` | Build | Perturbed clinical + mutation files |
| `scripts/score_stage_a_consistency.py` | Build | LLM judge: Stage A vs Phase 2 |
| `scripts/score_phase2_delta.py` | Exists | Delta scoring |
| `biodiscoverygym/utils/data_loader.py` | Small edit | Add `perturb` param |
| `biodiscoverygym/episode.py` | Small edit | Pass `perturb` through |
| `scripts/run_episode.py` | Small edit | Add `--perturb` flag |
