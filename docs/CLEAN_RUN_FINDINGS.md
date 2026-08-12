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
| Deriving identity protects against the mislead (H2) | 25 v 75, **p=0.0002** | 66% v 65%, **p=1.0000** | **does not replicate** |
| Agents take identity shortcuts | 45/126 G2 | 1/126 (1%) survives | **artifact of the leak** |
| Staged prompt makes models more fooled | 3/3 models | see §5 | pending lean judge review |
| Outcome cannot see process | supported | supported, weaker | **survives** |

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

**Process and outcome are dissociated.** Shortcut rate spans 0%–33% across the six arms while G2
outcome spans 0.318–0.497. The arm taking the most shortcuts (Gemini/lean, 33%) is not penalised
in proportion. Correlation rho = −0.64, **p = 0.17 at n = 6 arms** — directionally consistent,
not statistically established. State it as such.

**The methodological result.** A process-level finding that looked solid (p=0.0002) was produced
by a harness defect, was invisible in every aggregate report, and vanished under blinding. The
project's own guard predicted it: `shortcut_analysis.py` labelled the shortcut result CONDITION-A
and printed "will largely evaporate in the clean rerun BY DESIGN. Do not build the paper on it."
It evaporated. That is a demonstrable, documented, end-to-end case study in agent-benchmark
validity, with pilot, defect, gate, rerun and cross-judge check all preserved.

---

## 8. Framing options

1. **Lead with the methodology.** The contribution is that agent process metrics are acutely
   sensitive to harness leakage, that the leak is invisible to aggregates, and that blinding
   reverses conclusions. H2's collapse is the central exhibit, not a disappointment. Everything
   needed is already on disk.
2. **Lead with the instrument.** Report that the strategy axis does not populate under blinding
   (2/126) and that a neutral judge classifies half of one model's traces as unreadable — i.e.
   LLM-judged process taxonomies need validation before use. Honest, narrower, and it makes the
   next round's design the natural follow-on.
3. **Do not** lead with "derivation predicts robustness." At n=192, p=1.0, OR=1.01, the data do
   not support it in any direction.

(1) and (2) are compatible and share all the same evidence.

---

## 9. Open items

- `shortcut_analysis.py` prints hardcoded prose ("~80 points", "~3") that no longer matches its own
  computed values (33 points, 0.179). Fix before any report ships.
- `path_cited` (14 episodes) uses the same over-broad regex that produced false positives in
  `audit_integrity`: it matches the bare word "directory". Since `audit_blinding` reports 0 leaks
  on these lanes, the 14 are probably all save-path mentions — meaning the "1% survives" figure in
  §2 rests on the single `count_leak` episode. Needs a per-episode read.
- The pilot's 45/126 "reasoned from path" is an upper bound with the same false-positive mode; a
  cohort-bearing-path rule gives 10/126. Left at 45 pending a manual read (decision: 2026-08-11).
- Lean-wave ablation numbers (`gen_ablation_report.py`) not yet regenerated against the clean run.
- Cross-family judge agreement rests on n=42. A full second-family pass over all 126 G2 episodes
  would settle whether the empty recalled-prior cell is judge or data.
