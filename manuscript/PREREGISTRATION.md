# Confirmatory analysis plan

*(preregistration — fixed before the confirmatory data exists)*

**Frozen 2026-08-03, before any clean data exists.** The git commit of this file is the timestamp.
Nothing below may be revised after the confirmatory run begins; deviations go in §9, dated, with
reasons.

**Drafted by the assistant, pending PI review.** The margin in §4 and the exclusions in §7 are
judgement calls and should be checked before the run starts.

---

## 1. Why this document exists

The pilot campaign (450 episodes, `results/tcga/{ladder,lean}`) was exploratory. We tried many
analyses, changed constructs mid-flight, found two data-integrity defects, and **retracted one
finding** ("Gemini Flash collapses under lean"). That history is legitimate exploration, but it
means no p-value from the pilot can be read as confirmatory.

This document fixes the predictions *before* the clean data exists so the confirmatory run can be
read as confirmatory. The honest narrative is: **an exploratory campaign exposed a benchmark defect;
hypotheses were frozen; the confirmatory experiment followed.**

## 2. Design (fixed)

Unchanged from the pilot except where stated.

- **Task:** subtype discovery on blinded TCGA multi-omics via a fixed code/tool interface.
- **Ladder:** G0 (cohort disclosed) · G1 (genes disclosed, cohort hidden) · G2 (blinded) ·
  G3a/G3b (false cohort supplied, differing in reveal timing).
- **Models:** GPT-5.5, Claude Sonnet 5, Gemini 3.5 Flash. *Gemini is a smaller tier — a confound we
  disclose, not one we can remove.*
- **Prompts:** detailed six-stage scaffold vs lean ("no prescribed procedure").
- **Cohorts/seeds:** 7 cohorts × 3 seeds on honest arms. **G3 raised from 3 to 8 seeds** (see §6).
- **Blinding fix:** agent works in an opaque directory (`48d1db0`). **Gate: `audit_blinding.py`
  must exit 0 on every run dir before any analysis.** A run that fails the gate is discarded, not
  patched.

## 3. Constructs (fixed before seeing clean data)

Two axes, deliberately separate. **They are not interchangeable and the paper must not treat them
as one.**

| axis | levels | scored? |
|---|---|---|
| **strategy** — how identity was reached | data-derived / mixed / recalled-prior / not-established | **neutral** — recall is legitimate |
| **support** — whether the claim was warranted | grounded / unsupported / anchored | **scored** — this carries the failure |

`unwarranted` := `unsupported` ∪ `anchored`.

