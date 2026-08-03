# Plan to ICLR 2027

**Planning target:** abstract ~18 Sep, paper ~23 Sep 2026 (ICLR 2026 dates + 1yr; **2027 dates not
posted — re-check before relying on this**). ~6 weeks from 2026-08-03.

**Critical path is NOT compute.** Measured from the existing campaign:

```
450 episodes serial            5.2 days
3 lanes (one per model)        2.0 days
6 lanes (one per run dir)      1.0 days
full rerun cost              ~$1,273        G1-G3 only (324 eps)  ~$920
```

The rerun is ~1–2 days of wall clock. The critical path is **fixing the leak correctly and freezing
the analysis plan before spending the compute** — because a second contaminated run costs six weeks,
not $1,273.

---

## Phase 0 — Make the rerun trustworthy (days 1–3, no API)

Nothing else matters if this is wrong.

**0.1 Fix the agent-visible path.** `executor.py:258` injects `output_dir` into the agent namespace;
it resolves to `.../g3a_lusc_mislead_luad_s42`. Give the agent a **neutral per-episode working
directory** (`<run>/_work/<opaque-id>`), and relocate artifacts into the real episode directory
after the episode ends. The harness keeps the mapping; the agent never sees it.

**0.2 Sweep for every other identity channel.** The path is the one we found, not necessarily the
only one. Audit what reaches the agent: `episode_id`, filenames written by the harness, tool-result
text, error messages, codebook payload, any `cwd`. **G3 is the severe case — its label carries the
true cohort, the planted cohort, *and* the word `mislead`.**

**0.3 Build the pre-flight leak audit.** A script that scans a completed run and asserts **zero**
identity-bearing strings in anything agent-visible. Extend `audit_integrity.py`. This must exist
*before* the rerun so cleanliness is verified rather than assumed.

**0.4 Smoke test** — 6 episodes (1 per run dir, must include a G3), ~$20. Run the leak audit on
them. **Gate: audit returns zero hits, or Phase 0 repeats.**

## Phase 1 — Freeze the plan (days 3–5)

Written and committed **before** clean data exists. This is what converts the messy exploratory
campaign from a liability into good practice.

**1.1 `PREREGISTRATION.md`** — hypotheses, primary vs secondary, tests, exclusions, equivalence
margin, and the hierarchical model spec, all fixed in advance. Git commit is the timestamp.

**1.2 Prespecify the equivalence margin.** The outcome-invariance claim needs a smallest meaningful
difference chosen *now*. Current observed spread is 0.019 across G0–G2 (Kruskal p=0.34) — pick the
margin without reference to that number.

**1.3 Freeze construct definitions.** `strategy` (data-derived/mixed/recalled) and `support`
(grounded/unsupported/anchored) defined before looking at clean results.

**1.4 Pre-commit BOTH directions on every fragile test.** The study must be publishable across
plausible outcomes, which is the point of preregistering:

- **A small G0→G2 process shift is a FINDING, not a null.** The leak inflates the current shift, so
  shrinkage is the *expected* direction. If clean G2 shows agents cannot derive identity and fall
  back to recall, that is **"agents remain in the recall regime even under genuine blinding"** — a
  more alarming paper than "process shifts a lot". Write that framing now.
- **If clean G2 outcome DROPS below G0, that is also a finding:** the outcome metric is
  recall-biased. Component-level prediction to preregister: the drop should appear in
  `reference_concordance` and not elsewhere. Measured on pilot data, that is the *only* component
  with a significant G0 advantage (+0.073, p=0.011); `marker_evidence` is marginally *higher* blind.
- **Scaffold→fooling** may only ever be directional. Decide now that this is acceptable.

**1.5 Multiplicity control** across the five primary tests and any stratified analyses. Specify the
method in the prereg; a prereg reviewer will look for it.

## Phase 2 — Clean rerun (days 5–8)

**2.1 Full 450 episodes + EXTRA G3 SEEDS**, 6 parallel lanes, ~1–2 days, ~$1,470.

**Raise G3 from 3 to 8 seeds.** G3 is only 12 of 75 episodes per run, so this costs ~+16% (~$200)
and it protects the two results that most need protecting. At the current design a modest
attenuation kills the headline reversal outright:

```
                     moderate attenuation (56% vs 39%)
G3 seeds  eps/arm     p
   3         36     0.238      <- current design, dead on any attenuation
   6         72     0.066
   8         96     0.021  SIG
```

