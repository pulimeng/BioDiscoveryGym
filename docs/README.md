# Explore/Exploit Scoring — map & status (start here)

The one-page index for the explore/exploit study. Read this first; it says what every
artifact is and whether it's **current**, **prototype**, or **superseded**.

**Thesis (see `../memory` / `GRAND_DESIGN.md`):** exploration is valuable; the goal is the
explore/exploit **balance**. Companion finding: LLMs default to recall — a **miscalibration**
(they recall regardless of whether recall is warranted). Sequence: describe how LLMs treat
the two → judge whether the shift is *grounded* → only then prescribe balance. We are at
describe→judge.

---

## Two scoring tracks (both current, run per episode)

| Track | Question | Scorer | Output | Judge / prompt | Status |
|---|---|---|---|---|---|
| **Outcome** | *Is the discovery correct?* | `scripts/score_tcga_episode.py` (EvaluatorV3) | `_v3scores.json` | `biodiscoverygym/scoring/judge.py` | current — 7 components /14 + cohort-identity gate |
| **Grounding** | *Calibration: how did it get there, and was recall warranted?* | `scripts/score_grounding.py` | `_gscores.json` | `scripts/grounding_judge.py` | current — judge validated ~95% |

The tracks are complementary and measure orthogonal things:
- **Outcome** = *right ↔ wrong*.
- **Grounding** = a *quality* axis, `grounded ↔ anchored` (earned ↔ unearned), `unsupported`
  between. **Strategy** (`explore / exploit`) is a **separate neutral tag** — unscored, no
  good/bad direction. Do NOT put `recalled` on the quality axis: recall can be grounded
  (efficient) or anchored (lazy), so it is not the opposite of "earned."

**The payload is the joint cell — outcome × grounding** (neither scorer answers "was recall
warranted?" alone):

|  | grounded | anchored |
|---|---|---|
| **correct** | genuine discovery | right for the wrong reason (lucky recall) |
| **wrong** | honest miss (fine) | **confidently wrong recall — the failure** |

(`strategy × grounding` is a second, within-grounding view where `exploit × anchored` flags
miscalibration; but the correct-vs-wrong failure cell above only exists in the outcome join.)

**Warranted ≠ correct.** Grounding measures *process legitimacy* — was the claim justified by
the evidence *at decision time* — deliberately independent of whether it landed right. So the
off-diagonals are meaningful, not noise: `grounded + wrong` = honest miss, good process,
unlucky (**fine**); `anchored + correct` = process failure even though the answer is right
(lucky recall). That independence is the entire reason there are **two** scorers — a single
correctness score collapses these.

**What the two axes do NOT cover — the grade-1 gap.** Neither scorer measures *was a derived
path available, and would it not have scored worse?* Grounding asks whether the claim was
data-supported, not whether the agent *could have derived instead of recalling*. The grade-1
laziness claim (recall-when-derivation-was-available) rests on that counterfactual, so it
needs a **third signal**: the **G2 arm used as a per-cohort counterfactual** (same model /
cohort, blinded → does derive and scores comparably → proof the derived path was achievable
and non-inferior). That's an *analysis*, not a scorer — grades 2–3 live in the two axes,
grade 1 lives only in the G0/G1-vs-G2 paired comparison. (Empirically so far: agents ground
well *with* priors present, so grade-1 laziness looks unlikely to be the story for Sonnet.)

---

## The grounding apparatus (built + validated 2026-07-02)

Pipeline:
```
episode.json ─ extract_trace ─▶ build_user_msg(trace + cohort CARD) ─▶ grounding_judge
   ─▶ per decision D1/D2/D3: {strategy [neutral], grounding [scored], contradiction [audit]}
   ─▶ grounding_score (/5) + strategy×grounding cross-tab
Validation:  grounding_probes.json ─▶ run_grounding_probes.py ─▶ agreement (gate ≥80%; at ~95%)
```

| File | Role |
|---|---|
| `scripts/grounding_judge.py` | **canonical** prompt + card loader + scoring (single source of truth for the prompt text) |
| `scripts/score_grounding.py` | the scorer → `_gscores.json` + cross-tab report |
| `scripts/grounding_probes.json` | 7-probe answer key (the judge's ground truth) |
| `scripts/run_grounding_probes.py` | validation harness (judge-vs-probes agreement) |
| `docs/GROUNDING_JUDGE_PROMPT.md` | design rationale for the prompt (module is canonical for exact text) |
| `docs/COHORT_REFERENCE_CARDS.md` | fact-check cards — canonical biology per cohort (BRCA/LIHC/LUAD/OV) |

**Grounding levels** (scored): `grounded 1.0 / unsupported 0.25 / anchored 0.0`, weighted
D1×2 D2×2 D3×1. **Strategy** (explore/exploit/mixed) is a neutral tag, not scored — its
distribution by arm is the manipulation check (replaces the old derived-rate).

---

## How to run (needs `ANTHROPIC_API_KEY`; ~1 Sonnet call/episode)

```bash
# validate the judge (no real data):
python scripts/run_grounding_probes.py

# score the money panel (G0/G1 = 30 eps in run1+2), then the full set (63):
python scripts/score_grounding.py results/tcga/run1+2 --arms g0,g1 --save
python scripts/score_grounding.py results/tcga/run1+2 --save
```

Read the output: **grounding score by arm**, **explore-share by arm** (low in G0/G1 = recall
default), and the **strategy × grounding cross-tab** (how much prior-available recall is
`unsupported`/`anchored` vs `grounded` — the laziness/miscalibration evidence).

---

## Superseded / prototype — do NOT use for new work

| File | Was | Now |
|---|---|---|
| `scripts/score_decision_points.py` → `_dpscores.json` | derived>recalled scorer (ranked exploration) | **superseded** by `score_grounding.py` (still produced run1+2's `_dpscores`, cited in EXPLORE_EXPLOIT_SCORING) |
| `docs/DECISION_POINT_RUBRIC.md` | derived/recalled rubric | **superseded** by `GROUNDING_JUDGE_PROMPT.md` |
| `scripts/crosstab_explore_exploit.py` | joined old `_dpscores` + `_v3scores` | prototype; grounding cross-tab now built into `score_grounding.py` |
| `scripts/proto_belief_metrics.py` | belief-trail (effort) metrics | prototype; still relevant as the **conditional corroborator** (ttc/n_obs inside ungrounded cells), not yet wired |
| `docs/EXPLORE_EXPLOIT_SCORING.md` | the design-history record (the reframe reasoning) | keep as rationale; its "pre-commit" header is stale |

**Local-only (not on GitHub):** `run_mech_ab.sh`, `gen_run1_report.py`, `gen_run2_report.py`,
`gen_merged_report.py`, `run_tcga_missings.sh`.

**Reference papers (docs/):** BiomniBench `2026.05.12.724604v1` (process-scoring machinery),
NatureBench `2606.24530v1` (method-translation = exploit, the content).

---

## Current state → next

Judge validated (~95% grounding on probes). Scorer ready. **Not yet run on real episodes.**
Next: run `score_grounding.py` on run1+2 G0/G1 → read the cross-tab. Downstream: add G0 seeds
(grade-1 evidence is thin at n=8), wire the effort corroborator, then the G0/G1-vs-G2 contrast.
