# Model Ladder — running the benchmark across providers

Run the **identical** agent (same prompt, tools, loop, codebook-reveal timing) on multiple
model providers, so any difference is the *model*, not the scaffolding. One agent
(`agents/cohort_agent.py`) + provider adapters (`agents/adapters/`); the model id picks the
adapter automatically.

**Status:** the harness is proven — parity was smoke-confirmed (2026-07-07) on the *previous*
model set (Sonnet 4.6 / Opus 4.8 / GPT-4.1 / Gemini-2.5-flash): all fired the G2 codebook at
the same turn (`reveal@RO=3`) and submitted. Model list now updated to current, reasoning =
**default (as-deployed)**. **Re-run `smoke_ladder.sh` on the new models before the full ladder.**

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

## 2. Models (current as of 2026-07; reasoning = DEFAULT / as-deployed)

**Running now** (this ladder):

| Provider | Model id | Notes |
|---|---|---|
| Anthropic | `claude-sonnet-5` | replaced Sonnet 4.6 (2026-06-30). `effort` defaults high (runs at default). |
| OpenAI | `gpt-5.5` | current flagship (`gpt-5.5-2026-04-23`). Reasoning model — runs at default reasoning_effort. |
| Google | `gemini-3.5-flash` | **Flash tier — a deliberate tier downgrade, see the caveat below.** Smoke-passed (submits, grouping 1095). Default thinking; thought_signature round-tripped; adapter logs + backs off on transient 503/429. |

> **⚠️ TIER CAVEAT — Gemini is a Flash tier; the others are flagship (decided 2026-07-16).**
> Disclose this wherever Gemini appears. It is a known, accepted asymmetry, not an oversight.
>
> **Why:** `gemini-2.5-pro` — the parity-correct choice, and what the retired 4-cohort ladder in
> `results/tcga/ladder0/gemini25_` actually ran (48 eps @ 4.7 min median) — began returning
> sustained `503 ... high demand`: *server-side overload, not a quota 429*, so no key upgrade
> fixes it. Episodes could not complete (the adapter slept in backoff at 0% CPU). Flash unblocked
> the run.
>
> **Mitigating — why `gemini-3.5-flash` and not `gemini-2.5-flash`:** 3.5 is **Flash-only** —
> `gemini-3.5-pro` returns 404, it does not exist. So 3.5-flash is the *top of its own family*,
> not a cheap variant sitting below a Pro. "We ran the newest Gemini model Google ships; there is
> no Pro in that generation" is materially stronger than "we used Flash because Pro was busy."
> This **blunts the tier objection — it does not eliminate it.** A Flash model is still distilled,
> and a reviewer may fairly say it isn't comparable to GPT-5.5.
>
> **Consequence — do not paper over this:** a Gemini deficit vs GPT-5.5/Sonnet-5 remains
> **confounded by tier** and must not be attributed to the model family.
>
> **Smoke evidence (2026-07-16, G2/BRCA/s42, n=1 each — qualitative, not a measurement):**
> both Flash models passed parity (`reveal@RO=3`, both submitted). 3.5-flash ran **40 run_code**
> calls and recovered canonical BRCA structure (ESR1/GATA3/FOXA1 luminal, ERBB2, CDC20/CENPA
> proliferation → luminal/luminal/basal-TP53/normal-like). 2.5-flash ran **7** and returned
> generic cancer boilerplate (KRAS/EGFR/TWIST1/VIM EMT vocabulary — not BRCA subtype drivers) at
> `confidence: high` — i.e. answering from priors with minimal data engagement, the exact failure
> this benchmark exists to detect. 3.5-flash also absorbed 2× transient 503 at attempt 1/6.
>
> **To restore parity later:** re-run `--model gemini-2.5-pro --tag ladder/gemini25pro_<date>`
> when demand drops, and use Pro as the headline number. No code change needed.

**Parked — production tier** (not running now, but keep in the ladder; add with `--tag ladder/<m>_<date>`):

| Provider | Model id | Notes |
|---|---|---|
| Anthropic | `claude-opus-4-8` | production Opus; ~$720/48 eps (the cost driver). `effort` defaults high. |
| Anthropic | `claude-fable-5` | current **top tier** (above Opus, $10/$50); the true flagship if production uses it. |

Adding a parked model later is just another `run_tcga.sh --model <id> --tag ladder/<name>_<date>`
— the adapter routes it, results slot into `ladder/`. No code change.

