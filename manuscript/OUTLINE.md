# Outline — section by section, with the evidence each claim rests on

Every claim below is tagged with what supports it. Claims marked **[UNSUPPORTED]** are ones the
narrative wants but the data does not yet carry — they must be cut or backed before submission.

---

## 1. Introduction

**Claim:** Agents are pitched as autonomous discoverers of biology; the pitch is untestable as
usually measured.
→ *Support:* framing. Cite NatureBench (17.8% beat-SOTA; "methodological translation rather than
genuine scientific invention") and BiomniBench-DA as evidence the field already suspects this.

**Claim:** A recalled-but-correct answer is indistinguishable from a discovered one under any
correctness metric.
→ *Support:* **H1, measured** — derived 0.483 vs recalled 0.524, p=0.19; ordinal ρ=−0.067, p=0.46.
Claim "no detectable relationship in either direction" — the point estimate mildly favours recall
but is not significant. This is not a rhetorical point; it is a result. Lead with it.

**Claim:** Grounding is not merely aesthetic — it predicts whether the agent survives bad data.
→ *Support:* **H2, measured** — 21% vs 67% fooled, p=0.0001, OR=0.13, n=72 complete.

**Contribution list:**
1. A benchmark that holds data constant and varies *what the agent is allowed to know* (G0→G3).
2. A process instrument (identity derivation) scored from the action trace by a neutral judge,
   with 3-pass consensus and an explicit separation test.
3. Two results: outcome cannot see grounding; grounding predicts robustness.
4. An instruction ablation showing rigor scaffolding makes models *more* fooled, not less.

## 2. Related work

- NatureBench, BiomniBench-DA — process-aware, but grade a single output and disclose the answer-key
  paper in the prompt, leaving parametric recall wide open.
- LLM-as-judge reliability literature — motivates the 3-pass consensus and the neutral-family judge.
- Data contamination / benchmark memorisation — motivates blinding, and is directly evidenced by our
  shape-leak finding.

**Gap we close:** nobody blinds the data itself, and nobody scores explore-vs-exploit per decision.

## 3. Benchmark design

- **Task:** subtype discovery on blinded TCGA multi-omics (expression, mutation, methylation, CNA).
  Agent works in code: cluster → name subtypes → build mechanism.
- **Blinding:** genes → `GENE_XXXXX`, samples → `SAMPLE_XXXX`, labels stripped, no internet.
- **The ladder (opportunity to recall):** G0 told the cohort · G1 genes visible · G2 fully blind ·
  G3 *misled* with a false cohort label.
- **Substrate:** 7 TCGA cohorts × 3 seeds; G3 = 2 mislead pairs (OV↔BRCA, LUSC↔LUAD).
- **Prompt axis:** staged 6-stage procedure vs lean "no prescribed procedure".
→ *Support:* design; counts verifiable from the run dirs (21 per honest arm, 12 G3, 75/run, 450 total).

**Honest note to keep:** the ladder is setup, not a per-arm claim. G0/G1 pre-reveal the codebook, so
"recalled" is *expected* there — the contrast against G2 is what carries meaning.

## 4. Instrument

- **Outcome scorer:** 7 biology-grounded checks + a cohort-identity gate.
- **Process scorer:** `identity_derivation` ∈ {data-derived, mixed, recalled-prior, not-established},
  judged from the agent's own action trace by a neutral non-benchmarked family (DeepSeek-v4-pro).
- **Reliability:** 3 independent passes over all 450 episodes; consensus by majority, ties reported
  as unresolved rather than broken.
→ *Support:* 1350 outputs, 0 corrupt (`check_judge_integrity.py`).

**Reliability must be reported honestly, not buried:**
- identity_derivation: 35–63% unanimous across 3 passes, 54–74% pairwise.
- **Therefore: aggregate deltas only. Never quote a single episode's label as fact.**
- The separation test — a delta counts only if the two arms' three per-pass rates do not overlap.
- `codebook_response` agrees ~100% but that is a **ceiling effect** (1168/1350 one label), not
  evidence of judge reliability. Say so; a reviewer will otherwise catch it.

## 5. Results

**R1 — Outcome cannot see grounding.** [H1] derived 0.483 vs recalled 0.524; Mann-Whitney p=0.19;
ordinal ρ=−0.067 (p=0.46), n=122. Point estimate mildly favours *recall* — claim **no detectable
relationship in either direction**, never "derivation scores better".
*This is the load-bearing result — give it the first figure.*

**R2 — Grounding predicts robustness.** [H2] 21% vs 67% fooled, p=0.0001, OR=0.13, n=72.

**R3 — Instruction ablation.** Outcome prompt-invariant for **all three models**, mean |Δ|=0.013.
Staged prompt → more fooled **3/3** (11→5, 8→4, 5→2).
**[RETRACTED]** the earlier "Flash collapses under lean 0.511→0.361" was an artifact — a failed API
call scored mechanism_grounding as 0.000 across all 75 Gemini-lean episodes. Do not reinstate it.

**R4 — Derivation deltas under 3-pass consensus.** G2: GPT +38, Sonnet −19, Gemini +14 — all
*separated*. G3: GPT +50 separated; Sonnet +17 and Gemini +8 **overlap → not claimed**.

**R5 — Benchmark recognition.** 8 episodes name the cancer from cohort *size* before any biology.
Verbatim: *"1095 samples strongly resembles TCGA-BRCA cohort size (famous PanCancer BRCA
n=1097/1095)"*. Dataset shape is the one property blinding cannot hide.

**R6 — Cost.** [supporting] $1,273 for 450 episodes; grading costs 0.3% of generating. Pre-empts
"process evaluation doesn't scale".

**Null worth reporting:** derivation rate is flat across cohorts (44–61%), so there is **no
literature-volume effect** in our data. The earlier "recall tracks the literature" idea is
**[UNSUPPORTED]** — cut it.

## 6. Discussion

- Outcome-only leaderboards overstate discovery; the gap is measurable and we measured it.
- Rigor scaffolding buys documentation, not grounding — and costs robustness.
- Practitioner takeaway: evaluating an agent for a genomics pipeline? A correct answer is not a
  discovered one. Check whether it grounded or recalled.
- **Optional:** the osteosarcoma companion result (`docs/OS_PHASE3_DIAGNOSIS.md`) — a discovery
  cohort that cannot support the task at all. Decide: cite as evidence that benchmark design must
  be validated, or omit to keep scope tight.

## 7. Limitations

State plainly, do not bury:
1. Judge replicates are same-family → stochasticity bounded, **cross-family bias untested**.
2. n=21 per honest arm, 12 per G3; single seed-triple.
3. Gemini is Flash tier → its deltas confound prompt with capability.
4. `identity_derivation` is one categorical call; the lean prompt's own wording may nudge it.
   Mitigated by consensus + separation, not eliminated.
5. Stated reasoning only — provider adapters strip raw thinking tokens for every model.

---

## Figures

| # | Content | Source |
|---|---|---|
| 1 | H1 — outcome by derivation class, showing overlap | `cot_stats.json → h1_*` |
| 2 | H2 — fooled rate, derived vs not | `cot_stats.json → h2_*` |
| 3 | Ladder: derivation distribution G0→G3 per arm | `COT_REPORT.html §2` |
| 4 | Ablation: outcome / derivation / observations, detailed vs lean | `ABLATION_REPORT.html` |
| 5 | Judge reliability: unanimity + separation test | `COT_REPORT.html §3` |
| 6 | Evidence box: verbatim shape-leak quote | `COT_REPORT.html §7` |
