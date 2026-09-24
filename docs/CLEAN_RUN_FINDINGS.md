# Clean-run findings — what replicated, what did not

> **⚠ SUPERSEDED FOR ALL JUDGE-DERIVED NUMBERS (2026-08-21).** Every figure below comes from a
> SINGLE judge (nemotron). The study now uses a three-family panel — nemotron / laguna / qwen,
> one pass each over all 570 episodes — and the panel changes several of them:
> adoption **126/133 = 94.7%** (not 127/135 = 94.1%); the G0→G2 strategy shift **+42.9 / +31.5 pt**
> (not +50.8 / +61.9); and two sub-claims are retracted outright — "the scaffold grounds worse"
> and "blinding improves grounding" were both single-judge artifacts. 98/570 episodes have no
> panel consensus on the strategy label.
>
> This file is kept as the single-judge record and for its retraction post-mortems, which stand.
> **For any current number use `manuscript/EXPLORE_EXPLOIT_PAPER.md` §5b and the figure JSONs.**


**Date:** 2026-08-12 · **Supersedes pilot numbers for every claim below.**

> **⚠ CORRECTION 2026-08-13 — §2b IS RETRACTED.** The staged-prompt→more-fooled result reported
> below (84% v 47%, p=6.0e-08) is an **exposure artifact**, not a finding. The planted label is
> gated on the agent's Nth `record_observation` (`agents/cohort_agent.py`, g3a=3rd, g3b=5th, no
> call-count fallback), and the lean prompt logs a median of 4 observations — so most lean episodes
> on the late arm **never received a false label at all** and were scored as "not fooled".
> Conditional on exposure the contrast is null (95.3% v 92.0%, p=0.468). Full analysis:
> `paper/analysis/reveal_mechanism.py` → `manuscript/figures/reveal_mechanism.json`; write-up in
> `manuscript/EXPLORE_EXPLOIT_PAPER.md` R4/R5. §7's recommendation to lead with §2b is void.
>
> **What replaces it:** among the 135 G3 episodes that actually received a label, **127 adopted it
> (94.1%)** — Sonnet 5 42/42 (100%), GPT-5.5 49/51 (96.1%), Gemini 36/42 (85.7%), invariant across
> both cohort pairs (LUSC 97.1%, OV 91.0%), both reveal times (early 92.6%, late 97.5%) and both
> prompts (staged 95.3%, lean 92.0%). Exposed-and-scored is the denominator throughout.
>
> *Figures updated 2026-08-13 after `g3a_ov_mislead_brca_s7` was re-scored: it had submitted an
> empty `proposed_grouping`, and `evaluator_v2` returned before the identity gate, leaving an empty
> verdict that read as "not fooled". Its mechanism described BREAST cancer on an OVARIAN cohort; the
> gate now runs without a partition and returns `mislead_cohort`. All 192 G3 episodes now carry a
> usable verdict.*

The pilot (`results/tcga/_superseded/pilot/*`) leaked the cohort name through `output_dir` into the arms that
were supposed to be blind. This document reports the blinded rerun and states plainly which pilot
findings survived it. Two did not.

---

## 1. What was run

| | detailed | lean |
|---|---|---|
| run root | `results/tcga/clean` | `results/tcga/clean_lean` |
| models | GPT-5.5, Sonnet 5, Gemini 2.5 Pro | same |
| episodes | 285 (95 × 3) | 285 (95 × 3) |
| arms | g0 21, g1 21, g2 21, g3a 16, g3b 16 per lane | same |
| outcome scores | 285 | 285 |
| support scores | 285 | 285 |
| CoT judge passes | 855 (3 × 285) | 855 (3 × 285) |

Judge: `nemotron-3-super` via the St. Jude internal gateway. Not a benchmarked agent family, so
self-preference is not available to it. The earlier DeepSeek judging is archived under
`results/tcga/_superseded/deepseek_judge_20260809/`.

**Gates — one FAILS. Corrected 2026-08-13 after an audit; this block previously read "all passing".**

Every gate below must be given the clean directories explicitly. `scripts/runs_config.py` defaults
to the **pilot**, so a bare invocation audits the contaminated campaign and its result says nothing
about this run.

- `audit_blinding` — **pass**. 6/6 lanes, 570 episodes, no identity-bearing content reached the
  agent. Carries positive controls (`--self-test`, 8/8).
- `audit_integrity` — **pass**. Clean run: **0/126** G2 episodes with an identity-bearing path
  visible, **0/126** reasoned from one, 0 errored identity gates, and (after the 2026-08-13
  re-score) 192/192 G3 episodes carrying a usable verdict. *Denominator corrected from 0/77: the
  earlier figure predated full coverage. The "reasoned from" detector was also corrected the same
  day — it was a bare keyword match on "directory"/"folder"/"file path" and flagged 14/126 clean
  episodes for benign lines like "saved to the output directory" while `path visible` was 0/126.
  It now requires an identity token beside the path mention, the rule `audit_blinding.py` adopted
  in 933e6a9. Positive control: on the contaminated pilot it still reports 118/126 path-visible and
  16/126 reasoned-from, so the check discriminates rather than passing everything.*
