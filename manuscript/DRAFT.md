# Correct but not discovered: measuring whether cancer-genomics agents derive or recall

*Draft for ICLR 2027. All statistics from `figures/cot_stats.json`; regenerate with
`python scripts/cot_deepdive.py`.*

---

## Abstract

Autonomous research agents are increasingly pitched as instruments of discovery: give the system
your data, and it will find the biology. We show this claim is not merely unproven but, as usually
measured, **unfalsifiable**. On a blinded cancer-genomics benchmark we score 450 agent episodes on
two axes: whether the answer is correct, and whether the agent *derived* the cohort's identity from
the data or *recalled* it from parametric memory. Correctness cannot tell the two apart — episodes
judged data-derived and recalled-prior score 0.483 and 0.524 respectively — no detectable
difference in either direction (Mann-Whitney p=0.19; ordinal ρ=−0.067, p=0.46). Yet the distinction is not cosmetic. When we inject a false cohort label,
episodes that derived identity from data commit to the falsehood 21% of the time against 67% for
those that did not (Fisher p=0.0001, OR=0.13). **The property that determines whether an agent
survives misleading data is invisible to the metric the field reports.** We further find that
prescriptive "rigor" scaffolding makes models *more* susceptible to the false frame, not less, in
3 of 3 models tested, and that agents sometimes identify the benchmark from cohort *sample size*
before performing any biological analysis. Process labels come from a neutral, non-benchmarked judge run in
three independent passes over all 450 episodes; we report per-episode agreement (35–63% unanimous)
and claim only deltas whose per-pass ranges do not overlap.

---

## 1. Introduction

The pitch is now familiar at every computational-biology venue: hand the agent your data and it will
solve the problem, perhaps even discover new biology. The claim is attractive and, in its usual
form, untestable.

Consider an agent handed a breast-cancer cohort that returns the canonical subtypes with a
mechanistic story. Did it derive that structure from the matrix in front of it, or retrieve it from
the thousands of breast-subtype papers in its training corpus? For well-studied biology the two
outputs are *identical*. Any correctness metric assigns them the same score. "The agent discovered
X" is, as measured, not a falsifiable claim.

The field has begun to suspect this. NatureBench reports agents beating published SOTA on only 17.8%
of tasks, concluding they succeed "primarily through methodological translation... rather than
genuine scientific invention." BiomniBench-DA grades process against expert rubrics. But both grade
a *single output*, and both disclose the answer-key paper in the prompt — leaving parametric recall
entirely open. Nobody blinds the data itself.

We make the distinction measurable, and then show it matters.

**Contributions.**
1. A benchmark holding data constant while varying what the agent is permitted to know, from
   told-the-cohort through fully-blinded to actively-misled.
2. A process instrument scoring how cohort identity was established, judged from the agent's own
   action trace by a neutral judge, with three-pass consensus and an explicit separation criterion.
3. Two results: **correctness cannot distinguish derivation from recall**, and **derivation predicts
   robustness to misleading data**.
4. An instruction ablation showing that prescriptive rigor scaffolding buys documentation rather
   than grounding — and costs robustness.

---

## 2. Benchmark design

**Task.** Subtype discovery on blinded TCGA multi-omics (expression, mutation, methylation, copy
number). The agent works in code — cluster samples, name subtypes, propose a mechanism — through a
fixed tool interface with a bounded call budget and no internet.

**Blinding.** Gene symbols are replaced with opaque `GENE_XXXXX` identifiers, samples with
`SAMPLE_XXXX`, and subtype labels are stripped. A gene codebook is revealed only partway through, at
the agent's third recorded observation, which lets us separate what it established *before* it could
look anything up from what it added afterwards.

**The ladder.** Four information conditions over identical data:

| arm | agent is given | recall is |
|---|---|---|
| G0 | the cohort identity | expected |
| G1 | gene identities, not the cohort | available |
| G2 | nothing — fully blinded | must derive |
| G3 | a **false** cohort label | actively misleading |

