# Model Ladder — running the benchmark across providers

Run the **identical** agent (same prompt, tools, loop, codebook-reveal timing) on multiple
model providers, so any difference is the *model*, not the scaffolding. One agent
(`agents/cohort_agent.py`) + provider adapters (`agents/adapters/`); the model id picks the
adapter automatically.

**Status (2026-07-07): smoke-tested, parity confirmed** across Sonnet / Opus / GPT-4.1 /
Gemini-2.5-flash — all four fire the G2 codebook at the *same* record_observation turn
(`reveal@RO=3`) and submit a discovery. Cleared for the full ladder. Smoke: `smoke_ladder.sh`.

## 1. Setup (once)

```bash
pip install anthropic openai google-genai
```
Put your keys in `keys.txt` (gitignored, one per line) then source the loader:
```
# keys.txt
Anthropic:sk-ant-...
OpenAI:sk-proj-...
Gemini:AIza...
```
```bash
source load_keys.sh     # exports ANTHROPIC_API_KEY / OPENAI_API_KEY / GEMINI_API_KEY(+GOOGLE_API_KEY)
```
Keys are per-provider (separate billing). Anthropic you already have. `load_keys.sh` holds no
secrets (committable); `keys.txt` is gitignored — never commit it.

## 2. Models (matched frontier tier, reasoning OFF)

| Provider | Model id | Notes |
|---|---|---|
| Anthropic | `claude-sonnet-4-6` | thinking off (`--thinking-budget 0`, the default) |
| Anthropic | `claude-opus-4-8` | thinking off |
| OpenAI | `gpt-4.1` | non-reasoning flagship (the clean pair; `o3` is a *reasoning* model → separate axis) |
| Google | `gemini-2.5-flash` | **2.5 Pro REJECTS thinking-off** (`400: Budget 0 is invalid; this model only works in thinking mode`) — confirmed. For a thinking-off ladder you MUST use **`gemini-2.5-flash`** (accepts budget 0), a lighter tier than Opus. To keep 2.5 Pro, run it as a separate *thinking-on* arm (footnote that one model reasons). |

Confirm exact ids against each provider's current docs when you make the keys — names churn.

## 3. Smoke test FIRST (cheap — do not skip)

```bash
bash scripts/smoke_ladder.sh
```
One G2 BRCA/seed-42 episode per model (skips providers with no key). It prints a parity table:

- **`reveal@RO` must be the SAME across models** — the gene codebook reveals on a deterministic
  record_observation gate; if a provider reveals at a different turn (or `none`), its
  tool-call cadence differs and the comparison is confounded. Fix the adapter before spending.
- Every model should **submit** a discovery and use `record_observation`.

Gemini is the one to watch (matches tool responses by name, not id; finickier function calling).

## 4. Full ladder

`run_tcga.sh` takes `--model` and a nested `--tag`, so each model's 48 episodes land grouped
under `results/tcga/ladder/<model>_<date>/` (analysis is then `for m in results/tcga/ladder/*/`):

```bash
D=$(date +%Y%m%d)     # ONE date per campaign — reuse the SAME tag to resume (see note)
bash scripts/run_tcga.sh --model claude-sonnet-4-6 --tag ladder/sonnet_$D
bash scripts/run_tcga.sh --model gpt-4.1           --tag ladder/gpt41_$D
bash scripts/run_tcga.sh --model gemini-2.5-flash  --tag ladder/gemini_$D
# bash scripts/run_tcga.sh --model claude-opus-4-8 --tag ladder/opus_$D   # parked (cost)
```
Episode dirs are **label-named** (`.../ladder/gpt41_20260707/g2_brca_s42/…`), not uuids.
`run_tcga.sh` scores each episode as it goes (both tracks) and is **resume-safe** — re-run
the *same tag* to continue. **Note:** the timestamp versions a campaign; to resume across days,
hardcode the date (`--tag ladder/gpt41_20260707`) rather than `$(date)`, which would roll to a
new dir. To (re)score a whole model dir: `python scripts/score_support.py results/tcga/ladder/<dir> --save`.

The paper figure is the **outcome × support cross-tab per model** — does the top-right cell
(correct-but-unwarranted) fill for weaker models and stay empty for stronger ones?

### Results layout (all under gitignored `results/`)
```
results/tcga/
├── ladder/<model>_<date>/<label>/   episode.json + .md + _v3scores + _supportscores + artifacts
│                                     (label dirs, e.g. gpt41_20260707/g2_brca_s42/)
├── run1+2/                          canonical Sonnet pilot (62 eps, keep)
├── _archive/                        superseded runs (run1, run2, mech_ab_*)
└── _smoke/                          smoke tests (smoke_ladder, smoke-test)
```

## 5. Parity checklist (what must be equal across models)

- ✅ prompt / tools / loop / codebook-reveal gate — shared by construction (one agent)
- ✅ reasoning off — Claude budget 0, GPT-4.1 has none, Gemini budget 0 (Pro floor noted)
- ✅ **output-token cap uniform** — the agent requests 32k/turn and every adapter's ceiling is
  ≥ that (Anthropic 64k, OpenAI 32768 for gpt-4.1, Gemini 65536), so all four get a uniform
  32k output cap. (If you swap to `gpt-4o`, lower `OpenAIAdapter.max_output_cap` to 16384.)
- ⚠️ verify `reveal@RO` matches in the smoke output before the full run.

## Cost & runtime estimate

**48 episodes/model** (G0×12 + G1×12 + G2×12 + G3a×6 + G3b×6; all of G0/G1/G2 = 4 cohorts ×
3 seeds), ~100 tool calls each. Estimates below are order-of-magnitude — verify against your
first few real episodes.

| Model | ~$/episode | ~$/48 eps | ~wall/episode | Notes |
|---|---|---|---|---|
| `claude-sonnet-4-6` | ~$3 | **~$145** | ~15–30 min | slow (many turns) |
| `claude-opus-4-8` | ~$15 | **~$720** | ~8–15 min | **the cost driver (~65% of the ladder)** |
| `gpt-4.1` | ~$2 | **~$95** | ~5–10 min | fastest, cheapest-per-token flagship |
| `gemini-2.5-flash` | ~$1 | **~$48** | ~15–25 min | cheap tokens but big context + retries → slow |
| **Full ladder** | | **~$1000** | | Opus dominates cost; Sonnet/Gemini dominate wall-time |

**Levers if that's too much:**
- **Drop Opus** → ~$250 for the other three (Opus is ~$600 alone).
- **`--no-g3`** → 36 eps/model instead of 48 (skips the mislead arms) → ~25% cheaper.
- Run Opus on **1 seed** (G1/G2 → 4 eps each instead of 12) if you only need a point estimate.

Runtime is serial and long (a full model = ~10–20 hr wall). Run models/arms in separate
terminals to parallelize, and `run_tcga.sh` is resume-safe (skips already-completed episodes).

## Provider notes (adapter behavior)

- **Gemini** delivers the system prompt as the first *user* turn (not `system_instruction`)
  and forces tool calls (`mode=ANY`) with a retry-on-malformed loop — a long
  `system_instruction` otherwise triggers `MALFORMED_FUNCTION_CALL`. Same prompt text as the
  other models (no parity break); it just costs Gemini extra calls/latency. Gemini matches
  tool responses by name (no call id).
- **Output cap** is a uniform 32k across all four (adapters raise their ceilings to ≥ that).