- `check_judge_integrity` — **pass**. 1710 judge outputs parsed, complete, schema-valid (10 required
  fields, 3 enum-checked). *Note: before 2026-08-13 this script silently fell back to checking 3 of
  10 fields with no enum validation when `biodiscoverygym` was not importable, while still printing
  "schema-valid". Any earlier citation of this gate was weaker than it read.*
- `check_judge_symmetry` — **FAILS**. No thinking TEXT in any arm, but `record_observation` is
  present in **567/570**, not 570. Three Gemini-2.5-Pro lean episodes recorded **zero** observations
  while making 15–18 `run_code` calls and submitting:
  `clean_lean/gemini25pro/{g0_brca_s7, g0_luad_s7, g1_ucec_s7}`.
  **Consequence:** these three carry no belief trail and no stated-intent checkpoints, so they are
  absent from `conf_start`/`conf_rise` (n=567, not 570) and give the CoT judge nothing to read for
  process. All three are G0/G1, so no G3 or exposure analysis is affected. It does undercut any
  claim that all three models supplied equivalent process evidence — Gemini sometimes supplied
  none.

Deterministic score components reproduce **bit-identically** against the DeepSeek archive across
192 paired episodes. Only the LLM-judged component moved. The judge swap changed the judge and
nothing else.

---

## 2. Headline: two pilot findings did not survive blinding

| claim | pilot | clean run | verdict |
|---|---|---|---|
| Staged prompt makes models more fooled | 3/3 models | ~~3/3, 84% v 47%, p=6.0e-08~~ → **exposure artifact**; conditional on exposure 95.3% v 92.0%, p=0.468 | **RETRACTED 2026-08-13** |
| Deriving identity protects against the mislead (H2) | 25 v 75, **p=0.0002** | 65.7% v 67.3%, **p=0.87** (exposed: 95.7% v 89.7%, p=0.35) | **does not replicate** |
| Agents take identity shortcuts via our plumbing | 45/126 G2 | **0/126** on a hand-read | **artifact of the leak** |
| Outcome cannot see process | supported | see §7 — weakened | **qualified** |

The headline is not that everything collapsed. One finding replicated with a far larger effect
than the pilot reported, and it is the one that does not depend on the derivation label at all.

---

## 2b. The staged prompt makes every model more susceptible — ~~replicated~~ **RETRACTED**

> **Everything in this section is an artifact of unequal exposure.** The denominators below are
> `n_g3` (episodes in the arm), not episodes that received a false label. Those differ enormously by
> wave: detailed 85/96 exposed, lean 49/95. The lean column is mostly counting episodes that were
> never misled. Kept for the record; do not cite. See the correction banner at the top.

G3 mislead arms, 32 episodes per model per wave, denominators derived from `n_g3` (the pilot's
hardcoded `/12` would have rendered these as `31/12`):

| model | detailed | lean | delta | Fisher p |
|---|---|---|---|---|
| GPT-5.5 | 31/32 (97%) | 18/32 (56%) | −41 pt | 0.00020 |
| Sonnet 5 | 26/32 (81%) | 16/32 (50%) | −31 pt | 0.01686 |
| Gemini 2.5 Pro | 24/32 (75%) | 11/32 (34%) | −41 pt | 0.00231 |
| **pooled** | **81/96 (84%)** | **45/96 (47%)** | **−38 pt** | **6.0e-08** |

~~3/3 models, same direction, each significant alone.~~ The pilot saw the same direction because it
ran the same gate — it reproduced the artifact, not the effect.

**Why the reasoning above failed.** The section argued this result was robust *because* it needed
only the identity gate and no derivation label, and 0 of 192 gates errored. That is true and
irrelevant: the gate faithfully reported that these episodes did not commit to the planted cohort.
They did not commit to it because they were never shown it. A correct measurement of a
non-event is still a non-event, and no amount of gate integrity detects a missing denominator.

---

## 3. H2 — derivation does not predict robustness

> **Denominator note, 2026-08-13.** The table below uses all G3 episodes with a verdict, which
> includes the ~30% that never received a false label (see the exposure correction at the top).
> Re-run on the **exposed** denominator the conclusion is unchanged but the numbers and the sign are
> not: derived **90/94 (95.7%)** vs not-derived **26/29 (89.7%)**, OR=2.60, **p=0.354** — still null,
> now pointing at derived episodes being *more* often fooled. Quote the exposed figures.
>
> The same conditioning was applied to **C3** (support) and to the **strategy axis**; both are in
> `manuscript/EXPLORE_EXPLOIT_PAPER.md` §6. C3 inverts to grounded 98.5% vs unwarranted 89.7%
> (p=0.062); the strategy axis **collapses from p=0.0082 to p=1.00** and is retracted.
> **Every candidate predictor of false-label resistance is null on the exposed denominator.**

