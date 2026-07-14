# BioDiscoveryGym — Status

**Last updated:** 2026-07-14 · scoring map: **`docs/README.md`** · model ladder: **`docs/MODEL_LADDER.md`**

---

## Session 2026-07-13/14 — TCGA ladder EXECUTED + judge upgraded

**The 3-model detailed ladder is run and scored.** All on the neutral **DeepSeek-v4-pro** judge
(both tracks), current prompt, 48 eps/model.

| Model (detailed) | dir | outcome (honest) | grounding /5 |
|---|---|---|---|
| **Sonnet 5** | `ladder/sonnet5_20260713` | **0.503** | **4.79** |
| GPT-5.5 | `ladder/gpt55_20260707` | 0.491 | 4.54 |
| Gemini 2.5 Pro | `ladder/gemini25_` | 0.427 | 3.89 |

- **Sonnet leads both axes; outcome & grounding track together** (right-answer model is also the
  most faithful, not the biggest recaller). Report: `results/tcga/ladder/MODEL_COMPARISON.html`
  (`gen_report.py`) + detailed `gen_ladder_report.py` (per-episode + judge evidence quotes).
- **`run1+2` RETIRED** — old iteration (pre-Jun-30 prompt w/ RPPA + Sonnet 4.6). Kept on disk
  (docs cite its `_dpscores`) but **excluded from all comparisons**. Sonnet-5 detailed is its replacement.

**G3 mislead finding (report per-model, n=6/arm — noisy):** the early≫late anchoring gradient is
**Claude-specific** (Sonnet g3a 4/6 → g3b 2/6). **Cohort dominates timing**: `OV→BRCA` sticky for
all; `LUAD→LIHC` resisted by GPT/Sonnet. **Gemini inverts it** — falls for `LUAD→LIHC` *late* (3/3),
and never confidently resists in G3 (only `mislead`/`hedged`, no `true_cohort`).

**Identity-recall taxonomy (`recall_type`) — the sharper claim.** Mining the judge's D2 evidence
surfaced 5 behaviors: `grounded_recall` / `derived` / `bare_assertion` / `no_identification` /
`wrong_disease`. Models differ in the **character** of identity failure, not just the rate:
Sonnet/GPT mostly **ground-or-derive**; **Gemini disproportionately `no_identification` +
`bare_assertion`** (clusters "0/1" without proposing a disease) and has ~no `grounded_recall`.

**Judge upgraded (2026-07-14, `support_judge.py`):**
- **`recall_type`** now a judge-emitted enum on D2 (auditable, replaces the regex mine).
- **Completeness-retry** — a dropped decision / missing `recall_type` rerolls up to 3× (fixes the
  `'d2_identity'` KeyError class) instead of silently skipping the episode.
- **Consistency audit flag** — e.g. `wrong_disease`+`grounded` mismatch is logged.
- ⚠️ **Requires a support-track rescore (144 eps)** to populate `recall_type` — old scores lack it.

**Lean-prompt ablation** (`prompts/ablation/tcga_lean.txt` via `--prompt-file`): tests whether the
staged prompt *manufactures* the grounding (reviewer confound). **Smoke DONE — all 4 models
(incl. Opus, Sonnet) submit clean G0/G1/G2 under the lean prompt** (`_ablation/lean_smoke/`).
Full lean runs pending; include G0 as the control arm (expect ≈0 lean-vs-detailed gap at G0,
widening through G2 = dose-response).

**Infra fixes (committed):** provider-key routing per `--model` (not always Anthropic); DeepSeek
truncation (8k→16k + retry on `finish_reason=length`) on both judges; `score_run.sh` empty-arg bug;
`resume_support.sh` gap-filler. **Scripts consolidated** — 4 per-run report generators → one
parameterized `gen_report.py`; removed dead one-offs + `__pycache__`.

**Known issues / hardening ideas (not yet done):**
- **`submit_discovery` accepts an unvalidated grouping** — an agent that saves `grouping.json` inside
  a codebook-gated `else` (skipped pre-reveal in G2) submits a *path to a file that was never written*
  → silently unscorable (hit `gemini/g2_lihc_s123`, had to rerun). **Fix: validate the grouping at
  submit time** (path exists + is a dict) so it self-corrects in-episode.