> **Reasoning policy: DEFAULT (as-deployed).** The frontier is reasoning-first; we run each
> model at its **own default reasoning** (Claude `effort` high, GPT-5.5 default, Gemini
> adaptive) rather than forcing minimal. Rationale: **more reviewer-proof** — "each model as
> its provider ships it," which pre-empts the "you handicapped them by disabling reasoning"
> objection. Reasoning is a property of the model, not a confound we introduced. The adapters
> set **no** reasoning params. Cost is **~2–4× the figures below** (reasoning tokens billed as
> output). Watch for output truncation at the smoke — heavy default reasoning can eat the 32k
> output budget before the tool call; if so, raise the agent `max_tokens`.

**Use the newest variant per family.** The ids above are unversioned aliases → they already
resolve to the latest snapshot within a family. For the latest *family* (names churn — a
newer one may have shipped), list what your keys can actually see and pick the top:
```bash
python -c "import anthropic;[print(m.id) for m in anthropic.Anthropic().models.list()]"
python -c "import openai;[print(m.id) for m in openai.OpenAI().models.list()]"
python -c "from google import genai;[print(m.name) for m in genai.Client().models.list()]"
```
Any newer id just goes in `--model` — the adapter routes by prefix (`claude*` / `gpt*`/`o<n>`
/ `gemini*`), so `gpt-5`, `o5`, `gemini-3.0-pro`, `claude-opus-4-9` all work with no code change.

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
bash scripts/run_tcga.sh --model claude-sonnet-5  --tag ladder/sonnet5_$D
bash scripts/run_tcga.sh --model gpt-5.5          --tag ladder/gpt55_$D
bash scripts/run_tcga.sh --model gemini-3.5-flash --tag ladder/gemini35flash_$D
# bash scripts/run_tcga.sh --model claude-opus-4-8 --tag ladder/opus_$D   # parked (cost)
```
Episode dirs are **label-named** (`.../ladder/gpt41_20260707/g2_brca_s42/…`), not uuids.
`run_tcga.sh` runs **episodes only — it does NOT score** (its own header says so; score separately
with `scripts/score_run.sh`, or `scripts/score_support.py <dir> --save` for a whole model dir).
An unscored ladder dir is therefore expected, not a symptom. It is **resume-safe** — re-run
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
- ✅ **reasoning = default (as-deployed)** — each model at its own default; intentional, not forced (see §2). Reasoning is a model property here, not a confound.
- ✅ **output-token cap uniform** — the agent requests 32k/turn; adapter ceilings are ≥ that
  (Anthropic 64k, OpenAI 32768, Gemini 65536) → uniform 32k. (Reasoning tokens count against
  output — **default reasoning can eat the 32k budget**; raise agent `max_tokens` if truncating.)
- ⚠️ verify `reveal@RO` matches in the smoke output before the full run.
- ❌ **model tier is NOT equal — Gemini runs Flash, the others run flagship** (see the tier
  caveat in §2). This is the one knowingly-broken item on this checklist. It was forced by
  sustained `503 high demand` on `gemini-2.5-pro`, and it means a Gemini deficit is confounded
  by tier. Report the tier wherever Gemini appears; re-run on Pro to close it.

## Cost & runtime estimate

**48 episodes/model** (G0×12 + G1×12 + G2×12 + G3a×6 + G3b×6; all of G0/G1/G2 = 4 cohorts ×
3 seeds), ~100 tool calls each. The table is a MINIMAL-reasoning baseline; **we run DEFAULT reasoning, so budget ~2–4× these**
(reasoning tokens billed as output × ~100 turns/episode). Order-of-magnitude; verify on your
first few real episodes.

| Model | ~$/episode | ~$/48 eps | ~wall/episode | Notes |
|---|---|---|---|---|
| `claude-sonnet-5` | ~$3 | **~$145** | ~15–30 min | slow (many turns) |
| `claude-opus-4-8` | ~$15 | **~$720** | ~8–15 min | **the cost driver (~65% of the ladder)** |
| `gpt-5.5` | ~$2 | **~$95** | ~5–10 min | fastest, cheapest-per-token flagship |
| `gemini-3.5-flash` | ~$1? | **~$48?** | ~20 min (measured, smoke) | Flash tier — **not flagship-parity** (see tier caveat, §2). 40 run_code/ep; occasional transient 503, self-recovers at attempt 1/6 |
| **Full ladder** | | **~$1000** | | Opus dominates cost; Sonnet dominates wall-time |

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
