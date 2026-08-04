# Data-integrity audit — 2026-07-28, extended 2026-08-04

**Reproduce:** `python scripts/audit_integrity.py --json manuscript/figures/integrity_audit.json`
(exits 1 if any identity gate errored, so it can gate a release).

Three defects, none visible in any report — that is what makes them dangerous. One silently
weakens a headline metric; one silently fabricates a zero that was then read as a finding; one
would have silently swapped the cohort an episode analysed.

Defects 1 and 2 were found by reading individual episodes rather than aggregates, prompted by an
external review pass. Of its three claims, one was real and understated, one was wrong, one was
already fixed. The most serious problem was found while checking the claim that was wrong —
recorded here so the audit's own provenance is honest.

Defect 3 was found at launch on 2026-08-04, by crashing. It produced no data and is fixed.

---

## Defect 1 — the "blinded" arm leaks the cohort through `output_dir`

> **STATUS: FIXED IN CODE 2026-08-03 (commit 48d1db0). PILOT DATA REMAINS CONTAMINATED.**
>
> Two separate facts, and conflating them would be a serious error:
> - **The harness is fixed.** Future runs are clean. `episode.py` now runs the agent in an opaque
>   working directory (`base/_work/<uuid12>`) and relocates artifacts into the real episode
>   directory afterwards, in a `finally` block so a crashed episode still keeps its output. `base`
>   is deliberately left intact — model, date and prompt arm are not hidden from the agent anyway;
>   only the episode label was identity-bearing.
> - **The existing 450 episodes are still leaked.** No code change can retroactively unsee what the
>   agent read. Every G2/G3 number from the pilot campaign stays provisional until the clean rerun.
>   That rerun is the whole point of `manuscript/PLAN.md`.
>
> **Gate for any future run:** `python scripts/audit_blinding.py <run_dir>` must exit 0. It asserts
> that nothing the *harness* showed the agent reveals identity, and is arm-aware — G0 discloses the
> true cohort and G3 a false one by design, so cohort checks are suppressed where disclosure is
> definitional while plumbing checks (episode label, results path, arm token, arm+seed, the word
> `mislead`) apply to every arm. Validated against known-bad data: **422/450 pilot episodes fail**.

### Mechanism (structural, not incidental)

