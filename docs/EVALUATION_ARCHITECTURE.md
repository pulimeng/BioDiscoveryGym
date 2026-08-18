# Evaluation architecture

*Authoritative description of how an episode is evaluated. Current as of 2026-08-18, after the
judge-panel redesign and the episode-layout reorganisation. Every claim here was verified against
the code in the session that wrote it; where something is asserted but unverified it says so.*

Companion docs: `METHODOLOGY.md` (experimental design), `SUPPORT_JUDGE_PROMPT.md` (the support
rubric), `COHORT_REFERENCE_CARDS.md` (the fact-check cards), `README.md` (index).

---

## 1. What gets evaluated

One **episode** = one agent, one cohort, one arm, one seed. The agent performs subtype discovery
over TCGA multi-omics through a fixed tool interface (`run_code`, `record_observation`,
`submit_discovery`), and everything it did is persisted to `<episode>.json`.

Evaluation produces **three artifacts per episode per judge**, from three different scorers that
answer three different questions:

| artifact | scorer | question | LLM involvement |
|---|---|---|---|
| `v3scores.json` | `score_tcga_episode.py` | *Is the discovery correct?* | **2 of 8** fields |
| `supportscores.json` | `score_support.py` + `support_judge.py` | *Was the claim warranted?* | **everything** |
| `cotsummary.json` | `summarize_cot.py` + `extract_cot.py` | *How did it reason?* | **everything** |

---

## 2. The information ladder

The independent variable is what contextual identity the agent is given. The molecular data is
identical across arms.

| arm | disclosed | role |
|---|---|---|
| G0 | cohort identity + real gene names | the known-recall anchor (construct validity) |
| G1 | real gene names, cohort hidden | intermediate |
| G2 | nothing; codebook arrives after the 3rd observation | the data-first condition |
| G3a | a **false** cohort label, planted at observation 3 | early false premise |
| G3b | a **false** cohort label, planted at observation 5 | late false premise |

**The G3 reveal fires on a counter of the agent's own `record_observation` calls, with no
call-count fallback.** An episode that submits before its Nth observation is never shown a label.
The outcome scorer then records `verdict != mislead_cohort`, which reads as "resisted". Any G3
rate must therefore be computed on the **exposed** denominator — see `scripts/g3_exposure.py`.
This is not a hypothetical: it invalidated two headline results.

---

## 3. What is computational and what is a model call

Six of the seven scored outcome components never touch a model:

| component | how scored |
|---|---|
| `structure_validity` | silhouette + bootstrap ARI (100 resamples) |
| `clinical_signal` | c-index, Cox log-HR |
| `genomic_coherence_drivers` | driver association, FDR |
| `reference_concordance` | NMI vs known subtype schemes |
| `marker_evidence` | one-vs-rest AUC, marker validity |
| `pathway_validity` | over-representation analysis |
| **`mechanism_grounding`** | **LLM judge** |
| **`cohort_identity` (gate)** | **LLM judge** — not one of the seven, but decides `true_cohort` / `mislead_cohort` / `hedged` |

**The identity gate is the false-label adoption result.** The headline robustness number is a
single model call per episode, even though the score it gates is 6/7 deterministic.

The computational components are **seeded** (`seed=42`, seeded RNG) and reproduce bit-identically —
verified over three runs. Per-judge `v3scores.json` files therefore differ *only* in the two
LLM-derived fields, which is what makes them comparable across judges.

---

## 4. What each judge actually sees

Verified by reading the extractors. **No judge reads the filesystem.** All three parse
`<episode>.json` only.

### CoT judge — `cotsummary.json`
Input assembled by `extract_cot.py`:
- `run_code` **`# WHY:` / `# EXPECTS:`** headers — stated intent per step
- `record_observation` inputs — hypothesis, evidence_for/against, alternatives, confidence
- the final submission
- derived sections: stage usage, stage skips/regressions, G2 clinical-metadata leak channel,
  gene-frequency and k distributions

**Deliberately excluded:** provider *thinking* (measured 0% across all models — extended thinking
is off, so Sonnet emits empty shells) and assistant free-text. That exclusion is the
model-asymmetry guard: Sonnet writes ~27k words of free text, GPT and Gemini ~none, so including
it would score prose volume.

### Support judge — `supportscores.json`
Input assembled by `score_support.extract_trace` + `support_judge.build_user_msg`:
```
COHORT REFERENCE CARD (fact-check only — NOT an answer key)
TRACE:
  RUN_CODE # WHY: headers, in order
  record_observation hypotheses, in order
  SUBMITTED subtype labels / top genes / mechanism
```
It is the **only** judge given an external document, so it can fact-check biology rather than
judge plausibility. It emits `strategy` (explore/exploit/mixed) and `support`
(grounded/unsupported/anchored) at three decisions: D1 partition, D2 identity, D3 mechanism.

