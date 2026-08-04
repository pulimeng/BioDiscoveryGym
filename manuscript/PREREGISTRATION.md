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

Directional predictions, registered in this order. **α = 0.05 after the correction in §5.**

**H1 — Information disclosure changes provenance.**
Consensus strategy distribution differs across G0/G1/G2.
*Test:* arm × strategy contingency over **3 arms × 4 strategy levels** (data-derived, mixed,
recalled-prior, not-established), plus the §5 model. `not-established` is retained rather than
collapsed — it occurred 3/1350 times in the pilot, so it is rare but real. **If any cell has an
expected count < 5, use Fisher–Freeman–Halton rather than χ²**; that decision is made here, not
after seeing the table.
*Predicted:* G0 predominantly recalled-prior; G2 shifts away from that pole.

**H2 — Outcome is equivalent across G0–G2 within a practical margin.**
*Estimand — fixed now, because "equivalent across G0–G2" has several non-equivalent readings.*
The claim is the **maximum pairwise arm difference**: equivalence is declared only if **all three**
model-based contrasts (G0−G1, G0−G2, G1−G2) fall inside the margin. This is the strictest reading
and the one the narrative uses. TOST on each contrast; the conjunction requires all three, so no
multiplicity adjustment is needed within H2 (an intersection–union test is valid at α).
*Test:* TOST on the three model-based contrasts from the §5 model.
**Margin: ±0.05 on the 0–1 scale**, chosen *a priori*. Justification: pilot honest-arm SD = 0.094,
so ±0.05 ≈ **d = 0.53** — a medium effect. We assert that a difference smaller than this is not
scientifically meaningful for "did the agent discover it". The margin is **not** derived from the
observed G0–G2 spread (0.019); anchoring it to the effect we hope is small would be circular.
*A non-significant difference alone does NOT establish equivalence and will not be reported as such.*

**H3 — Unwarranted identity support is ASSOCIATED with false-label adoption (G3).**
*Test:* logistic model per §5. **Primary axis = support.**
*Predicted:* unwarranted more often fooled. Pilot OR ≈ 14.9 (contaminated; not a prediction of size).

**⚠ Associational only — do not write this as causal, and the reason is not merely caution.**
`support` is judged from the WHOLE trace, so an agent that accepts the false label and then
reasons unsupportedly earns "unwarranted" as a *consequence* of being fooled, not a cause. The
temporal order is not established by this design. Any causal reading requires evidence that the
support behaviour preceded acceptance — which we do not have and will not claim.
*Exploratory, registered here:* re-score support using only pre-acceptance trace segments and
report whether the association survives. Exploratory because the segmentation rule is not yet
validated.

**H4 — Strategy provides a secondary association (G3).**
Same test on the strategy axis. Secondary to H3 by design, since strategy is scored neutrally.

**H5 — Detailed scaffolding increases documented rigor AND false-label adoption.**
*Test:* an **intersection–union test** over two endpoints (validation_rigor; false-label adoption),
each from the §5 model. H5 is supported only if **both** reject in the predicted direction.
Because an IUT rejects only on the conjunction, it is valid at α without internal correction, so
**H5 occupies ONE slot in the Holm family, not two.** If only one endpoint holds, H5 is *not*
supported and the single surviving component is reported as exploratory.

## 5. Analysis

- **Mixed model, with the fixed/random split stated explicitly.**
  **FIXED:** `arm` (3 or 2 levels), `prompt` (2), `model` (3). These are the experimental factors,
  not samples from a population — and `prompt` is the manipulation H5 is *about*. With 2 and 3
  levels their variance components are not estimable anyway.
  **RANDOM:** `cohort` (7) and, on G3, `cohort_pair` (2, or fixed if it fails to converge).
  **REPEATED:** `seed` nests within cohort×arm×prompt×model and indexes replicate episodes.
  Model: `outcome ~ arm * prompt + model + (1 | cohort)` for H1/H2; the G3 models add
  `(1 | cohort_pair)` and drop `arm`.
  *A statistician should confirm the contrast coding and convergence before the run; this
  specification is the assistant's and has not been reviewed.*
- **Multiplicity:** Holm–Bonferroni across the **five primary hypotheses** (H5 contributes one slot
  as an IUT; H2 contributes one as an IUT over its three contrasts). Stratified and per-model
  analyses are **exploratory** and reported as such.
- **Judge reliability** reported alongside every process result: unanimity, pairwise agreement, and
  the cross-family comparison.

## 6. Power

G3 carries H3/H5 and is the smallest arm. At 3 seeds (36 per prompt arm) a moderate attenuation of
the pilot fooling contrast is undetectable (p≈0.24). **G3 therefore moves to 8 seeds (96 per arm),**
where the same attenuation reaches p≈0.02. Cost ≈ +$200.

**Pre-committed:** if H5 lands directional but non-significant, it is reported as *"directional
across 3/3 models"* and **not** as a headline. That decision is made here, not after seeing the
p-value.

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

- **H1 small or null.** A *small* clean process shift is a **finding, not a failure**: the pilot leak
  inflated the shift, so shrinkage is the expected direction. If G2 shows agents cannot derive
  identity and fall back to recall, we report **"agents remain in the recall regime even under
  genuine blinding"**, which is a stronger claim than a large shift.
- **H2 fails — clean G2 outcome drops below G0.** Also a finding: **the outcome metric is
  recall-biased.** Registered component-level prediction: the drop should concentrate in
  `reference_concordance`. In pilot data that is the only component with a significant G0 advantage
  (+0.073, p=0.011), while `marker_evidence` is marginally *higher* blind.
- **H3 fails.** Then support is not associated with robustness, the instrument's criterion validity
  is not established, and we say so plainly. This is the outcome that would most damage the paper.
  We report it rather than retreating to H4 — and H4 surviving alone would be reported as an
  exploratory observation, not as a rescue of H3.
- **H5 fails.** The scaffold reversal was a pilot artifact. Reported as a failed replication of our
  own exploratory finding.

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

---

## What is exploratory, not confirmatory

Reported as exploratory regardless of outcome: the mechanism markers (paradox / noted-but-unresolved
/ deference), the shortcut analysis, cohort-level patterns, cost, per-model leaderboards, and any
pilot-vs-rerun comparison. The pilot-vs-rerun pairing in particular is **quasi-experimental** — the
conditions differ in the scorer patch and in time, not only in the blinding fix.
