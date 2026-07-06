# Model Ladder — running the benchmark across providers

Run the **identical** agent (same prompt, tools, loop, codebook-reveal timing) on multiple
model providers, so any difference is the *model*, not the scaffolding. One agent
(`agents/cohort_agent.py`) + provider adapters (`agents/adapters/`); the model id picks the
adapter automatically.

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
| Google | `gemini-2.5-pro` | thinking auto-disabled by the adapter; **2.5 Pro has a ~128-token floor** — can't be *fully* off (footnote it). Use `gemini-2.5-flash` for zero-thinking, at a lighter tier. |

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

`run_tcga.sh` already takes `--model`, so run the full cohort × seed × arm set per model:

```bash
bash scripts/run_tcga.sh --model claude-sonnet-4-6 --tag ladder_sonnet
bash scripts/run_tcga.sh --model claude-opus-4-8   --tag ladder_opus
bash scripts/run_tcga.sh --model gpt-4.1           --tag ladder_gpt41
bash scripts/run_tcga.sh --model gemini-2.5-pro    --tag ladder_gemini
```
Then score each with both tracks (see `docs/README.md`):
```bash
python scripts/score_tcga_episode.py <ep> --cohort <C> --save   # outcome  -> _v3scores.json
python scripts/score_support.py results/tcga/ladder_<m> --save   # support  -> _supportscores.json
```
The paper figure is the **outcome × support cross-tab per model** — does the top-right cell
(correct-but-unwarranted) fill for weaker models and stay empty for stronger ones?

## 5. Parity checklist (what must be equal across models)

- ✅ prompt / tools / loop / codebook-reveal gate — shared by construction (one agent)
- ✅ reasoning off — Claude budget 0, GPT-4.1 has none, Gemini budget 0 (Pro floor noted)
- ✅ **output-token cap uniform** — the agent requests 32k/turn and every adapter's ceiling is
  ≥ that (Anthropic 64k, OpenAI 32768 for gpt-4.1, Gemini 65536), so all four get a uniform
  32k output cap. (If you swap to `gpt-4o`, lower `OpenAIAdapter.max_output_cap` to 16384.)
- ⚠️ verify `reveal@RO` matches in the smoke output before the full run.

## Cost

Rough order (63 eps × ~100 calls): **Opus / o-series most expensive**, `gpt-4.1` and Gemini
mid/cheap. Estimate per model and load each account before the full run; the smoke is cents.