`support_score` is arithmetic over those labels (`SUPPORT_POINTS × WEIGHTS`) — there is no
independent measurement in it.

### Outcome judge — `v3scores.json`
Two narrow calls, no trace at all:
```
score_mechanism_grounding(mechanism_hypothesis, pathway_evidence, top_genes)
score_cohort_identity(mechanism_hypothesis, subtype_labels, true_cohort, mislead_cohort)
```

### The gap this creates — read before interpreting "grounded"

**No judge sees any verified output.** Not the agent's saved files, and not the `tool_result`
text either:

- `extract_cot.py` *has* a `_extract_stats` regex that pulls `p=`, `HR=`, `AUC=`, `silhouette=`
  from tool results — but it renders only in a detail mode `summarize_cot.py` does not use.
  Measured: **0 `→ stats` lines** in the actual judge input across sampled episodes. It is dead
  code, not a verification path.
- `score_support.extract_trace` reads only `b["input"]` of tool_use blocks — **zero** tool output.

The judge input is dense with numbers, but they live inside `record_observation.evidence_for`,
i.e. **the agent's own report of what its code produced**. An agent that wrote `p=9.7e-196` when
the true value was `p=0.4` would score identically.

> `support = "grounded"` currently means *"the agent narrated a data-derived rationale"*, not
> *"the claim was checked against the data."* Same for `identity_derivation = data-derived`.

This belongs in the paper's limitations, and it is a live confound for model comparison: verbose
self-reporters look better-grounded for stylistic reasons. See §7.

---

## 5. The judge panel: one pass, three families

Replaced the previous 3-passes-of-one-model panel.

```
old:  3 x nemotron           -> judge self-consistency        (stochasticity)
new:  nemotron/laguna/qwen   -> do independent families agree? (cross-family robustness)
```

The new axis is the one a reviewer challenges. **The trade is real and must be stated:** with one
pass per judge, judge *noise* and judge *disagreement* are no longer separable, and cross-family
exact agreement was only ~67% on the n=42 pilot check — so expect materially more no-consensus
episodes than the 3-pass design produced.

`judges_config.consensus()` returns `None` for a 1/1/1 split. **`None` is a result, not a missing
value**: it means the construct is not robustly measurable for that episode. Callers must count
and report them. Folding them into a majority, or dropping them, both overstate agreement and
quietly turn the panel into a filter that keeps only the easy episodes.

| tag | model | host | neutral? |
|---|---|---|---|
| `nemotron` | `nemotron-3-super` | bifrost gateway | yes — not a benchmarked family |
| `laguna` | `laguna` | bifrost gateway | yes |
| `qwen` | `Qwen/Qwen3.6-27B-FP8` | AIE serving platform (separate host) | yes |

Routing lives in **one** table — `biodiscoverygym/scoring/judge.py::judge_provider` — matched by
**substring, not prefix**. Gateways advertise vendor-qualified ids (`AI-Workstation/nemotron-3-super`
is what `/v1/models` returns), and under prefix matching those fell through to the OpenAI default:
the run completes, files are well-formed, and the "neutral" judge was silently GPT — a benchmarked
family. `is_benchmarked_family()` now warns at all four entry points.

The Qwen host's root CA (`AIE Root CA`, HPE Ezmeral) is in no trust store and the host sends only
its leaf with no AIA URL, so TLS verification is **disabled for that host only**, by explicit
decision, in `openai_client_for()`. Every other provider still verifies. `BDG_QWEN_VERIFY=1`
restores it.

---

## 6. Episode layout and provenance

```
<episode>/
  <stem>.json .md .log                    harness — the trace
  codebook.json gene_map.json grouping*.json   harness — inputs/submission
  outputs/                                AGENT — everything it wrote (csv, png, result dirs)
  scoring/
    v3trace.json                          derived, judge-INDEPENDENT (no model call)
    <judge>/cotsummary.json
    <judge>/supportscores.json
    <judge>/v3scores.json
```

Three provenances used to share one namespace, which forced episode discovery to be a glob plus a
blocklist of substrings guessed to appear in non-episode filenames. Agents invent names that guess
does not cover (`grouping_stage2.json`, `proposed_grouping.json`, `grouping_stage2_blinded.json`
all exist). **A directory boundary replaces a guess with a fact.**

`v3trace.json` sits at the scoring root, not under a judge: it is pure trace statistics with no
model call, and filing it under a judge would imply otherwise.

