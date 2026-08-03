# The story — a sketch

*Synthesis as of 2026-08-03. Every number traces to `figures/cot_stats.json` or a generator in
`scripts/`. Evidence strength is marked on every claim: **[SOLID]**, **[WEAK]**, **[NULL]**,
**[RETRACTED]**.*

---

## The story in one paragraph

The field sells autonomous agents as instruments of discovery. We show that claim is, as measured,
**unfalsifiable** — and then make it falsifiable. On a blinded cancer-genomics benchmark, an agent
that *derives* the cohort's identity from data and one that *recalls* it from training score
identically on correctness. But when we plant a false cohort label, the ones that derived resist it
three times more often. **The property that determines whether an agent survives bad input is
invisible to the metric everyone reports.** Worse, the obvious remedy backfires: prescribing a
rigorous staged procedure buys real statistical work, no additional grounding, and *more*
susceptibility to the false premise. Rigor applied to statistics does not protect against a
semantic trap.

---

## The arc

### Act 1 — You cannot currently tell discovery from recall **[SOLID]**

An agent hands you TCGA breast subtypes with a mechanism. Did it derive that from the matrix, or
retrieve it from thousands of papers? For well-studied biology the outputs are *identical*.

We measured it. Grouping 126 blinded episodes by how the judge says identity was established:

```
data-derived     n=65   0.483
mixed            n=43   0.478
recalled-prior   n=14   0.524
                 derived vs recalled: p=0.19 · ordinal rho=-0.067, p=0.46
```

**No relationship in either direction.** (Point estimate mildly favours *recall* — say "no
detectable relationship", never "derivation scores better".) Holds within every arm.

→ *An outcome-only leaderboard cannot distinguish an agent that discovers from one that recalls.*

### Act 2 — But the distinction decides robustness **[SOLID — the strongest result]**

If grounding were merely stylistic this would be a curiosity. Plant a false cohort label:

```
                not fooled   fooled    rate
derived              23         6      21%
did not derive       14        29      67%
                Fisher p=0.0001 · OR=0.13 · n=72 complete
```

→ *Together with Act 1: the deployment-relevant property is invisible to the reported metric.*
**This pairing is the paper.** Neither half alone is publishable; together they are.

### Act 3 — The intuitive fix makes it worse **[SOLID]**

Ablate the prompt: prescribed six-stage procedure vs "no prescribed procedure."

```
                              detailed    lean
outcome (honest mean)          invariant, mean |delta| = 0.013 across ALL THREE models
validation_rigor = high          85%       71%      (2/3 models; Sonnet flat at 95%)
weaknesses: failed execution     10%        6%
weaknesses: omission             48%       51%      <- INDISTINGUISHABLE
fooled by false label          24/36     11/36      3/3 models
```

The scaffold buys **real methodology** — higher rigor, and failures that are *attempted-and-broken*
(`SNF multimodal clustering collapsed degenerately (555/1/1)`) rather than never-attempted. It does
**not** reduce omission. And the arm doing more statistical validation is the arm that gets fooled
more.

→ *"More rigor" is not the fix. Bootstrapping and consensus clustering are orthogonal to whether
the agent questions its premise.*

### Act 4 — Why: the contradiction gets filed, not acted on **[WEAK — say so]**

When the planted label conflicts with the data, the agent registers the conflict and files it as an
anomaly rather than treating it as evidence against the label.

```
marker                            fooled   resisted   Fisher p
"paradox" characterisation          29%        7%       0.051
contradiction noted-not-resolved    51%       29%       0.078
explicit deference to the label     11%        4%       0.37
```

**No marker reaches p<0.05 at n=63.** Three markers agreeing in direction — more than nothing, less
than a result. The qualitative signature is unambiguous:

> *"chose to interpret this as 'squamous-like transdifferentiated LUAD' rather than challenging the
> cohort label — a consequential deference to priors over data."*

The agent had already recovered genuinely squamous biology (KRT5, KRT6A, TP63, SOX2) and relabelled
its own correct finding to fit the frame.

→ *The scaffold trains the agent to document tensions faithfully. Documenting a contradiction is
not acting on one. The output is a well-catalogued wrong answer — harder to catch than a sloppy one.*

### Act 5 — Blinding is harder than it looks **[SOLID + a self-implicating case]**

- **Sample-count recognition [SOLID]** — 8 episodes name the cancer from cohort *size* before any
  biology: *"1095 samples strongly resembles TCGA-BRCA cohort size (famous PanCancer BRCA
  n=1097/1095)."* Dataset shape is the one property blinding cannot hide.
