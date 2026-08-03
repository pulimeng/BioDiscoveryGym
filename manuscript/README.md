# Manuscript — ICLR 2027

**Target:** abstract ~18 Sep, paper ~23 Sep 2026 *(ICLR 2026 dates +1yr; 2027 dates not posted —
verify before relying on them)*.

## Read in this order

| # | file | what it is | authority |
|---|---|---|---|
| 1 | `PLAN.md` | execution plan, phases, gates, ownership | **current** |
| 2 | `RECOMMENDED_OUTLINE.md` | the paper's structure, section by section | **authoritative outline** |
| 3 | `STORY.md` | the narrative arc, every claim tagged SOLID/WEAK/NULL/RETRACTED | current |
| 4 | `DRAFT.md` | running prose draft | **pilot-based — see below** |
| 5 | `TO_BE_TESTED.md` | blind-then-challenge remedy | proposed, stretch goal |
| — | `archive/OUTLINE_superseded.md` | earlier outline, kept for its evidence tags | superseded |

`figures/*.json` holds every cited statistic. Regenerate before any revision:

```bash
python scripts/cot_deepdive.py        # -> figures/cot_stats.json
python scripts/shortcut_analysis.py   # -> figures/shortcut_stats.json
python scripts/audit_integrity.py --json figures/integrity_audit.json
```

## ⚠️ Status of the numbers

**Every G1/G2/G3 result in `DRAFT.md` and `STORY.md` comes from the pilot campaign, which was
path-contaminated.** The harness is fixed (commit `48d1db0`) but no code change unsees what those
agents read. Treat all of it as **provisional pending the clean rerun** — that rerun is the whole
point of `PLAN.md`.

What is **not** affected:
- **G0 calibration** (109/126 recalled-prior) — G0 discloses identity anyway.
- **The conceptual claim** that correctness cannot certify provenance — that does not depend on our data.
- **Cost, scorer-failure audit, sample-count recognition** — independent of the leak.

## The argument

| | |
|---|---|
| **Outcome cannot see *strategy*** | derived 0.483 vs recalled 0.524, p=0.19; ordinal ρ=−0.067, p=0.46 — no relationship either direction |
| **Grounding predicts robustness** | unwarranted vs grounded identity → **81% vs 22%** fooled, OR=14.9, p<0.0001 |
| **Process varies, outcome doesn't** | shortcut-taking 0%→81% across arms; outcome 0.477→0.503 |

The instrument has **two axes** and they are not interchangeable: *strategy* (derive/mix/recall) is
scored neutrally — efficient recall is legitimate — while *support* (grounded/unsupported/anchored)
is the one that carries the failure. 12 of 14 recalled G2 episodes are **grounded**. The claim is
**unwarranted** recall, never recall as such.

## Claim discipline

**Motivate broadly, claim narrowly.** Lead with the general measurement problem; claim only what
seven TCGA cohorts of one task family support. Generality across task families is future work.

Do not reinstate: *"Flash collapses under lean"* **[RETRACTED** — a failed API call scored
`mechanism_grounding`=0.000 across 75 episodes**]**; *"blinded agents recognise rather than
derive"* **[NOT SUPPORTED** — 52% data-derived, 94% grounded**]**; *"recall tracks literature
volume"* **[NULL** — flat 44–61% across cohorts**]**.

## Open

1. **Clean rerun** — the critical path. Everything G1–G3 is provisional until it lands.
2. **Cross-family judge pass** — all three passes are one family; bounds stochasticity, not bias.
3. **Human adjudication** of a stratified label sample — owned by the PI. The whole contribution is
   a process *measure*; a reviewer will want it anchored to human judgement.
4. **Preregistration** — must be committed *before* the rerun. This is what converts the messy pilot
   into defensible practice.
