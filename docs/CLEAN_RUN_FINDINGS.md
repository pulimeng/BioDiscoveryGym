# Clean-run findings — what replicated, what did not

**Date:** 2026-08-12 · **Supersedes pilot numbers for every claim below.**

The pilot (`results/tcga/pilot/*`) leaked the cohort name through `output_dir` into the arms that
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
`results/tcga/_archive_deepseek_judge_20260809/`.

**Gates, all passing:**

- `audit_blinding` — 6/6 lanes, 570 episodes, no identity-bearing content reached the agent.
  The gate carries positive controls (`--self-test`, 8/8).
- `audit_integrity` — clean run: 0/77 path-visible, 0 errored identity gates.
- `check_judge_integrity` — 1710 judge outputs parsed, complete, schema-valid, 0 bad.
- `check_judge_symmetry` — no thinking TEXT in any arm; `record_observation` present in all 570.

Deterministic score components reproduce **bit-identically** against the DeepSeek archive across
192 paired episodes. Only the LLM-judged component moved. The judge swap changed the judge and
nothing else.

---

## 2. Headline: two pilot findings did not survive blinding

| claim | pilot | clean run | verdict |
|---|---|---|---|
| Staged prompt makes models more fooled | 3/3 models | 3/3, 84% v 47%, **p=6.0e-08** | **replicates, stronger** |
| Deriving identity protects against the mislead (H2) | 25 v 75, **p=0.0002** | 66% v 65%, **p=1.0000** | **does not replicate** |
| Agents take identity shortcuts via our plumbing | 45/126 G2 | **0/126** on a hand-read | **artifact of the leak** |
| Outcome cannot see process | supported | see §7 — weakened | **qualified** |

The headline is not that everything collapsed. One finding replicated with a far larger effect
than the pilot reported, and it is the one that does not depend on the derivation label at all.

---

## 2b. The staged prompt makes every model more susceptible — replicated

G3 mislead arms, 32 episodes per model per wave, denominators derived from `n_g3` (the pilot's
hardcoded `/12` would have rendered these as `31/12`):

| model | detailed | lean | delta | Fisher p |
|---|---|---|---|---|
| GPT-5.5 | 31/32 (97%) | 18/32 (56%) | −41 pt | 0.00020 |
| Sonnet 5 | 26/32 (81%) | 16/32 (50%) | −31 pt | 0.01686 |
| Gemini 2.5 Pro | 24/32 (75%) | 11/32 (34%) | −41 pt | 0.00231 |
| **pooled** | **81/96 (84%)** | **45/96 (47%)** | **−38 pt** | **6.0e-08** |

3/3 models, same direction, each significant alone. The pilot saw the same direction at smaller
magnitudes (92→42, 67→33, 42→17 percent).

The detailed prompt supplies a staged analytical scaffold. Giving a model more procedural
structure made it **more** likely to commit to an injected false cohort, not less. This does not
route through the derivation label, which is why it is unaffected by §6's instrument problems —
it needs only the identity gate, and 0 of 192 gates errored.

---

## 3. H2 — derivation does not predict robustness

G3 mislead arms, 3-pass consensus derivation label, errored gates **excluded** (0 of them):

| | not fooled | fooled | rate |
|---|---|---|---|
| derived | 47 | 90 | 65.7% |
| not-derived | 19 | 36 | 65.5% |

Fisher exact **p = 1.0000**, odds ratio 1.01, n = 192.

The pilot's protective effect was measured on episodes where the cohort was readable from the
output path. Under blinding the effect is not merely weaker — it is absent, and the point estimates
differ by 0.2 percentage points.

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

1. **Lead with the staged-scaffold result (§2b).** It is the only strong positive: 3/3 models,
   84% → 47%, p=6.0e-08, replicating the pilot's direction with a bigger effect. The claim —
   *more procedural scaffolding makes an agent more susceptible to an injected false premise* —
   is deployment-relevant, needs no derivation label, and survived the blinding that killed H2.
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

**So: 0/126 attributable to our plumbing, 1/126 (0.8%) genuine shape recognition.** The pilot's
45/126 was the leak.

---

## 10. Open items

- The pilot's 45/126 "reasoned from path" is an upper bound with the same false-positive mode; a
  cohort-bearing-path rule gives 10/126, and the clean-run hand-read above suggests the true figure
  is lower still. Left at 45 pending a manual read (decision: 2026-08-11).
- Cross-family judge agreement rests on n=42. A full second-family pass (`laguna`, same gateway)
  over all 126 G2 episodes would settle whether the empty `recalled-prior` cell is judge or data.
  This is now load-bearing for framing option 2.
- `MANUSCRIPT_REPORT.html` and `COT_REPORT.html` not yet regenerated against the clean run.