**Judge protocol:** 3 independent passes for stochastic stability, plus ≥1 pass from a different
model family. The process judge **must not see the true or planted cohort identity** when
classifying provenance; identity correctness is scored separately. *(Requires editing
`summarize_cot.build_input`, which currently prints the true cohort into the judge's own prompt.)*

**Consensus:** majority of 3. Ties reported as unresolved, never broken.
**Separation criterion:** a between-arm delta is claimed only if the two arms' three per-pass rates
do not overlap.

## 4. Confirmatory analysis plan — descriptive first

**This is an analysis plan, not a significance ceremony.** Its purpose is to prevent narrative
selection: fixing which contrasts we look at and how we describe them, before the data exists. It is
not a device for finding a model that yields stars.

With 3 models, 7 cohorts, 2 mislead pairs and correlated episodes, inferential machinery can
manufacture more confidence than the design earns. **The paper is a measurement and
experimental-design paper, not a hypothesis-testing paper**, and the analysis should say so.

### Evidence hierarchy — report in this order

| # | level | what it establishes |
|---|---|---|
| 1 | **Construct demonstration** | outcome scores do not encode provenance *by definition* — no data needed |
| 2 | **Controlled contrasts** | what changes as information disclosure changes |
| 3 | **Replication structure** | whether the pattern recurs across models, prompts, cohorts, seeds, judge families |
| 4 | **Effect sizes and uncertainty** | raw counts, percentage-point differences, cluster-aware intervals |
| 5 | **Formal tests** | supporting diagnostics, in tables or the supplement — **not the story** |

A result that survives level 3 — the same direction in most models, prompts and cohorts — is
stronger evidence here than a small p-value on pooled data, because pooling correlated episodes is
exactly where this design would mislead.

### Primary contrasts (fixed now)

**C1 — Provenance across the information ladder.**
*Estimand:* the full strategy distribution per arm (G0/G1/G2), and the **percentage-point change**
in derived-rate between arms.
*Report:* full distributions, raw counts, per-arm rate with a cohort-clustered bootstrap interval.

**C2 — Outcome across the same ladder.**
*Estimand:* the **largest pairwise arm difference** in normalized outcome, expressed in points and
**relative to the observed episode-level SD** (pilot: 0.094).
*We do not claim equivalence.* The design cannot establish that outcome is invariant across
scientific tasks, and a non-significant difference would not show it. We report the magnitude and
its uncertainty and let it stand next to C1's magnitude — that juxtaposition is the finding.

**C3 — False-context response by evidential support (G3).**
*Estimand:* fooled-rate by support class, as **raw counts first**, then the difference in points and
an odds ratio with interval.
*Report:* a per-model × per-cohort-pair table of raw fooled/resisted counts. **The pooled estimate is
secondary to that table** — with 2 mislead pairs, a pooled OR is a summary of very few independent
units.
**Associational only.** `support` is judged from the whole trace, so unsupported reasoning may
*follow* accepting the false label rather than precede it. Temporal order is not established here.

### Secondary — direction and magnitude only, no multiplicity claim

Strategy axis on G3 · scaffolding vs `validation_rigor` · scaffolding vs false-label adoption.
Reported as **direction per model** ("k of 3 models, same sign") with intervals.

## 5. Handling correlated episodes — the real statistical risk

The threat here is **pseudoreplication**, not insufficient power. The same cohort recurs across
arms, prompts and models; episodes are not independent.

- **Cluster-aware intervals.** Bootstrap resampling **cohorts** (and cohort-pairs on G3), not
  episodes. Resampling episodes would understate uncertainty by treating 7 cohorts as 126
  independent draws.
- **Show the structure.** Every primary contrast is also reported per model, per prompt, per cohort.
  A pooled number whose strata disagree is reported as **heterogeneous**, never as a headline.
- **No hierarchical models.** At this n, variance components for 2–3-level factors are not
  estimable and would imply precision the design lacks.
- **Formal tests** (Fisher, Fisher–Freeman–Halton) appear in tables as diagnostics with exact counts
  beside them. **No multiplicity ceremony over three contrasts** — we report all of them, always,
  which is the actual protection against selection.
- **Judge validity** reported as agreement against human annotation and across judge families, not
  assumed.

### Language, fixed in advance

Prespecified because the wording is where overinterpretation enters.

| do not write | write |
|---|---|
| "derivation significantly predicts resistance, p=0.0001" | "false-label adoption differed substantially across process categories; the estimate rests on few independent cohort-pairs, so we treat it as a pattern to test, not a population estimate" |
| "outcome is equivalent across arms" | "outcome differences were small relative to observed episode-level variation, with uncertainty reported" |
| "agents recall rather than derive" | "agents varied widely in how they established identity, and outcome scores did not distinguish them" |
| "X causes Y" | "X is associated with Y; temporal order is not established by this design" |

**Central framing:** *we use controlled contrasts and repeated observations to characterise a
measurement gap. The study estimates patterns within this benchmark; it does not claim
population-level effects across models, cancers, or scientific-agent tasks.*

## 6. Power

G3 carries C3 and is the smallest arm, so it gets the extra episodes. **G3 moves from 3 seeds to 8
(36 → 96 per prompt arm),** cost ≈ +$200.

The reasoning is **interval width, not significance**: at 36 per arm a fooled-rate interval is
roughly ±16 points, wide enough that most plausible results are uninformative. At 96 it is roughly
±10. We are buying a usable estimate.

**The binding constraint is independent units, not episodes.** G3 has only **2 mislead pairs**, so
more seeds narrow the within-pair interval but do not create new independent cohort-pairs. This is
the honest ceiling on C3 and is stated as such in the paper — additional seeds cannot fix it.

## 7. Exclusions (fixed)

Declared in advance; anything else is a deviation under §9.

1. Episodes whose run dir fails `audit_blinding.py` — the whole run is discarded.
2. Episodes where any LLM scorer component errored. The scorers now refuse to emit these
   (`c28336a`); they are re-run, and if they fail twice they are excluded and **counted in the paper**.
3. Episodes with no submitted discovery.
4. **No other exclusions.** In particular we do **not** exclude episodes for being surprising.

## 8. Interpretation registered in advance, per outcome

**Not a claim that every result is a finding.** The purpose is to fix the *interpretation* of each
plausible outcome now, so that reading is not chosen after seeing the data. Some outcomes below are
genuine findings; others are failures we would report as failures. Which is which is decided here.

- **C1 small or null.** A *small* clean process shift is a **finding, not a failure**: the pilot leak
  inflated the shift, so shrinkage is the expected direction. If G2 shows agents cannot derive
  identity and fall back to recall, we report **"agents remain in the recall regime even under
  genuine blinding"**, which is a stronger claim than a large shift.
- **C2 — clean G2 outcome drops below G0.** Also a finding: **the outcome metric is
  recall-biased.** Registered component-level prediction: the drop should concentrate in
  `reference_concordance`. In pilot data that is the only component with a significant G0 advantage
  (+0.073, p=0.011), while `marker_evidence` is marginally *higher* blind.
- **C3 shows no association.** Then support is not associated with robustness, the instrument's criterion validity
  is not established, and we say so plainly. This is the outcome that would most damage the paper.
  We report it rather than retreating to the strategy axis — strategy surviving alone would be an
  exploratory observation, not a rescue of C3.
- **Scaffolding→fooling fails (§4a).** The scaffold reversal was a pilot artifact. Reported as a
  failed replication of our own exploratory finding — which is a legitimate result, not a gap.

## 9. Deviation log

*(append-only; date, what changed, why)*

- **2026-08-04 — amended before any clean data existed.** Six statistical specifications were
  underdetermined or wrong in the 08-03 freeze; corrected while the confirmatory run had not begun,
  so nothing here was chosen with knowledge of clean results:
  (1) H1 said a 3×3 table when strategy has four levels — now 3×4 with a prespecified
  Fisher–Freeman–Halton fallback; (2) §5 listed `model` and `prompt` as RANDOM effects despite
  having 3 and 2 levels, and `prompt` being the H5 manipulation — both are now FIXED;
  (3) H2's equivalence estimand was unstated — now the maximum pairwise contrast, all three
  required; (4) H5's two endpoints versus a five-test Holm family was ambiguous — now an
  intersection–union test occupying one slot; (5) H3 was worded as prediction and is now explicitly
  associational, with the post-acceptance confound stated; (6) §8's "publishable across outcomes"
  framing was outcome-driven and is now "interpretation registered per outcome".
- **2026-08-04 (second amendment, still before any clean data) — statistical plan simplified to
  match the sample size.** The 08-04 corrections were right but produced machinery out of scale with
  ~21 episodes per arm. Five primary hypotheses collapse to **three** (P1–P3); the strategy-axis G3
  test and both scaffolding endpoints move to secondary with no multiplicity claim. Hierarchical
  models are **dropped entirely** — variance components for 2–3-level factors are not estimable at
  this n and would imply precision the design lacks. Analysis now leads with **effect sizes and 95%
  CIs**, with repeated structure **shown per stratum rather than modelled away**. The equivalence
  test is **kept**: P2 asserts equivalence, which a non-significant difference cannot establish.
  Power is re-argued in terms of interval width (±16 → ±10 points at 96/arm) rather than a p-value
  threshold.
- **2026-08-04 (third amendment, still before any clean data) — reframed as a descriptive
  measurement study after reviewer input.** The paper is a measurement and experimental-design
  paper, so the analysis now follows an explicit **evidence hierarchy**: construct demonstration →
  controlled contrasts → replication across models/prompts/cohorts/judges → effect sizes with
  uncertainty → formal tests as supporting diagnostics only. Hypotheses P1–P3 become **contrasts
  C1–C3** with descriptive estimands.
  **The equivalence claim is dropped rather than tested.** Earlier drafts kept TOST on the grounds
  that "equivalent" cannot follow from non-significance — true, but the better fix is to not claim
  equivalence. C2 now reports the largest pairwise outcome difference *relative to episode-level SD*
  and lets it stand beside C1's magnitude; that juxtaposition is the finding.
  Identifies **pseudoreplication as the real statistical risk** (not power): intervals now bootstrap
  over **cohorts**, not episodes, since 7 cohorts are not 126 independent draws. Multiplicity
  ceremony is dropped over three always-reported contrasts — reporting all of them always is the
  actual protection against selection.
  Adds a **fixed language table** because wording is where overinterpretation enters, and states the
  binding constraint on C3 plainly: only **2 mislead pairs** exist, so more seeds cannot create more
  independent units.

---

## What is exploratory, not confirmatory

Reported as exploratory regardless of outcome: the mechanism markers (paradox / noted-but-unresolved
/ deference), the shortcut analysis, cohort-level patterns, cost, per-model leaderboards, and any
pilot-vs-rerun comparison. The pilot-vs-rerun pairing in particular is **quasi-experimental** — the
conditions differ in the scorer patch and in time, not only in the blinding fix.