**Provenance is recorded in every artifact.** Before this, `_supportscores.json` carried
`judge_model: None` in all 570 files and `_v3scores.json` had no such field at all, while report
generators inferred the run's judge by reading the *CoT* summaries — a different artifact, possibly
a different model. Each artifact now records `judge_model` at the point of use; the outcome file
also records `llm_components`, naming which of its fields are model-derived.

Pre-panel artifacts were tagged `unrecorded`, **not** `nemotron`: they were almost certainly
nemotron (the default since `24bc72e`, which precedes the clean run), but nothing in them says so,
and an inferred value is not a recorded one.

---

## 7. Known asymmetries and confounds

These are properties of the instrument, not of the models. Report per model; never pool.

1. **Free text** — Sonnet ~27k words/episode, GPT and Gemini ~none. *Excluded* from judge input.
2. **Saved files** — GPT 728 CSVs and 37 PNGs; Sonnet **0** CSVs and 120 PNGs; Gemini 637 PNGs.
   A 7× volume spread and a modality split. *Excluded* from judge input. Including them would
   reward house style, and 637 of Gemini's are images no text judge can read.
3. **Quantitative narration** — numeric claims per episode: GPT ~203, Sonnet ~60, **Gemini ~9**.
   A **22× spread**, and this one is *not* excluded: it is the entire support-judge input. A
   grounding judgement made from 9 numbers is not the same measurement as one made from 203.
   This is a candidate mechanism for Gemini's `not-established` rate (20/42 on G2), which is
   currently carried as an unexplained caveat.
4. **Gemini is a generation behind** (2.5 Pro; 3.1 Pro and 3.5 Flash could not complete a run),
   confounding vendor with generation.
5. **Judge asymmetry** — the support judge gets a fact-check card; the outcome identity gate gets
   none, so the gate judges cohort identity purely on the model's own knowledge.

---

## 8. Verification layer (deterministic, no LLM) — planned

Addresses §4's narration-vs-verification gap *without* changing the judge instrument. Extracts
numeric assertions from `record_observation.evidence_for/against` and matches them against floats
in the `tool_result` blocks (2% relative tolerance for formatting).

Feasibility measured on sampled G2 episodes:

| lane | numbers claimed | matched | fidelity |
|---|---:|---:|---:|
| GPT-5.5 | 1627 | 1470 | 90% |
| Sonnet 5 | 422 | 366 | 87% |
| Gemini 2.5 Pro | 74 | 68 | 92% |

Agents mostly report real numbers; fabrication is not rampant. Two caveats the tool must state in
its own output: a 2% tolerance produces false matches on common values (`0.05`, `1.0`), and an
agent may narrate a number computed in an earlier call — so **unmatched means unverified, not
fabricated**.

Home: `cot_deepdive.py`, which needs rework regardless (its stated H1/H2 are both retracted).

---

## 9. Running it

```bash
export BDG_RUNS=clean BDG_JOBS=6
source load_keys.sh "<keys.txt>"

scripts/run_judge_panel_v2.sh              # all judges x all artifacts, resume-safe
scripts/run_judge_panel_v2.sh qwen         # one judge
python scripts/panel_status.py             # coverage gate; non-zero exit until complete
```

Judges run **sequentially** by design: nemotron and laguna share one bifrost gateway that is
demonstrably capacity-limited (Gemini 3.1 Pro returned 503 on a 1-token preflight there; Gemini 3.5
Flash was abandoned at 60/95). Qwen is a separate host, so a qwen lane may safely run alongside a
bifrost lane.

### Integrity gates
| gate | checks |
|---|---|
| `panel_status.py` | every judge × artifact × episode present; exits non-zero otherwise |
| `audit_blinding.py` | no cohort identity reachable from agent-visible text |
| `audit_integrity.py` | no path-derived identity reasoning |
| `check_judge_integrity.py` | judge outputs schema-valid, no silent partial validation |
| `check_judge_symmetry.py` | comparable process evidence across models |
| `g3_exposure.was_exposed()` | required denominator for any G3 rate |
| `remove_stale_judges.py` | refuses unless backup exists, panel complete, readers migrated |

**A panel that is 97% complete is not a panel.** The missing episodes are not random — they are the
ones whose traces break a judge — so analysing around them changes the denominator without saying so.

---

## 10. Outstanding

- **27 reader scripts still expect the pre-reorg flat filenames.** They do not fail loudly: most
  glob, find nothing, and report empty tables and zero denominators as though that were the result.
  This is the gating item before `remove_stale_judges.py` will run.
- The analysis layer assumes 3-passes-of-one-model (`explore_exploit.py` still reads
  `[_cotsummary, _j2, _j3]`); it must be taught the panel, including how to report no-consensus.
- `check_judge_symmetry` currently **fails**: 3 Gemini-lean episodes logged zero observations.
- The verification layer (§8) is designed and feasibility-tested, not built.