This is the best marginal dollar in the plan. Under *strong* attenuation even 12 seeds gives
p=0.076 — so also pre-commit to reporting "directional across 3/3 models" if it lands there,
rather than choosing that framing after seeing the p-value.
Rerun G0 too — it is only ~$350 of the total and having all arms from one clean codebase removes
"the arms aren't comparable" as a reviewer question. Do not economise here.

**2.2 Run the leak audit on all 450. Gate: zero hits.**

**2.3 Keep the old campaign** as the pilot that motivated the confirmatory experiment. Do not delete
it — it is the evidence that the defect was found and fixed.

## Phase 3 — Judging (days 8–10, ~$25)

**3.1 Blinded process judge** — the judge must **not** see the true or planted cohort identity when
classifying provenance. Identity correctness scored separately. *(This is a real change to
`summarize_cot.build_input`, which currently prints `COHORT (blinded to the agent): {cohort}`.)*

**3.2 3-pass consensus** — as before, for stochastic stability.

**3.3 Cross-family pass** — a second family, closing the standing objection.

## Phase 4 — Analysis (days 10–17)

**4.1** Hierarchical/paired models accounting for model, prompt, cohort, seed, cohort-pair.
**4.2** Equivalence test against the Phase-1 margin.
**4.3** Primary tests in the preregistered order.
**4.4** Both axes: `support` (grounded vs unwarranted) as primary — it is the stronger predictor
(OR≈14.9 vs 8.0 in pilot) and matches "recall is not inherently bad"; `strategy` as secondary.

### GATE — decide what the paper is

| pilot finding | survives? | consequence |
|---|---|---|
| G0–G2 process shift | | |
| outcome equivalence | | |
| G3 grounded/unwarranted split | | |
| scaffold → more fooled | | |

- **All four** → full paper, proceed to Phase 5.
- **Outcome flatness only** → too mild for main track; retarget.
- **G3 only** → narrower robustness paper, still viable.
- **None** → the honest contribution is the benchmark-integrity audit → workshop/eval venue.

## Phase 5 — Blind-then-challenge **[STRETCH GOAL — decided 2026-08-03, not a gate]**

Third prompt arm from `TO_BE_TESTED.md`. G3 primary, G2 as honest control: 33 episodes × 3 models ×
~2 seeds. Diagnosis + remedy is materially stronger than diagnosis alone.

**Cut from the critical path.** A clean diagnosis is a complete ICLR submission; diagnosis+remedy is
stronger only if the remedy is real, and a rushed remedy is worse than none. Fast-follow for
camera-ready or the next cycle. Revisit only if Phases 0–4 finish early.

## Phase 6 — Figures and manuscript (days 24–38)

**6.1** Figures 1–4 per the outline (Fig 2 is the hero).
**6.2** Nine-page manuscript, general-ML framing first:
> *not* "we built a cancer-genomics benchmark" — **"outcome metrics do not identify whether agent
> conclusions are grounded in task evidence or inherited from context"**, with cancer genomics as
> the testbed.
**6.3** Supplementary: sample-count cases, scorer-failure audit, cost, leaderboard, textual markers,
per-cohort results.

**Buffer: days 38–42.**

---

## Ownership

| | who |
|---|---|
| Path fix, leak audit, prereg draft, analysis, figures, manuscript | me |
| Every API-spending run (smoke, rerun, judging) | you |
| Human adjudication of a stratified label sample | you |

## Settled 2026-08-03

- Blind-then-challenge → **stretch goal**, off the critical path.
- G3 seeds → **3 to 8** (+~$200).
- Human adjudication → owned by PI, outside this plan's critical path.
- **Claim discipline: motivate broadly, claim narrowly.** Lead with the general measurement problem;
  claim only what seven TCGA cohorts of one task family support. Generality across task families is
  future work — do not let the framing write checks the evidence cannot cash.

## Still open

1. **Full 450 or G1–G3 only?** — recommend full (+$350 buys arm comparability).
2. **Keep Gemini?** — tier-confounded, but it is the shortcut-heavy case (81%) that makes the
   process-variance argument vivid. Recommend keep, disclose the confound.

## Standing risk

The pilot's messiness is a liability **only if the clean run is not preregistered**. With Phase 1
frozen and committed before Phase 2 runs, the narrative is: *an exploratory campaign exposed a
benchmark defect; hypotheses were frozen; the confirmatory experiment followed.* That is a strength.
