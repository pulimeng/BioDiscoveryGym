# Data-integrity audit — 2026-07-28

**Reproduce:** `python scripts/audit_integrity.py --json manuscript/figures/integrity_audit.json`
(exits 1 if any identity gate errored, so it can gate a release).

Two defects, found by reading individual episodes rather than aggregates. **Neither is visible in
any report** — that is what makes them dangerous. One silently weakens a headline metric; the other
silently fabricates a zero that was then read as a finding.

Prompted by an external review pass. Of its three claims, one was real and understated, one was
wrong, one was already fixed. The most serious problem was found while checking the claim that was
wrong — recorded here so the audit's own provenance is honest.

---

## Defect 1 — the "blinded" arm leaks the cohort through `output_dir`

> **STATUS: DEFERRED BY DECISION 2026-07-29.** Not being worked on. Documented, quantified, and
> accepted as a known limitation for the current results. It does **not** invalidate the
> between-arm deltas (see below); it does mean **absolute** G2 derivation rates are inflated and a
> blinded re-run is the only clean fix. Anyone starting a new blinded run must fix this first, or
> the new data inherits the defect.

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

Both defects were invisible at every level of aggregation and were found only by reading episodes.
Both share a shape: **a failure mode that renders as a benign value** — a path that looks like a
save location, an API error that looks like a model resisting a trick. Aggregates cannot show you
these, because the aggregate is exactly where the failure stops looking like one.

Concretely: never let an error state share a code path with a legitimate value, and audit at the
episode level before any number becomes a claim.
