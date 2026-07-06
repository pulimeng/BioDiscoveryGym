# BioDiscoveryGym — Status

**Last updated:** 2026-07-02 · scoring map: **`docs/README.md`** (start here)

---

## Current State

| Area | Status |
|------|--------|
| Task A infrastructure | Complete |
| Task A OS benchmark | run6 complete (bugs found + fixed); **run7 ready** |
| Task A TCGA benchmark | Designed (40 runs: G3 split into G3a ro_gate=3 + G3b ro_gate=5 sub-arms 2026-06-15; cohorts trimmed 7→4 on 2026-06-18); awaiting budget (~$120 on Sonnet) |
| Task B target discovery | Archived (`scripts/archive/run_target_discovery*.py`) |
| TCGA scorer (outcome) | Complete — **7 components, 14 pts** (RPPA removed 2026-06-30) + cohort-identity gate |
| Explore/exploit scoring — **REFRAMED to support (2026-07-02)** | Strategy (neutral tag) × support (scored: grounded/unsupported/anchored) replaces derived>recalled. Scorer `scripts/score_support.py` → `_supportscores.json`; judge `scripts/support_judge.py` validated ~95% on `scripts/support_probes.json`; fact-check cards `docs/COHORT_REFERENCE_CARDS.md`. **Not yet run on real episodes.** Map: `docs/README.md`; rationale: `docs/SUPPORT_JUDGE_PROMPT.md` |
| ~~Decision-point scorer (derived/recalled)~~ | **Superseded** — prototype produced run1+2 `_dpscores.json` (partition derived-rate g0 14%→g2 81%, cited in EXPLORE_EXPLOIT_SCORING). `score_decision_points.py` / `DECISION_POINT_RUBRIC.md` retained for history |
| Mechanism prompt loosening | Committed but **dormant** (`690b3db`); cheap A/B **done** — flat D3 both arms (loosening did not unflatten → model behavior, not prompt). No full re-run. Local-only `run_mech_ab.sh` |
| SGH-OS scorer (Phase 1+2+3) | Complete — 11 components, 24 pts, with TARGET-OS external validation |
| Unified prompt | `agent_system.txt` replaces g0/g1/g2_system.txt; codebook auto-injected |
| multimodal_cluster() | Pre-loaded in executor namespace (MOFA+/SNF/concat_pca) |
| PrimeKG + PCST | Integrated — `--primekg` flag, PCST via networkx steiner_tree |
| OpenTargets | Downloaded and integrated — 1,227 genes, revealed at Stage 5 |

---

## OS Benchmark Results (SGH-OS, Jia et al. 2022)

**9 runs complete. Seed 42 stale runs archived in `results/external/stale/`.**

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
- Full analysis: `results/external/os_benchmark_summary.md`

---

## Recent Changes (since 2026-05-14)

### Scorer v2 update: mechanistic_logic axis
`mechanism_grounding` now has 3 axes (was 2): `internal_coherence`, `data_grounding`, `mechanistic_logic`.
- `mechanistic_logic` (0–4): rewards explicit directional causal chains (A activates B → B phosphorylates C → C drives phenotype X), not pathway name-drops
- Total normalizer changed from /8 → /12 (raw score); final weighted contribution unchanged at 3 pts
- Stale seed-42 runs scored under the old judge; re-scoring needed if comparing directly

### PrimeKG integration
- Download: `python scripts/download/download_primekg.py` (Harvard Dataverse doi:10.7910/DVN/IXA7BM)
- 4 splits: gene-gene (~642k edges), gene-drug (~24k), gene-disease (~95k), gene-pathway (~84k)
- Agent access: `--primekg` flag → pre-reveal with PCST instructions in initial message
- PCST tool: `biodiscoverygym/tools/pcst.py` — networkx KMB approximation, degree-penalized weights
- Purpose: find minimal connected subgraph (Steiner tree) linking top differential genes; Steiner nodes = mechanistic intermediates

### OpenTargets integration
- Download: `python scripts/download/download_opentargets.py` (OpenTargets Platform GraphQL API, no auth)
- 1,227 OncoKB genes: 32,424 tractability rows, 45,842 drug rows, 147 genes with approved drugs
- Agent access: automatically revealed inside `request_codebook` response (no flag needed)
- Tool: `biodiscoverygym/tools/opentargets.py` — `get_actionability(gene)`, `batch_actionability([genes])`

### OS subtypes added to reference
- Added 91 OS rows to `data/subtypes/pancan_subtypes.tsv` → `reference_concordance` now non-zero (NMI = 0.135, weighted = 0.271)
- _noCNA_noSNV tag on OS run names = CNA and full SNV data absent (pending controlled access)

### run6 → run7 infrastructure changes (2026-06-01)

**Unified system prompt:** `prompts/agent_system.txt` replaces three mode-specific files. All G0/G1/G2 differences handled by 5 format vars. `request_codebook` tool removed; codebook is now auto-injected into the conversation as a narrative.

**Codebook reveal redesign:**
- G0/G1: injected into the first user message at episode start
- G2: injected into the 8th `run_code` tool result (deterministic, no RO compliance required)

**multimodal_cluster() pre-loaded** in executor namespace — agents call it directly (MOFA+/SNF/concat_pca).

**Bug fixes:**
- H3F3A anonymization leak: rename map now covers expression∪mutation columns; assertion added
- G2 codebook never fired: `_ro_count >= 5` → `_run_code_count >= 8` in run_code handler
- `data/external` unblocked: added to `_BLOCKED_SUBSTRINGS` (was fully readable, bypassing anonymization)

**Smoke test:** `bash scripts/run_cohort.sh --smoke-test --cohort OS` → G0/G1/G2 × seed=42, 15 calls, results in `results/external/dry-run/`

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

# Score any episode (cohort-specific tracks)
python scripts/score_sghos_episode.py results/external/run10/<uuid>/<label>.json --save     # OS discovery
python scripts/score_tcga_episode.py results/tcga/run10/<uuid>/<label>.json --cohort BRCA --save  # TCGA
bash scripts/score_all_sghos.sh results/external/run10/                    # batch OS
bash scripts/score_all_tcga.sh results/tcga/run10/                      # batch TCGA

# OS smoke test (1 seed/mode, fast verify)
bash scripts/run_cohort.sh --smoke-test --cohort OS

# OS full benchmark run (G0/G1/G2 × 3 seeds = 9 episodes)
bash scripts/run_cohort.sh --tag run10 --cohort OS

# Task B (archived — see scripts/archive/run_target_discovery*.py)
```

---

## Next Steps

1. **run7** — smoke test first, then full 9-run OS benchmark with all fixes applied
2. **TCGA benchmark** — fund and run 40 episodes (G0×4, G1×12, G2×12, G3a×6, G3b×6 from 2 mislead pairs × 2 ro_gates; 4 cohorts) on Sonnet (~$120)
3. **OS with WES/CNA** — re-run once GSA HRA003260 access granted; expect `genomic_coherence_drivers` to become non-zero
4. **Task B systematic runs** — run target discovery pipeline on 3+ indications