G0 and G1 pre-reveal the codebook, so a "recalled" label there is the *expected* behaviour and
carries no criticism. The ladder is experimental setup; the contrast between G2 and G3 is what
carries the argument.

**Scale.** 7 TCGA cohorts (BRCA, LIHC, LUAD, LUSC, OV, PRAD, UCEC) × 3 seeds = 21 episodes per
honest arm; G3 uses 2 mislead pairs (OV↔BRCA, LUSC↔LUAD) × 3 seeds = 12. Three models
(GPT-5.5, Claude Sonnet 5, Gemini 3.5 Flash) × two prompt systems × 75 episodes = **450 episodes**.

---

## 3. Instrument

**Outcome.** Seven biology-grounded checks — survival separation, cluster structure, driver-mutation
association, reference concordance, marker validity, pathway enrichment, mechanism coherence — plus
a cohort-identity gate that zeroes an episode committing to the wrong cancer.

**Process.** A neutral judge reads the agent's *action trace* — its stated intent per analysis step,
its recorded hypothesis checkpoints, and its final submission — and labels how cohort identity was
established: `data-derived`, `mixed`, `recalled-prior`, or `not-established`. The judge is
DeepSeek-v4-pro, deliberately from a family **not** under evaluation, to avoid self-preference.

**Reliability.** The label is a single categorical judgement, so we run the judge **three
independent times over all 450 episodes** (1350 outputs, none malformed) and take the majority, with
ties reported as unresolved rather than broken.

We report agreement rather than assuming it. Per-episode unanimity across the three passes is
**75/198 (38%)** on the arms used for our claims, with pairwise agreement 54–74%. This is
substantial disagreement, and it constrains what may be claimed:

- **Aggregate rates only. A single episode's label is not evidence.**
- A between-arm delta counts only if the two arms' three per-pass rates **do not overlap** — a
  criterion we apply explicitly and which some of our own effects fail.
- One field, `codebook_response`, agrees at nearly 100%, but this is a **ceiling effect** (1168 of
  1350 votes are a single label), not evidence that the judge is reliable in general.

---

## 4. Results

### 4.1 Correctness cannot distinguish derivation from recall

On the blinded arm, grouping episodes by consensus derivation label:

| label | n | mean outcome | median |
|---|---:|---:|---:|
| data-derived | 65 | 0.483 | 0.507 |
| mixed | 43 | 0.478 | 0.473 |
| recalled-prior | 14 | 0.524 | 0.538 |

Derived versus recalled differ by **−0.041** (Mann-Whitney **p=0.19**). Treating the label as
ordinal gives Spearman **ρ=−0.067, p=0.46** (n=122). The effect is absent, not merely small.

Note the direction: the point estimate mildly *favours recall*, though not significantly. We claim
**no detectable relationship in either direction** — not that recall helps, and not that derivation
helps. That is the whole point: the metric is uninformative about how the answer was reached.

**A correctness score is therefore blind to how the answer was reached.** An outcome-only
leaderboard cannot distinguish an agent that discovers from one that recalls, which is precisely the
distinction the discovery claim depends on.

### 4.2 Derivation predicts robustness to misleading data

If grounding were merely stylistic, this would be a curiosity. It is not. On the mislead arm, where
the agent is handed a false cohort label:

| | not fooled | fooled | rate |
|---|---:|---:|---:|
| derived identity | 23 | 6 | **21%** |
| did not derive | 14 | 29 | **67%** |

Fisher exact **p=0.0001**, odds ratio **0.13** (n=72, complete — no exclusions). Agents that worked
out what they were looking at are **three times less likely** to adopt a falsehood presented to
them.

Taken with §4.1: **the property that determines whether an agent survives bad input is invisible to
the metric normally reported.** That gap is the paper's central claim.

### 4.3 Rigor scaffolding buys documentation, not grounding

