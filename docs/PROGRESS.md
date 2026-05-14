# BioDiscoveryGym — Status

**Last updated:** 2026-05-14

---

## Current State

**Task A (cohort analysis):** Infrastructure complete. 67-run benchmark designed, awaiting budget (~$201 on Sonnet).
**Task B (target discovery):** v1 implemented, not yet run systematically.
**Scoring:** v2 scorer (9 components, 18 pts, LLM judge) validated on LIHC baseline — 9.34/18.

---

## Key Empirical Findings (Task A, LIHC)

- **Agents read the data.** Perturbation battery (4 runs, 2 baseline + 2 perturbed): perturbed agents correctly pre-committed inverted signals in Stage A (TP53↔CTNNB1 swapped, survival direction flipped). They are not just recalling canonical HCC biology.

- **Motivated data reading.** Despite correctly reading inverted signals, no agent flagged a biological anomaly. Both perturbed runs immediately rationalized inversions as plausible (AFP early detection, TP53-mediated resistance). Score drop confirmed: baseline 9.45–9.51, perturbed 6.63–7.36.

- **~80% of Phase 2 content is recall.** Novelty control (same questions, no data): correct answers without data for Q1 (CTNNB1, TP53, WNT/PKM) and Q2 (stromal/fibrosis PC axis). No-data answer was *more accurate* than the data-driven agent on Q2 — the agent mislabeled a fibrosis PC as "proliferation intensity sub-axis."

- **Mislead gate effect confirmed.** Gate=0 agents (real gene names from call 1): not fooled by fake barcodes. Gate=30 agents: fooled in ~4/6 runs. Biological identity established early prevents the fake barcode from overriding a formed prior.

---

## How to Resume

```bash
cd /Users/lpu/myprojects/BioDiscovery
conda activate biodiscoverygym

# G0 — explicit retrieval (ceiling baseline, 1 seed per cohort)
python scripts/run_episode.py --cohort BRCA --explicit-retrieval \
  --seed 42 --save-log episode_g0_brca_s42.json

# G1 — implicit retrieval (real gene names from start, cohort hidden)
python scripts/run_episode.py --cohort BRCA --gene-codebook-gate 0 \
  --seed 42 --save-log episode_g1_brca_s42.json

# G2 — data-driven (GENE_XXXXX blind phase, codebook at call 30)
python scripts/run_episode.py --cohort BRCA \
  --seed 42 --save-log episode_g2_brca_s42.json

# G3 — mislead (wrong TCGA barcodes injected)
python scripts/run_episode.py --cohort OV --mislead-cohort BRCA \
  --seed 42 --save-log episode_g4_ov_brca_s42.json

# Score any episode
python scripts/score_episode_v2.py \
  --episode results/{id}/episode_g2_brca_s42.json --cohort BRCA

# Task B — target discovery
python scripts/run_target_discovery_v2.py \
  --indication "Acute Myeloid Leukemia" --save-log results/aml.json
```

---

## Session History

Detailed per-session notes have been archived. Key design decisions are in `docs/GRAND_DESIGN.md`; empirical findings and benchmark design are in `docs/TASK_A_COHORT.md`. Full session logs are in `docs/archive/`.
