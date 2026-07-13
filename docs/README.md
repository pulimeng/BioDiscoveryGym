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
| **Evidential support** | *Calibration: how did it get there, and was recall warranted?* | `scripts/score_support.py` | `_supportscores.json` | `scripts/support_judge.py` | current — judge validated ~95% |

The tracks are complementary and measure orthogonal things:
- **Outcome** = *right ↔ wrong*.
- **Evidential support** = the quality axis, `grounded ↔ anchored` (well-supported ↔ asserted
  against the data), `unsupported` (no support) between. **Strategy** (`explore / exploit`) is
  a **separate neutral tag** — unscored, no good/bad direction. Do NOT put `recalled` on the
  support axis: recall can be grounded (efficient) or anchored (lazy), so it is not the
  opposite of "supported."

**The payload is the joint cell — outcome × support** (neither scorer answers "was recall
warranted?" alone):

|  | grounded | anchored |
|---|---|---|
| **correct** | genuine discovery | right for the wrong reason (lucky recall) |
| **wrong** | honest miss (fine) | **confidently wrong recall — the failure** |

(`strategy × support` is a second, within-support view where `exploit × anchored` flags
miscalibration; but the correct-vs-wrong failure cell above only exists in the outcome join.)

**Warranted ≠ correct.** Evidential support measures *process legitimacy* — was the claim
justified by the evidence *at decision time* — deliberately independent of whether it landed
right. So the
off-diagonals are meaningful, not noise: `grounded + wrong` = honest miss, good process,
unlucky (**fine**); `anchored + correct` = process failure even though the answer is right
(lucky recall). That independence is the entire reason there are **two** scorers — a single
correctness score collapses these.

**What the two axes do NOT cover — the grade-1 gap.** Neither scorer measures *was a derived
path available, and would it not have scored worse?* Evidential support asks whether the
claim was data-supported, not whether the agent *could have derived instead of recalling*. The grade-1
laziness claim (recall-when-derivation-was-available) rests on that counterfactual, so it
needs a **third signal**: the **G2 arm used as a per-cohort counterfactual** (same model /
cohort, blinded → does derive and scores comparably → proof the derived path was achievable
and non-inferior). That's an *analysis*, not a scorer — grades 2–3 live in the two axes,
grade 1 lives only in the G0/G1-vs-G2 paired comparison. (Empirically so far: agents ground
well *with* priors present, so grade-1 laziness looks unlikely to be the story for Sonnet.)

---

## The evidential-support apparatus (built + validated 2026-07-02)

Pipeline:
```
episode.json ─ extract_trace ─▶ build_user_msg(trace + cohort CARD) ─▶ support_judge
   ─▶ per decision D1/D2/D3: {strategy [neutral], support [scored], contradiction [audit]}
   ─▶ support_score (/5) + strategy×support cross-tab
Validation:  support_probes.json ─▶ run_support_probes.py ─▶ agreement (gate ≥80%; at ~95%)
```

| File | Role |
|---|---|
| `scripts/support_judge.py` | **canonical** prompt + card loader + scoring (single source of truth for the prompt text) |
| `scripts/score_support.py` | the scorer → `_supportscores.json` + cross-tab report |
| `scripts/support_probes.json` | 7-probe answer key (the judge's ground truth) |
| `scripts/run_support_probes.py` | validation harness (judge-vs-probes agreement) |
| `docs/SUPPORT_JUDGE_PROMPT.md` | design rationale for the prompt (module is canonical for exact text) |
| `docs/COHORT_REFERENCE_CARDS.md` | fact-check cards — canonical biology per cohort (BRCA/LIHC/LUAD/OV) |

**Evidential-support levels** (scored): `grounded 1.0 / unsupported 0.25 / anchored 0.0`,
weighted D1×2 D2×2 D3×1. **Strategy** (explore/exploit/mixed) is a neutral tag, not scored —
its distribution by arm is the manipulation check (replaces the old derived-rate).

---

## How to run (needs `ANTHROPIC_API_KEY`; ~1 Sonnet call/episode)

```bash
# validate the judge (no real data):
python scripts/run_support_probes.py

# score the money panel (G0/G1 = 30 eps in run1+2), then the full set (63):
python scripts/score_support.py results/tcga/run1+2 --arms g0,g1 --save
python scripts/score_support.py results/tcga/run1+2 --save
```

Read the output: **support score by arm**, **explore-share by arm** (low in G0/G1 = recall
default), and the **strategy × support cross-tab** (how much prior-available recall is
`unsupported`/`anchored` vs `grounded` — the laziness/miscalibration evidence).

---

## Superseded / prototype — do NOT use for new work

Superseded pieces are moved to `scripts/archive/` and `docs/archive/`.

| File | Was | Now |
|---|---|---|
| `scripts/archive/score_decision_points.py` → `_dpscores.json` | derived>recalled scorer (ranked exploration) | **archived** — superseded by `score_support.py` (produced run1+2's `_dpscores`, cited in EXPLORE_EXPLOIT_SCORING) |
| `docs/archive/DECISION_POINT_RUBRIC.md` | derived/recalled rubric | **archived** — superseded by `SUPPORT_JUDGE_PROMPT.md` |
| `scripts/archive/crosstab_explore_exploit.py` | joined old `_dpscores` + `_v3scores` | **archived** — template for the pending outcome×support join (needs repointing to `_supportscores`) |
| `scripts/proto_belief_metrics.py` | belief-trail (effort) metrics | prototype, kept top-level; the **conditional corroborator** (ttc/n_obs inside ungrounded cells), not yet wired |
| `docs/EXPLORE_EXPLOIT_SCORING.md` | the design-history record (the reframe reasoning) | keep as rationale; its "pre-commit" header is stale |

**Repo layout:** data-download scripts grouped under `scripts/download/`; superseded code in
`scripts/archive/`, superseded docs in `docs/archive/`.

**Reports:** `scripts/gen_report.py` — one parameterized generator (`--model "Label:dir[:#color]"`,
repeatable) for any set of runs; auto-includes grounding when `*_supportscores.json` exist.
Replaced the old per-run one-offs (`gen_run1/run2/merged_report.py`, now removed).

**Local-only (not on GitHub):** `run_mech_ab.sh`, `run_tcga_missings.sh`.

**Reference papers (docs/):** BiomniBench `2026.05.12.724604v1` (process-scoring machinery),
NatureBench `2606.24530v1` (method-translation = exploit, the content).

---

## Current state → next

**Sonnet run1+2 is fully scored** (62 eps, both tracks). Result: the two axes are orthogonal
(support ≠ correctness — the design works), Sonnet grounds well, and anchoring is adversarial
(G3), not spontaneous — the "unwarranted recall is common" thesis did **not** hold for a
frontier model. So the next move is **discriminate across models**: the **model ladder**
(Sonnet / Opus / GPT-4.1 / Gemini) tests whether the correct-but-unwarranted cell fills for
weaker models. One agent, provider adapters (`agents/adapters/`) — see **`docs/MODEL_LADDER.md`**
(setup, smoke test, full run). Downstream: add G0 seeds (grade-1 counterfactual), wire the
effort corroborator (ttc/n_obs), build the outcome×support join script.
