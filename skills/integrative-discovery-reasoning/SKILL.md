---
name: integrative-discovery-reasoning
description: >
  A general reasoning template for data-rich scientific discovery, distilled from an
  integrated multi-omics cancer study. Use when an agent must turn broad, messy,
  multi-modal evidence into trustworthy structure, mechanism, and testable
  interventions. Triggers: "make sense of this dataset", "what's the story here",
  "find subtypes/structure", "nominate targets/levers", "is this finding real",
  "design follow-up experiments", "review this omics/data-heavy paper".
  Domain-agnostic — the source was biology, but the flow applies to any field where
  many orthogonal measurements describe the same set of units.
---

# Integrative Discovery Reasoning

A thinking discipline for going from a pile of multi-modal data to claims you'd
stake your name on. Distilled from the reasoning flow of a strong integrative study.
Follow the stages in order; each one gates the next. The core bet of this style:
**truth shows up as the same signal seen independently through many lenses.**

## The reasoning loop (8 stages)

### 1. Start from the gap, not the data
Before analyzing anything, state what the *current* frameworks for this problem
already explain and where they fail. New work earns its existence by capturing what
existing schemes miss — not by re-deriving them.
- Ask: "What do today's classifications/models get right? What heterogeneity do they
  leave unexplained?"
- Output: a one-sentence gap statement that your whole analysis is accountable to.
- *Worked example:* genetic + clinical AML schemes (WHO, ELN) each capture part of
  the disease; none unify genotype with cell-state phenotype. That gap defined the study.

### 2. Build a broad, same-unit, orthogonal evidence base
Gather *many* measurement types on the *same* units, so signals can be cross-checked
rather than taken on faith. Breadth + shared identity is the whole foundation.
- Prefer orthogonal modalities (different failure modes) over more of the same.
- Keep the unit of analysis fixed across modalities so findings are comparable.
- *Example:* 13 modalities (DNA, RNA, protein, PTMs, metabolites, lipids…) on 173
  identical patient samples.

### 3. Find the latent organizing axes — then interpret them
Don't describe 10,000 variables. Compress the heterogeneity to a *few* organizing
principles and name what they mean.
- Use unsupervised structure-finding first (factorization / clustering / dimensionality
  reduction) to let the data propose its own axes.
- Aim for a small set: typically **discrete groups** (subtypes/segments) *plus* one or
  two **continuous axes** (gradients) that cut across them.
- Then interpret each axis biologically/mechanistically — a factor you can't explain is
  not yet a finding.
- *Example:* discrete subtypes (AML-8) + a continuous MYC↔mTOR antagonism axis,
  surfaced by multi-omic factor analysis.

### 4. Link known causes to their downstream signatures
Connect the established drivers (mutations, inputs, known causes) to their molecular
consequences. This grounds new structure in known biology and reveals what's *novel*.
- For each known driver, ask "what is its imprint across each modality?"
- Watch for drivers whose imprint *survives* controlling for the obvious axis — those
  carry independent information.

### 5. Triangulate: trust convergence, distrust singletons
A claim is strong in proportion to how many independent modalities agree on it
("coalescent phenotypes"). Treat single-modality signals as hypotheses, not results.
- For every candidate finding, explicitly check: does an orthogonal ome corroborate it?
- Convergence across data types is the substitute for certainty you can't get from one.

### 6. Chase mechanism behind the strongest anomalies
Pick the most striking, unexpected signals and ask *why* — drive to a mechanism, and
distinguish competing mechanistic explanations.
- Don't stop at "X is dysregulated"; ask whether it's enzymatic vs. passive, cause vs.
  consequence, driver vs. marker.
- *Example:* mitochondrial hyperacetylation in one subtype → traced to non-enzymatic
  acetylation from elevated acetyl-CoA (a metabolic cause), distinct from another
  subtype's HDAC/HAT-driven hypoacetylation.

### 7. Convert description into testable interventions
Turn structure and mechanism into hypotheses about *levers* — what, if changed, would
move the outcome. Use models to nominate; don't let models conclude.
- Build the hypothesis explicitly first ("if the effect depends on interactors, then a
  network of co-functional partners should predict it"), then bring computational tools
  (networks, classifiers, dependency/perturbation data) to *rank* candidates.
- Require multiple lines of support to promote a candidate (e.g. overexpression + an
  independent dependency signal).
- **Validate causally**: perturb in both directions — remove the lever and the effect
  should vanish (necessity); add it back and the effect should return (sufficiency).
- *Example:* a co-function network nominated MTA1; CRISPR knockout restored drug
  sensitivity and overexpression re-conferred resistance — necessity *and* sufficiency.

### 8. Replicate externally, then state your limits
- Re-test the headline findings in an independent cohort/dataset before believing them.
- Close by enumerating what would make you wrong: confounders, population/scope limits,
  measurement artifacts, and the description-vs-mechanism gap. Name which claims are
  validated vs. still associational.

## Operating principles (apply throughout)
- **Convergence over significance.** Many lenses agreeing beats one small p-value.
- **Few axes over many variables.** Compress, then name; resist describing everything.
- **Models nominate, experiments/replication conclude.** ML ranks hypotheses; it does
  not establish causation.
- **Perturb in both directions.** Necessity and sufficiency, not correlation.
- **Separate marker from driver.** Always ask whether a signal causes the outcome or
  merely rides along with it.
- **Keep the gap statement in view.** Every result should pay back the Stage-1 gap.

## Anti-patterns to flag
- A claim resting on a single modality with no orthogonal check.
- Naming clusters/factors without a mechanistic interpretation.
- Treating a predictive model's output as a conclusion rather than a ranked hypothesis.
- Correlation-only causal language ("drives", "causes") with no perturbation.
- Skipping external replication; ignoring confounders and scope limits.

## Quick checklist
1. Gap stated?  2. Broad orthogonal same-unit data?  3. Few named axes?
4. Known drivers linked?  5. Findings triangulated?  6. Mechanism for top anomalies?
7. Interventions nominated + causally tested?  8. Externally replicated + limits stated?