G3 mislead arms, 3-pass consensus derivation label, errored gates **excluded** (0 of them):

| | not fooled | fooled | rate |
|---|---|---|---|
| derived | 47 | 90 | 65.7% |
| not-derived | 18 | 37 | **67.3%** |

Fisher exact **p = 0.8677**, n = 192.

*(Counts corrected 2026-08-14 after `g3a_ov_mislead_brca_s7` was re-scored — it had an empty verdict
that read as "not fooled". Previously reported as 19/36 and p = 1.0000.)*

The pilot's protective effect was measured on episodes where the cohort was readable from the
output path. Under blinding the effect is not merely weaker — it is absent, and the point estimate
now sits **1.6 points in the wrong direction** (not-derived episodes are marginally *less* often
fooled). On the exposed denominator the same inversion holds and widens; see the denominator note
above.

---

## 4. H1 — not answerable with this instrument

G2 (blinded) outcome by derivation label:

| label | n | mean outcome |
|---|---|---|
| data-derived | 94 | 0.463 |
| mixed | 5 | 0.465 |
| recalled-prior | **2** | 0.383 |

Mann-Whitney p = 0.203; ordinal rank vs outcome rho = +0.036, p = 0.718 (n=101).

**The recalled-prior group has n=2.** H1 is underpowered to the point of being uninformative, and
the reason is itself the finding in §6: under blinding the judge almost never assigns
`recalled-prior`.

---

## 5. The information ladder does not move outcome

Mean normalised outcome, pooled across the three models:

| wave | g0 (cohort disclosed) | g1 | g2 (blinded) |
|---|---|---|---|
| detailed | 0.492 | 0.481 | 0.484 |
| lean | 0.470 | 0.427 | 0.414 |

Telling the agent exactly which cancer it is looking at buys ~0.008 of outcome under the detailed
prompt. This is an independent route to the same conclusion as §7: the outcome score is not
measuring what the disclosure ladder manipulates.

---

## 6. Instrument diagnostics — read before designing the next round

**`recalled-prior` is effectively empty.** 3-pass consensus over 126 blinded G2 episodes:

| wave | derived | mixed | recalled-prior | not-established |
|---|---|---|---|---|
| detailed | 48 | 1 | **0** | 14 |
| lean | 46 | 4 | **2** | 10 |

Removing the staged scaffold did not release recalled-prior episodes — 2 of 126, both Gemini. The
category the strategy axis exists to detect does not populate under blinding. Either agents really
do derive, or the judge will not assign the label; §6.3 says it is at least partly the latter.

**Gemini is unclassifiable in half its traces.** `not-established` by model, both waves pooled
(n=42 each): Gemini **20**, GPT 3, Sonnet 1. Any Gemini process number rests on the half of its
episodes the judge could read, and that subset is not random.

**Judge stability.** Across 318 judged items the 3-pass panel was unanimous on 62% (198), with 14
unresolved ties dropped. Unanimity is not high; per-episode labels should not be treated as
point facts.

**Cross-family agreement is 67%.** On 42 G2 episodes judged by both DeepSeek and Nemotron, exact
agreement was 28/42. Disagreements are *directional*: Nemotron shifts toward `data-derived`
(mixed→derived ×8) and never assigned `recalled-prior`, where DeepSeek assigned it twice. So the
empty recalled-prior cell is partly a judge property. Both judges agree the label is rare; they
disagree on the derived/mixed boundary.

**Derivation rate is cohort-dependent**, 50%–83% (OV 9/18 lowest; PRAD and LUAD 15/18 highest).
Cohort is a confound in any pooled process comparison.

---

## 7. What does survive

**Process and outcome dissociation — weakened, and the shortcut route is now unusable.** After the
false-positive fix (§9) the shortcut rate spans only 0%–5% across the six arms while G2 outcome
spans 0.318–0.497 (18 points). Process now varies *less* than outcome on this metric, which is the
reverse of the pilot's framing, and rho = −0.21 at p = 0.69, n = 6 arms. **Do not cite shortcut
rate as evidence of dissociation.** The claim has to rest on the derivation/grounding
distributions and the flat ladder in §5 instead — where a 24-point spread in `not-established`
between models (§6) coexists with an 0.008 outcome spread across the disclosure ladder.