- **Our own leak [SOLID, deferred]** — the executor exposed a working path containing the cohort
  name; in 45/126 blinded episodes the agent reasoned from it. Deltas survive (symmetric in Gemini,
  near-absent in GPT), absolute rates do not.

→ *A benchmark on public data leaks through shape and through plumbing. We found both, and one was
ours.*

---

## Supporting results

- **Derivation deltas under 3-pass consensus [SOLID]** — G2: GPT +38, Sonnet **−19**, Gemini +14, all
  *separated* (per-pass ranges don't overlap). G3: only GPT's +50 separates; Sonnet +17 and Gemini +8
  overlap and are **not claimed**. Sonnet is an honest counter-case we keep rather than average away.
- **Cost [SOLID]** — $1,273 for 450 episodes; grading one costs $0.0095 against $1.46–$3.89 to
  generate it. **Process evaluation is 0.3% of generation** — pre-empts "this doesn't scale".
- **Cohort effect [NULL — report it]** — derivation rate is flat across cancers (44–61%). No
  literature-volume effect. The intuition that recall tracks how well-studied a cancer is
  **is not supported by our data.**

---

## The methodological spine (candidate contribution, not just hygiene)

Two defects were found by reading individual episodes; **neither was visible at any level of
aggregation**:

1. A path leak that let the "blinded" agent read the answer from its working directory.
2. A failed API call that scored `mechanism_grounding = 0.000` across 75 episodes — which produced
   a clean-looking finding (*"the small model collapses without scaffolding"*) that reached memory,
   a talk outline and a manuscript draft before anyone read an episode. **[RETRACTED]**

Both share one shape: **a failure mode that renders as a benign value.** A path that looks like a
save location. An API error that looks like a model resisting a trick. We closed the class — the
scorers now refuse to emit an episode when any LLM component fails — and the retraction is worth
reporting, because a benchmark built on LLM judges will meet this failure and the aggregate is
exactly where it stops looking like one.

*Framing decision needed: a short methods note (credibility-building, honest) or a limitation
sentence (smaller surface). I'd argue for the methods note.*

---

## Honest weak points, in the order a reviewer will hit them

1. **All three judge passes are the same model.** They bound stochasticity, not family bias.
   Everything in Acts 1, 2 and 4 rests on one family's labels. **~450 calls, ~$4 — this is the
   single highest-value outstanding item.**
2. **Per-episode judge agreement is low** — 35–63% unanimous, 54–74% pairwise. We handle it (aggregate
   only; separation test) and state it, but a reviewer will test whether we handle it *consistently*.
3. **n = 21 per honest arm, 12 per mislead arm**, single seed-triple.
4. **Act 4 is not significant.** Do not let it drift into sounding established between drafts.
5. **`recalled-prior` is n=14** in Act 1 — the null is real but thin on one side.
6. **Absolute derivation rates are inflated** by our own path leak (deltas are not).
7. **Gemini is a smaller tier**, confounding prompt sensitivity with capability.

---

## What I'd do next, in order

1. **Cross-family judge pass** — closes #1, the objection that touches every headline claim.
2. **Figures 1 and 2** — Acts 1 and 2 are currently tables; they are the paper and should be seen.
3. **Related work** — thinnest section; NatureBench/BiomniBench are cited but not engaged.
4. **Decide on the OS companion** (`docs/OS_PHASE3_DIAGNOSIS.md`) — a cohort that cannot support its
   own task. Cite in Discussion as evidence that benchmark design needs validating, or omit for scope.