We ablate the prompt: a prescribed six-stage procedure that structurally forces derive-before-annotate,
against a lean prompt stating there is no prescribed procedure.

- **Outcome is prompt-invariant across all three models** — mean |Δ| = 0.013 (GPT −0.003,
  Sonnet −0.024, Gemini Flash −0.011). Removing the prescribed procedure does not change *what*
  is found, at either capability tier.
- **The staged prompt makes models MORE fooled**, in **3/3 models** (GPT 11→5, Sonnet 8→4,
  Gemini 5→2, of 12). The mechanism is visible in the
  traces: a fooled episode finds genuinely squamous biology, then relabels it to fit the injected
  label rather than rejecting the label.
- **Derivation rises under lean where it moves at all.** Under three-pass consensus with the
  separation test: GPT +38 points, Gemini +14, and Sonnet **−19** — an honest counter-case we report
  rather than average away. On the mislead arm only GPT's +50 separates; Sonnet (+17) and Gemini
  (+8) overlap and we do not claim them.

The scaffold produces more recorded observations and higher documented-support scores while identity
is derived *less* often. It is buying paperwork, not reasoning.

### 4.4 Agents recognise the benchmark by its shape

In 8 episodes the model named the cohort's cancer type from its **sample count**, before any
biological analysis:

> *"1095 samples strongly resembles TCGA-BRCA cohort size (famous PanCancer BRCA n=1097/1095)"*

Dataset shape is the one property blinding cannot hide. This is recall in its most literal form —
recognising the benchmark rather than the biology — and it is a contamination channel that applies
to any benchmark built on a public cohort.

### 4.5 Process evaluation is cheap

Measured from provider-reported token usage across 450 episodes: generating an episode costs
$1.46–$3.89; grading one with all three judge passes costs **$0.0095**. Process evaluation is **0.3%**
of generation. The objection that process-level evaluation cannot scale is not supported by its cost.

---

## 5. Discussion

Our results do not show that agents are useless, or that recall is illegitimate. Efficient recall is
often the right move, and a recalled answer is frequently correct — that is exactly why the problem
is hard to see. What we show is that the *reported metric cannot see the difference*, while the
difference determines behaviour under adversarial conditions.

Two practical consequences. For **benchmark designers**: outcome-only leaderboards systematically
overstate discovery, and blinding must extend to dataset shape, not just identifiers. For
**practitioners** evaluating an agent for a genomics pipeline: a correct answer is not a discovered
one, and the cheap diagnostic is to ask whether the system grounded its claims or recalled them.

---

## 6. Limitations

1. **Cross-family judge bias is untested.** All three judge passes use the same model, bounding
   stochasticity but not family bias. A different-family pass is the obvious next experiment.
2. **n = 21 per honest arm, 12 per mislead arm**, single seed-triple. Small deltas are noise, which
   is why we apply the separation criterion.
3. **Gemini 3.5 Flash is a smaller tier**, so its deltas confound prompt sensitivity with capability.
   The clean ablation is the two flagships.
4. **`identity_derivation` is one categorical judgement** and the lean prompt's own phrasing may nudge
   it. Three-pass consensus and the separation test mitigate this; they do not eliminate it.
5. **We observe stated reasoning only.** Provider adapters strip raw thinking tokens for every model,
   so this is auditable intent, not hidden chain-of-thought — applied uniformly across models.
6. **The blinded arm leaks the cohort through the working directory path.** The executor exposes
   `output_dir`, which contains the cohort name. In 45/126 blinded episodes the agent's own
   reasoning references the path. Between-arm deltas are unaffected (the leak is symmetric in
   Gemini, near-absent in GPT), but absolute derivation rates are inflated. Full analysis in
   `docs/DATA_INTEGRITY_AUDIT.md`; a blinded re-run is required to recover clean absolute rates.
7. **Derivation rate is flat across cohorts** (44–61%), so we find *no* evidence that recall tracks
   literature volume, contrary to an intuition we initially held.
