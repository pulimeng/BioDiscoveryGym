# BioDiscoveryGym — Status

**Last updated:** 2026-05-19

---

## Current State

| Area | Status |
|------|--------|
| Task A infrastructure | Complete |
| Task A OS benchmark | **Complete** — 9 runs (3 modes × 3 seeds), results in `results/cohort/external/` |
| Task A TCGA benchmark | Designed (67 runs); awaiting budget (~$201 on Sonnet) |
| Task B target discovery | v1+v2 implemented; not yet run systematically |
| v2 scorer | Complete — 9 components, 18 pts, 3-axis LLM judge |
| PrimeKG + PCST | Integrated — `--primekg` flag, PCST via networkx steiner_tree |
| OpenTargets | Downloaded and integrated — 1,227 genes, revealed at Stage 5 |

---

## OS Benchmark Results (SGH-OS, Jia et al. 2022)

**9 runs complete. Seed 42 stale runs archived in `results/cohort/external/stale/`.**

| Group | Seeds | Mean total (/15) | Normalized | SD |
|-------|-------|----------------:|-----------|-----|
| G0 — explicit retrieval | 0, 1, 7 | 7.93 | 0.529 | 0.23 |
| G1 — implicit retrieval | 0, 1, 7 | 7.59 | 0.506 | 0.40 |
| G2 — data-driven        | 0, 1, 7 | 7.69 | 0.513 | 0.06 |

Key findings:
- All 9 runs recover the same 4-cluster partition (25/25/21/20); variation lives in narrative, not clustering
- Mode differences (≤0.35 pts) are smaller than G1 seed-to-seed spread (~1 pt) — no mode effect
- G2 is the most stable (SD = 0.06); best individual run G0 s7 = 8.25 (normalized 0.55)
- 3 pts structurally unavailable: `genomic_coherence_drivers` + `genomic_coherence_rppa` require CNA/WES (pending GSA HRA003260)
- Full analysis: `results/cohort/external/os_benchmark_summary.md`

---

## Recent Changes (since 2026-05-14)

### Scorer v2 update: mechanistic_logic axis
`mechanism_grounding` now has 3 axes (was 2): `internal_coherence`, `data_grounding`, `mechanistic_logic`.
- `mechanistic_logic` (0–4): rewards explicit directional causal chains (A activates B → B phosphorylates C → C drives phenotype X), not pathway name-drops
- Total normalizer changed from /8 → /12 (raw score); final weighted contribution unchanged at 3 pts
- Stale seed-42 runs scored under the old judge; re-scoring needed if comparing directly

### PrimeKG integration
- Download: `python scripts/download_primekg.py` (Harvard Dataverse doi:10.7910/DVN/IXA7BM)
- 4 splits: gene-gene (~642k edges), gene-drug (~24k), gene-disease (~95k), gene-pathway (~84k)
- Agent access: `--primekg` flag → pre-reveal with PCST instructions in initial message
- PCST tool: `biodiscoverygym/tools/pcst.py` — networkx KMB approximation, degree-penalized weights
- Purpose: find minimal connected subgraph (Steiner tree) linking top differential genes; Steiner nodes = mechanistic intermediates

### OpenTargets integration
- Download: `python scripts/download_opentargets.py` (OpenTargets Platform GraphQL API, no auth)
- 1,227 OncoKB genes: 32,424 tractability rows, 45,842 drug rows, 147 genes with approved drugs
- Agent access: automatically revealed inside `request_codebook` response (no flag needed)
- Tool: `biodiscoverygym/tools/opentargets.py` — `get_actionability(gene)`, `batch_actionability([genes])`

### OS subtypes added to reference
- Added 91 OS rows to `data/subtypes/pancan_subtypes.tsv` → `reference_concordance` now non-zero (NMI = 0.135, weighted = 0.271)
- _noCNA_noSNV tag on OS run names = CNA and full SNV data absent (pending controlled access)

---

## Key Empirical Findings

### LIHC ep2 (2026-05-05)
- 40 tool calls, ~$3, 7.8 min
- Found Metabolic (n=159) vs Proliferative (n=59) — Hoshida S1/S2 vs S3 analogue
- GSEA: Bile Acid Metabolism NES=−4.81, E2F Targets NES=2.58, all FDR<0.001

### Novelty control (2026-05-07)
- ~80% of Phase 2 answer content correct from recall alone
- No-data answer was *more accurate* than the data-driven agent on PC3 (correctly labeled as stromal/fibrosis)

### Perturbation battery (2026-05-08, 4 runs)
- Agents correctly pre-committed inverted signals → they read the data
- Neither run flagged a biological anomaly; both rationalized inversions as plausible
- Score drop confirmed: baseline 9.45–9.51, perturbed 6.63–7.36

### Mislead gate effect (2026-05-06/13)
- Gate=0 agents: not fooled (biological identity established early from gene names)
- Gate=30 agents: fooled in ~4/6 runs

### OS multi-seed benchmark (2026-05-15/19)
- All 9 runs converge to identical partition — stable benchmark property
- Mode effect absent; seed variance dominates within G1

---

## How to Resume

```bash
cd /Users/lpu/myprojects/BioDiscovery
conda activate biodiscoverygym

# G2 — data-driven (default)
python scripts/run_episode.py --cohort BRCA --seed 42 --save-log results/ep.json

# G2 + PrimeKG
python scripts/run_episode.py --cohort BRCA --seed 42 --primekg --save-log results/ep.json

# G0 — explicit retrieval
python scripts/run_episode.py --cohort BRCA --explicit-retrieval --seed 42

# G1 — implicit retrieval
python scripts/run_episode.py --cohort BRCA --gene-codebook-gate 0 --seed 42

# G3 — mislead
python scripts/run_episode.py --cohort OV --mislead-cohort BRCA --seed 42

# Score any episode
python scripts/score_episode_v2.py --episode results/{id}/episode.json --cohort BRCA

# OS multi-seed (3 modes × 3 seeds)
bash scripts/run_os_multiseed.sh

# Task B
python scripts/run_target_discovery_v2.py --indication "Acute Myeloid Leukemia" --save-log results/aml.json
```

---

## Next Steps

1. **TCGA benchmark** — fund and run 67 episodes (G0×7, G1×21, G2×21, G3×18) on Sonnet (~$201)
2. **PrimeKG evaluation** — run 2 matched episodes (with/without `--primekg`) on same seed/cohort; compare `mechanistic_logic` scores
3. **OS with WES/CNA** — re-run once GSA HRA003260 access granted; expect `genomic_coherence_drivers` to become non-zero
4. **Task B systematic runs** — run target discovery pipeline on 3+ indications
