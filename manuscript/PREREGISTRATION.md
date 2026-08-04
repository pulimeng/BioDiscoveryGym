# Preregistration — confirmatory run

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

## 4. Primary hypotheses

**Three, not five.** With ~21 episodes per honest arm and ~96 per G3 arm, more primary tests buys
multiplicity burden rather than evidence. H4 (strategy on G3) and the rigor half of the old H5 move
to §4a as secondary, reported with effect sizes and no multiplicity claim.

**Analysis style, fixed here: effect sizes with 95% CIs lead; p-values are secondary.** At this n a
CI communicates what the data can and cannot exclude; a p-value mostly communicates n. We report
simple, transparent statistics — proportions, differences, odds ratios, and their intervals — not
hierarchical models. The design has structure (cohort, seed, model, prompt recur), so we handle it
by **stratifying and showing per-stratum estimates**, not by modelling it away.

**P1 — Information disclosure changes provenance.**
Consensus strategy distribution differs across G0/G1/G2.
*Report:* the 3×4 arm × strategy table, plus **derived-rate per arm with 95% CIs** (Wilson).
*Test:* Fisher–Freeman–Halton on the table.
*Predicted:* G0 predominantly recalled-prior; G2 shifts away from that pole.

**P2 — Outcome is equivalent across G0–G2 within a practical margin.**
**This one genuinely needs an equivalence test** — a non-significant difference does NOT establish
equivalence, and we will not report it as if it did.
*Estimand:* the **largest pairwise arm difference** (G0−G1, G0−G2, G1−G2). Equivalence is declared
only if all three 90% CIs sit inside the margin.
**Margin: ±0.05 on the 0–1 scale**, chosen *a priori* (pilot honest-arm SD = 0.094, so ±0.05 ≈
d=0.53). Not derived from the observed 0.019 spread — anchoring the margin to the effect we hope is
small would be circular.
*Test:* TOST per contrast, equivalently read off the 90% CIs.

**P3 — Unwarranted identity support is ASSOCIATED with false-label adoption (G3).**
*Report:* fooled-rate by support class with 95% CIs, and the odds ratio with its CI. Stratified by
model, prompt and cohort-pair, **shown as a small-multiples panel** rather than pooled into one
number.
*Test:* Fisher exact on the pooled 2×2, with the stratified panel as the honesty check — if the
direction is inconsistent across strata, the pooled OR is not reported as the headline.

**⚠ Associational only, and the reason is structural.** `support` is judged from the WHOLE trace, so
an agent that accepts the false label and then reasons unsupportedly earns "unwarranted" as a
*consequence* of being fooled, not a cause. Temporal order is not established by this design.
*Exploratory:* re-score support on pre-acceptance trace segments only.

## 4a. Secondary — reported with CIs, no multiplicity claim

- **Strategy on G3** (the old H4) — the same 2×2 on the strategy axis. Secondary because strategy is
  scored neutrally by design.
- **Scaffolding and rigor** — does the detailed prompt raise `validation_rigor`?
- **Scaffolding and fooling** — does it raise false-label adoption? *Pre-committed:* if this lands
  directional but with a CI crossing 1, it is reported as **"directional in k/3 models"** and is not
  a headline. That call is made here, not after seeing it.

## 5. Analysis

- **Effect sizes with CIs first.** Wilson intervals for proportions, bootstrap for differences,
  exact CIs for odds ratios.
- **Structure is shown, not modelled.** Episodes repeat across cohort/seed/model/prompt, so every
  primary result is also given per stratum. A pooled estimate whose strata disagree is reported as
  heterogeneous, not as a headline.
- **Multiplicity:** Holm–Bonferroni across the **three** primary tests. Secondary and exploratory
  analyses carry no multiplicity claim and are labelled as such.
- **No hierarchical models.** At ~21 episodes per arm, variance components for factors with 2–3
  levels are not estimable and would imply precision the design does not have.
- **Judge reliability** reported alongside every process result: unanimity, pairwise agreement,
  cross-family comparison.

## 6. Power

G3 carries P3 and is the smallest arm, so it gets the extra episodes. **G3 moves from 3 seeds to 8
(36 → 96 per prompt arm),** cost ≈ +$200.

The reasoning is **precision, not significance**: at 36 per arm a fooled-rate CI is roughly ±16
points, wide enough that most plausible results are uninformative. At 96 it is roughly ±10. We are
buying a usable interval, not a p-value below a threshold.

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

- **P1 small or null.** A *small* clean process shift is a **finding, not a failure**: the pilot leak
  inflated the shift, so shrinkage is the expected direction. If G2 shows agents cannot derive
  identity and fall back to recall, we report **"agents remain in the recall regime even under
  genuine blinding"**, which is a stronger claim than a large shift.
- **P2 fails — clean G2 outcome drops below G0.** Also a finding: **the outcome metric is
  recall-biased.** Registered component-level prediction: the drop should concentrate in
  `reference_concordance`. In pilot data that is the only component with a significant G0 advantage
  (+0.073, p=0.011), while `marker_evidence` is marginally *higher* blind.
- **P3 fails.** Then support is not associated with robustness, the instrument's criterion validity
  is not established, and we say so plainly. This is the outcome that would most damage the paper.
  We report it rather than retreating to the strategy axis — strategy surviving alone would be an
  exploratory observation, not a rescue of P3.
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

---

## What is exploratory, not confirmatory

Reported as exploratory regardless of outcome: the mechanism markers (paradox / noted-but-unresolved
/ deference), the shortcut analysis, cohort-level patterns, cost, per-model leaderboards, and any
pilot-vs-rerun comparison. The pilot-vs-rerun pairing in particular is **quasi-experimental** — the
conditions differ in the scorer patch and in time, not only in the blinding fix.
