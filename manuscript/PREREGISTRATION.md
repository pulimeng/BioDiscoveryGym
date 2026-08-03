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
*Test:* χ² on the 3×3 (arm × strategy), hierarchical model as in §5.
*Predicted:* G0 predominantly recalled-prior; G2 shifts away from that pole.

**H2 — Outcome is equivalent across G0–G2 within a practical margin.**
*Test:* TOST (two one-sided tests) on normalized outcome.
**Margin: ±0.05 on the 0–1 scale**, chosen *a priori*. Justification: pilot honest-arm SD = 0.094,
so ±0.05 ≈ **d = 0.53** — a medium effect. We assert that a difference smaller than this is not
scientifically meaningful for "did the agent discover it". The margin is **not** derived from the
observed G0–G2 spread (0.019); anchoring it to the effect we hope is small would be circular.
*A non-significant difference alone does NOT establish equivalence and will not be reported as such.*

**H3 — Unwarranted identity support predicts false-label adoption (G3).**
*Test:* Fisher exact / logistic with the §5 random effects. **Primary axis = support.**
*Predicted:* unwarranted more often fooled. Pilot OR ≈ 14.9 (contaminated; not a prediction of size).

**H4 — Strategy provides a secondary association (G3).**
Same test on the strategy axis. Secondary to H3 by design, since strategy is scored neutrally.

**H5 — Detailed scaffolding increases documented rigor AND false-label adoption.**
*Test:* paired by model/cohort/seed. Two components; **both** must hold for H5 to be supported.

## 5. Analysis

- **Hierarchical models** with random effects for model, prompt, cohort, seed, and (G3) cohort-pair.
  Episodes are not independent — the same cohort and seed recur across arms.
- **Multiplicity:** Holm–Bonferroni across the five primary tests. Stratified and per-model analyses
  are **exploratory** and reported as such.
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

## 8. Both-directions framings

Registered so the study is publishable across plausible outcomes — the point of preregistering.

- **H1 small or null.** A *small* clean process shift is a **finding, not a failure**: the pilot leak
  inflated the shift, so shrinkage is the expected direction. If G2 shows agents cannot derive
  identity and fall back to recall, we report **"agents remain in the recall regime even under
  genuine blinding"**, which is a stronger claim than a large shift.
- **H2 fails — clean G2 outcome drops below G0.** Also a finding: **the outcome metric is
  recall-biased.** Registered component-level prediction: the drop should concentrate in
  `reference_concordance`. In pilot data that is the only component with a significant G0 advantage
  (+0.073, p=0.011), while `marker_evidence` is marginally *higher* blind.
- **H3 fails.** Then grounding does not predict robustness, the instrument's criterion validity is
  not established, and we say so. This is the result that would most damage the paper; we report it
  rather than retreating to H4.
- **H5 fails.** The scaffold reversal was a pilot artifact. Reported as a failed replication of our
  own exploratory finding.

## 9. Deviation log

*(append-only; date, what changed, why)*

- *(none yet)*

---

## What is exploratory, not confirmatory

Reported as exploratory regardless of outcome: the mechanism markers (paradox / noted-but-unresolved
/ deference), the shortcut analysis, cohort-level patterns, cost, per-model leaderboards, and any
pilot-vs-rerun comparison. The pilot-vs-rerun pairing in particular is **quasi-experimental** — the
conditions differ in the scorer patch and in time, not only in the blinding fix.