**The methodological result.** A process-level finding that looked solid (p=0.0002) was produced
by a harness defect, was invisible in every aggregate report, and vanished under blinding. The
project's own guard predicted it: `shortcut_analysis.py` labelled the shortcut result CONDITION-A
and printed "will largely evaporate in the clean rerun BY DESIGN. Do not build the paper on it."
It evaporated. That is a demonstrable, documented, end-to-end case study in agent-benchmark
validity, with pilot, defect, gate, rerun and cross-judge check all preserved.

---

## 8. Framing options

1. ~~**Lead with the staged-scaffold result (§2b).**~~ **VOID 2026-08-13** — §2b is an exposure
   artifact (see the correction banner). Lead instead with the disclosure ladder (`EXPLORE_EXPLOIT_PAPER.md`
   R1–R3: the ladder swings identity strategy 6→68% while outcome moves 0.09–0.48 SD, and disclosure
   degrades grounding) and, on the mislead arm, with **94.1% adoption (127/135) once actually exposed**.
   Supporting cast: the flat information ladder (§5) and the model-level process spread (§6).
2. **Lead with the methodology.** Agent process metrics are acutely sensitive to harness leakage,
   the leak is invisible in every aggregate, and blinding reverses conclusions. H2's collapse is
   the central exhibit. The full chain is on disk: pilot, defect, gate, rerun, cross-judge check.
3. **Do not** lead with "derivation predicts robustness" (p=1.0, OR=1.01, n=192), and do not cite
   shortcut rate as dissociation evidence — after the §9 fix it spans 5 points against outcome's
   18, which argues the opposite.

(1) and (2) are compatible and share all the same evidence. (1) is the stronger paper; (2) is the
more novel contribution. A paper that does (1) as the result and (2) as the method section is
both, and every number it needs already exists.

---

## 9. The shortcut hand-read — resolved

All 15 flagged episodes were read individually on 2026-08-12 rather than trusted to the regex.

**`path_cited`: 14 flagged, 0 real.** Every one was the agent saying where it would *save* a file
("a JSON file named grouping.json in the output directory") or listing `data/` to find a GMT.
None named the cohort near the match. `audit_blinding` independently reports no leak on these
lanes. `PATH_CITED` now requires the cohort to appear within 150 chars of the mention, mirroring
`count_based_identity`'s validated window; that alone drops 14 → 1. The survivor,
`GPT-5.5/lean g2_lihc_s7`, is adjacency of two unrelated statements — a status note ("grouping
file path ready") followed by a biological conclusion ("The dataset is hepatocellular carcinoma")
— and was rejected on reading. The regex was **not** tuned further to force it to zero; that would
be fitting the probe to this run. **Quote 0; treat the automated 1 as a conservative upper bound.**

**`count_leak`: 1 flagged, 1 real.** `Sonnet 5/lean g2_brca_s123`, pre-reveal:

> "sample size (**1095**), gene counts, mortality rate (~14%), age range (27-90y) strongly
> resemble **TCGA-BRCA (breast cancer)** cohort characteristics"

This is genuine benchmark recognition from dataset shape — an agent-side capability, not a harness
defect, and `audit_blinding` explicitly documents that shape stays recognisable by design.

**So: 0/126 attributable to our plumbing, 1/126 (0.8%) genuine shape recognition.**

*Superseded 2026-08-14 — the pilot comparison figure is **16/126**, not 45/126.* The 45 came from a
detector that matched the bare words *directory / folder / file path* with no requirement that the
path carry identity; it produced 14 false positives on the clean run. Requiring an identity token
beside the path mention (the rule `audit_blinding` adopted in `933e6a9`) gives **16/126 pilot vs
0/126 clean — same detector on both sides**, which is the only defensible comparison. Cite 45/126
only as the superseded, false-positive-prone result.

---

## 10. Open items

- ~~The pilot's 45/126 "reasoned from path" is an upper bound … left at 45 pending a manual read.~~
  **CLOSED 2026-08-14.** `audit_integrity.py` now requires an identity token within 120 characters of
  the path mention, matching `audit_blinding`. Result: **pilot 16/126, clean 0/126**, one detector,
  both campaigns. Positive control confirms the check still discriminates rather than passing
  everything.
- Cross-family judge agreement rests on n=42. A full second-family pass (`laguna`, same gateway)
  over all 126 G2 episodes would settle whether the empty `recalled-prior` cell is judge or data.
  This is now load-bearing for framing option 2.
- ~~`MANUSCRIPT_REPORT.html` and `COT_REPORT.html` not yet regenerated against the clean run.~~
  **DONE 2026-08-13** — all five reports (`MANUSCRIPT`, `ABLATION`, `COT`, `LADDER_3MODEL`, `COST`)
  regenerate against the clean run, carry derived episode counts (570) and judge attribution
  (nemotron-3-super), and use exposed-and-scored denominators on G3.