- [`biodiscoverygym/executor.py:258`](../biodiscoverygym/executor.py#L258) injects `output_dir` into
  the namespace the agent's code runs in.
- [`agents/cohort_agent.py:152`](../agents/cohort_agent.py#L152) **instructs** the agent to use it:
  *"Save with: `json.dump(grouping_dict, open(output_dir / 'grouping.json', 'w'))`"*.
- `output_dir` resolves to `results/tcga/<arm>/<run>/g2_lihc_s42` — **the cohort name is in the
  path**, on the arm whose entire purpose is that the cohort is unknown.

So on G2 the agent can read the answer out of its own working directory. This is a design flaw, not
a model behaviour.

### Extent (G2, the blinded arm)

| arm | path visible | **reasoned from** |
|---|---:|---:|
| GPT-5.5 / detailed | 21/21 | 1/21 |
| GPT-5.5 / lean | 21/21 | 0/21 |
| Sonnet 5 / detailed | 19/21 | 3/21 |
| Sonnet 5 / lean | 15/21 | 7/21 |
| Gemini 3.5 Flash / detailed | 21/21 | 17/21 |
| Gemini 3.5 Flash / lean | 21/21 | 17/21 |
| **TOTAL** | **118/126** | **45/126** |

The two columns mean different things and must not be conflated. *Path visible* is near-universal
simply because saving a file echoes its path; that alone corrupts nothing. **Reasoned from** — the
agent's own WHY/observation text invoking the directory — is what can corrupt an
`identity_derivation` label. Verbatim:

> *"Output directory path contains 'ucec' confirming endometrial carcinoma cohort"* — Sonnet 5, detailed, `g2_ucec_s42`

> *"confirming this is a lung cancer cohort (output_dir name confirms 'lusc')"* — Sonnet 5, detailed, `g2_lusc_s123`

### What it does and does not threaten

**Does NOT threaten the between-arm deltas**, contrary to the review's claim that it contaminates
GPT's +38 lean effect:
- GPT: 1 detailed vs 0 lean — essentially absent, so **+38 stands**.
- Gemini: 17 vs 17 — identical across arms, so the delta **cancels**.
- Sonnet: 3 vs 7 — the only asymmetry, and it runs *against* its −19 counter-case rather than
  manufacturing it.

**Does threaten the absolute derivation rates.** On an episode where identity came from the folder
name, "data-derived" does not mean what the paper says it means. Up to 45/126 G2 episodes are
affected, concentrated in Gemini.

### Required actions

1. **Fix upstream:** do not expose a cohort-bearing path. Give the executor a neutral working dir
   (e.g. `output_dir = <tmp>/episode`) and map it back outside the agent's view. **Until this is
   fixed every future blinded run inherits the defect.**
2. **Paper:** report absolute G2 derivation rates with leaked episodes excluded as a sensitivity
   analysis, and state the leak in Limitations. Deltas can be reported as-is with a footnote.
3. A blinded re-run is the only way to recover clean absolute rates.

---

## Defect 2 — a failed scoring run, silently rendered as legitimate scores

**RESOLVED 2026-07-29** by re-scoring 78 episodes. Pre-repair scores preserved in
`results/tcga/_rescore_backup_20260728/`.

**This defect was initially UNDER-REPORTED as 12 episodes / G3-only.** The first audit scanned only
`g3*`. Scanning all arms found **78 episodes**, including the *entire* 75-episode Gemini-lean run.
The under-count is recorded rather than quietly corrected, because the lesson is the same one the
defect teaches: scoping an audit to where you expect the problem is how you miss its real extent.

### Mechanism

A DeepSeek `402 Insufficient Balance` failed the LLM-judged parts of a scoring run. **Two
components broke, not one:**

1. `cohort_identity_verdict` recorded `verdict: "error"`.
2. **`mechanism_grounding` scored `0.000`** — on all 75 Gemini-lean episodes. After re-scoring:
   **0.968**.

Neither failure raised. Both rendered as values a consumer would accept. For the gate, every
consumer computes:

```python
fooled = (verdict == "mislead_cohort")
```

An errored gate is therefore **indistinguishable from a model that resisted the mislead**. Failure
is scored as success.

### Extent — 78 episodes, all arms

```
run                              errored    of
ladder/gemini35flash_20260716          0    75
ladder/gpt55_20260707                  0    75
ladder/sonnet5_20260713                1    75
lean/gemini35flash_20260722           75    75   <-- ENTIRE RUN
lean/gpt55_20260721                    0    75
lean/sonnet5_20260722                  2    75
TOTAL                                 78   450
```

The gate only zeroes narrative dimensions when `fooled` is set ([evaluator_v2.py:289](../biodiscoverygym/scoring/evaluator_v2.py#L289)).
On error `fooled` is never set, so **no gating occurred** — Gemini-lean was scored under a *more
lenient* regime than every other arm, while simultaneously losing `mechanism_grounding` entirely.

### Consequences after repair

**(a) A HEADLINE FINDING IS RETRACTED.** *"Gemini Flash collapses under lean (0.511→0.361), the small
model depends on the staged scaffold"* was **an artifact of the failed API call** — the 0.361 came
from `mechanism_grounding = 0.000`. Repaired:

| model | detailed | lean | Δ |
|---|---:|---:|---:|
| GPT-5.5 | 0.495 | 0.492 | −0.003 |
| Sonnet 5 | 0.506 | 0.482 | −0.024 |
| Gemini Flash | 0.511 | **0.500** | −0.011 |

**Outcome is prompt-invariant across all three models**, mean |Δ| = 0.013. The replacement finding
is simpler and stronger, but the "small models need scaffolding" story is gone. **Do not reinstate
it.**

**(b) "Staged prompt → more fooled" is RESTORED to 3/3**: GPT 11→5, Sonnet 8→4, Gemini **5→2**.

**(c) H2 is stronger and needs no exclusions** — complete n=72: **21% vs 67%**, Fisher **p=0.0001**,
OR=0.13 (was 21%/63% with errors miscounted as not-fooled).

**(d) H1 flipped sign, conclusion unchanged**: derived 0.483 vs recalled **0.524**, p=0.19; ordinal
ρ=−0.067, p=0.46. The point estimate now mildly favours *recall*. Claim **"no detectable
relationship in either direction"** — not "derived scores higher", which the pre-repair draft said.

### Required actions

1. ~~Re-score~~ **DONE** — 78 episodes re-scored 2026-07-29; all 450 gates now scored
   (`true_cohort` 397, `mislead_cohort` 35, `hedged` 11, `other` 7, **error 0**).
2. **Guard applied:** `cot_deepdive.py` excludes errored gates and prints the count.
3. **DONE 2026-07-29 — the class of bug is closed.** Both `score_tcga_episode.py` and
   `score_sghos_episode.py` now scan `report.diagnostics` for an `error` key after scoring and, if
   any component failed, **refuse to write a score file and exit non-zero**.

   The discriminator was already in the data and simply unread: a legitimate zero carries
   `{"reason": ...}` (e.g. *"no hypothesis submitted"*), a failure carries `{"error": ...}`. Only
   the latter now blocks the save, so genuine zeros still score normally.

   `score_all_tcga.sh` already collected failures and instructed the user to re-run — **that safety
   net existed the whole time and was bypassed only because scoring exited 0 with a fabricated
   number.** The guard lets it work. Verified against the preserved pre-repair scores: it fires on
   both `mechanism_grounding` and `cohort_identity` for the 402, so all 78 episodes would have been
   marked FAILED and fixed by one re-run instead of producing a retracted finding.

---

## Defect 3 — concurrent lanes shared one episode staging directory

**Found 2026-08-04, at launch, by the failure itself. Caught before it produced data.**

Every episode staged its anonymized cohort to a single hardcoded `data/episode/`, read it back
through `CodeExecutor`, and deleted it on the way out. Correct for one process; wrong for two.

Three model lanes were started in parallel to cut a 1–2 day run to ~10 hours. All three died
within minutes on `Parquet magic bytes not found in footer` — lane B truncating
`expression.parquet` while lane A read it, lane C `rmtree`-ing the directory when its episode
finished.

### Why this belongs in this document

The crash was the *lucky* branch. The unlucky branch is lane A opening the file a moment **after**
lane B finished writing it: a complete, structurally valid parquet belonging to a different
cohort. Nothing raises. The episode runs to completion, gets scored against the answer key for
the cohort on its **label**, and enters the results table indistinguishable from any other row.

That is Defect 1 and Defect 2's shape for the third time — a failure that renders as a benign
value — but aimed at the cohort identity the entire benchmark exists to measure. An episode
labelled `g2_brca_s42` that actually analyzed OV corrupts both the outcome score and the process
judgment, and no aggregate would show it.

### Extent

**Zero contaminated episodes.** Checked at the time: of 133 attempted episodes across the three
lanes, none completed — only harness artifacts (`gene_map.json`, `codebook.json`) had been
written. The resume check keys on `<label>.json`, which none of them had, so nothing was skipped
on the re-run either.

### Fix

`biodiscoverygym/paths.py` — writer (`Episode`) and reader (`CodeExecutor`) resolve the staging
path through one PID-keyed function, which is what keeps them in agreement. Stale directories
from SIGKILLed episodes are swept by liveness probe, scoped so a live sibling's data survives.

Verified by a 3-process × 3-cohort concurrency test doing repeated interleaved write/read cycles:
each lane reads back its own matrix shape. The pre-fix counterfactual deadlocks.

### Standing consequence

Parallelism was assumed safe because nothing in the harness *looked* stateful. The shared path
was four years of single-process convention, invisible until concurrency made it a race. Before
running anything in parallel again, ask what filesystem state it assumes it owns.

---

## Claims checked and NOT supported

Recorded so they are not re-litigated:

- **"G3 scoring is inverted for `g3b_ov_mislead_brca`."** Not supported. The outcome scorer treats
  OV as truth correctly: Sonnet `s123` claiming HGSOC → `true_cohort`; GPT `s123` claiming *"TCGA
  BRCA cohort"* → `mislead_cohort`. The fooling metric comes from this scorer, not from CoT-judge
  prose, so the headline numbers were never affected.
- **"Gemini names the cohort by sample count in 6/21."** Superseded — that is the retired loose
  probe. The tightened, hand-validated probe gives **8 episodes total** across all six runs, which
  is what the reports use.

---

## Standing lesson

All three defects share a shape: **a failure mode that renders as a benign value** — a path that
looks like a save location, an API error that looks like a model resisting a trick, a valid
parquet belonging to the wrong cohort. Aggregates cannot show you these, because the aggregate is
exactly where the failure stops looking like one.

Defects 1 and 2 were invisible at every level of aggregation and were found only by reading
episodes. Defect 3 was different and instructive: it announced itself loudly, but only because
the race happened to land on the destructive branch. Had the timing shifted by a few hundred
milliseconds it would have joined the other two, and we would have been reading episodes to find
it months later.

Concretely: never let an error state share a code path with a legitimate value; audit at the
episode level before any number becomes a claim; and when a bug is caught by luck, fix the class,
not the symptom — the same race with different timing is a silent data-corruption bug.
