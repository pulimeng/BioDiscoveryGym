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

## Defect 2 — identity gates that failed were silently counted as "not fooled"

### Mechanism

`cohort_identity_verdict` is an LLM call. On failure it records `verdict: "error"` — here, a
DeepSeek `402 Insufficient Balance`. Every consumer computes:

```python
fooled = (verdict == "mislead_cohort")
```

An errored gate is therefore **indistinguishable from a model that resisted the mislead**. Failure
is scored as success.

### Extent

All **12** G3 episodes in `lean/gemini35flash_20260722` errored — the entire arm:

```
arm                          n   fooled   ERRORED
GPT-5.5/detailed            12       11         0
GPT-5.5/lean                12        5         0
Sonnet 5/detailed           12        8         0
Sonnet 5/lean               12        4         0
Gemini 3.5 Flash/detailed   12        5         0
Gemini 3.5 Flash/lean       12        0        12   <-- UNSCORED
```

### Consequences

**(a) H2 was computed on contaminated input.** Corrected, the result gets *stronger*:

| | derived | not derived | p | OR |
|---|---|---|---|---|
| errors counted as not-fooled (wrong) | 6/29 = 21% | 27/43 = 63% | 0.0006 | 0.15 |
| **errors excluded (correct)** | **6/24 = 25%** | **27/36 = 75%** | **0.0002** | **0.11** |

**(b) A recorded finding is invalid.** "Gemini 5→0 fooled under lean" is **not a real zero** — it is
12 unscored episodes. The claim *"the staged prompt makes models more fooled, 3/3 models"* is
therefore **2/3 verified, 1 unknown**. This had already propagated into project memory and the talk
material.

### Required actions

1. **Re-score the 12 gates** (~$1; the balance failure is resolved). This is the cheapest fix and
   restores the third model.
2. **Guard applied:** `cot_deepdive.py` now excludes errored gates and prints how many it dropped,
   rather than absorbing them. Any other consumer of `cohort_identity_verdict` needs the same
   treatment — *the bug is the pattern, not the arm*.
3. Make the scorer refuse to emit a scored episode when the gate errors, so this cannot pass
   silently again.

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