- **Anthropic adapter lacks backoff** — a ~9-min transient API outage killed 6 Sonnet G1 eps (retried
  fine). Add exponential backoff like the Gemini adapter (`e2d89cd`) before long production runs.
- **Validation TODO:** hand-audit ~10–20 `recall_type` + D1/D3 `grounded` labels for judge-vs-human
  agreement (D2 spread already shows the judge discriminates, not defaults). Multi-judge robustness
  (2nd judge on a subset) still the most reviewer-proof step, still pending.

---

## Current State

| Area | Status |
|------|--------|
| Task A infrastructure | Complete |
| Task A OS benchmark | run6 complete (bugs found + fixed); **run7 ready** |
| Task A TCGA benchmark | **RUN + scored (2026-07-14)** — 3-model detailed ladder (Sonnet-5 / GPT-5.5 / Gemini-2.5-pro), 48 eps/model, both tracks on neutral DeepSeek judge. See Session 2026-07-13/14 above. Lean-prompt ablation smoke done; full lean + Opus pending |
| Task B target discovery | Archived (`scripts/archive/run_target_discovery*.py`) |
| TCGA scorer (outcome) | Complete — **7 components, 14 pts** (RPPA removed 2026-06-30) + cohort-identity gate |
| Explore/exploit scoring — **REFRAMED to support (2026-07-02)** | Strategy (neutral tag) × support (scored: grounded/unsupported/anchored) replaces derived>recalled. Scorer `scripts/score_support.py` → `_supportscores.json`; judge `scripts/support_judge.py` validated ~95% on `scripts/support_probes.json`; fact-check cards `docs/COHORT_REFERENCE_CARDS.md`. **Run on run1+2 (62 eps).** Map: `docs/README.md`; rationale: `docs/SUPPORT_JUDGE_PROMPT.md` |
| ~~Decision-point scorer (derived/recalled)~~ | **Superseded** — prototype produced run1+2 `_dpscores.json` (partition derived-rate g0 14%→g2 81%, cited in EXPLORE_EXPLOIT_SCORING). `score_decision_points.py` / `DECISION_POINT_RUBRIC.md` retained for history |
| Support scoring on run1+2 | **Done (2026-07-02)** — 62 eps scored; two axes orthogonal (support ≠ correctness), Sonnet grounds well, anchoring only under G3 mislead. "unwarranted recall common" did NOT hold for a frontier model → motivates the model ladder |
| Model ladder | **Ready (2026-07-07)** — provider adapters (`agents/adapters/`) run ONE identical agent across Sonnet/Opus/GPT-4.1/Gemini-flash (`--model` routes by prefix). Smoke-tested, parity confirmed (`reveal@RO=3` all 4). Full run: **48 eps/model** (G0 now 3 seeds), **~$1000 total** (Opus ~$720). Guide: `docs/MODEL_LADDER.md` |
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

1. **Rescore support track (144 eps)** with the upgraded judge → populate `recall_type`:
   `for d in gpt55_20260707 gemini25_ sonnet5_20260713; do python scripts/score_support.py results/tcga/ladder/$d --save --rescore; done`
2. **Validate the taxonomy** — hand-audit ~10–20 `recall_type` + D1/D3 `grounded` labels for judge-vs-human agreement; add a `recall_type` panel to `gen_report.py`
3. **Lean full runs** — GPT/Gemini/Sonnet G0/G1/G2 under `prompts/ablation/tcga_lean.txt` (scaffold-confound ablation), paired vs detailed
4. **Opus arm** — detailed + lean, last (cost driver ~$720+)
5. **Multi-judge robustness** — score a 15–20 ep subset with a 2nd judge; show the cross-model ranking is judge-stable
6. **Harden for production** — submit-time grouping validation; Anthropic adapter backoff
7. *(parked)* run7 OS benchmark; OS with WES/CNA once GSA HRA003260 granted; Task B systematic runs
