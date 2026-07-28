# OS Task A — why Phase 3 never scores, and what is actually wrong

**Date:** 2026-07-28 · **Status:** diagnosis complete, redesign NOT decided · **Scripts:**
`scripts/internal_robustness.py`, `scripts/target_qc.py`

## The question

OS Phase 3 (TARGET-OS replication, 5 pts) sits near the floor for every episode ever run.
`target_survival_replication` is exactly 0.0 in 5 of 9 run10 episodes and never exceeds 0.10,
while `target_coexpr_replication` discriminates fine (0.52–0.81). Phase 3 totals 1.22–1.61 / 5.

Two candidate explanations, with opposite consequences:

1. **The agent is failing** — its signatures are overfit; better discovery discipline would fix it.
   Implies: add an internal-robustness loop, iterate until stable, then score TARGET.
2. **The setup is unwinnable** — no signature could pass, whatever the agent does.
   Implies: redesign the task; iterating would only manufacture false positives.

The three experiments below say it is (2), and locate the cause in **SGH-OS, not TARGET-OS**.

---

## Finding 1 — Internal robustness does not predict external replication

`scripts/internal_robustness.py` — 22 existing episodes (run9_marker 13 + run10_withval 9),
retrospective, no new episodes needed.

Per episode: bootstrap sign stability (B=200), K-fold CV signature, leave-deciles-out HR SD,
all computed on SGH-OS only (what an agent could see while iterating); external = signed
Spearman vs TARGET-OS OS-time (the existing Phase 3 convention).

| internal metric | vs `target_rho` | p |
|---|---|---|
| `boot_sign_stability` | ρ = −0.025 | 0.911 |
| `cv_hr` | ρ = −0.272 | 0.221 |
| `ldo_hr_sd` | ρ = −0.130 | 0.563 |
| `insample_hr` | ρ = −0.295 | 0.182 |

Nothing significant. But the **distributions matter more than the correlations**:

```
boot_sign_stability   0.957 – 0.999      every episode at ceiling
cv_hr                 0.35  – 0.80       every episode strongly "protective"
target_rho           -0.199 – +0.084     every episode null
```

Every episode looks internally excellent; every episode fails externally. The correlation is null
largely because **neither variable varies** — the internal/external gap is uniform, not
episode-specific. There is no gradient for an agent to iterate toward: bootstrap stability is
already ~0.99 on the first attempt.

## Finding 2 — "Internally robust" is a selection artifact, not a mark of quality

Same script, `--baselines 5`. Two naive pickers sized like a real signature, scored through the
identical pipeline: random genes (no survival information) and top-N-by-univariate-Cox-p in SGH
(the dumbest possible "discovery").

| arm | n | boot_stability | insample_hr | cv_hr | target_hr |
|---|--:|---|---|---|---|
| **agent** | 22 | 0.985 [.95,1.00] | 0.501 [.32,.64] | 0.508 [.34,.69] | 1.023 |
| **top-Cox pick** | 5 | 0.989 [.97,.99] | **0.277** [.22,.36] | 0.282 [.20,.37] | 0.922 |
| **random genes** | 5 | 0.784 [.72,.82] | 0.571 [.51,.64] | 1.021 [.76,1.56] | 1.099 |

- The agent is **indistinguishable from top-Cox** on bootstrap stability (0.985 vs 0.989) and
  **worse** on in-sample HR (0.501 vs 0.277). The dumbest picker looks better internally.
- All three arms are **equally null externally** (0.92 / 1.02 / 1.10).
- Random genes at 0.784 mark the floor where no survival selection happened.

An internal-robustness loop would therefore reward the agent for behaving *more* like naive
top-Cox selection — maximising precisely the metric that carries no external information.

**Caveat (important).** `cv_hr` is **not** an honest internal estimate for the agent/top-Cox arms:
gene *selection* used all 91 patients including survival and sits outside the CV folds, so the
leak inflates it. The random arm has no selection leak and correctly collapses 0.571 → 1.021,
which demonstrates the CV machinery itself is sound. The bootstrap-stability comparison is
unaffected. Finding 3's self-capacity test does selection *inside* the folds and is the honest
version.

## Finding 3 — TARGET-OS is sound; SGH-OS is the limiting cohort

`scripts/target_qc.py` — the check that had to happen before blaming anyone.

**Structure — clean.** Same normalization, no variance collapse, adequate follow-up.

```
SGH-OS     n=91  events=37 (41%)  median FU=1296d
TARGET-OS  n=85  events=29 (34%)  median FU=1451d
gene overlap 18605   value range SGH [0,16.9] TARGET [0,17.0]
median per-gene SD   SGH 0.660   TARGET 0.649
```

**Positive controls.** `cytolytic` HR=0.60 p=0.026 **PASS**; hypoxia / proliferation / ifn_gamma ns.
NOTE: this battery is expression-only and does **not** include `metastasis_at_dx` (clinical), which
is why it reads 1/4 here versus the 3/5 recorded for the run9/run10 validation — different control
sets, not a contradiction.

**Self-capacity — the decisive test.** CV signature with selection *inside* the folds, scored on
held-out patients. This is the ceiling each cohort can support on its own survival:

```
TARGET-OS -> TARGET-OS (CV)    HR=0.51   p=0.00037     STRONG
SGH-OS    -> SGH-OS    (CV)    HR=0.83   p=0.211       NULL
```

**TARGET-OS predicts its own survival. SGH-OS does not.** The discovery cohort contains no
cross-validatable prognostic signal — so the in-sample HRs of 0.28–0.50 seen for agent *and*
baseline arms are selection artifact, confirming Finding 2 independently.

**Symmetry.** Transfer fails in both directions, so this is not a one-sided defect:

```
SGH -> TARGET   HR=1.23  p=0.29     fails
TARGET -> SGH   HR=1.30  p=0.134    fails
```

---

## What this means

**Phase 3 is unwinnable as specified.** The benchmark asks the agent to discover a prognostic
signature in a cohort that demonstrably does not contain one under honest validation. This is not
an agent failure and not a TARGET defect.

**Do not let the agent iterate against TARGET.** With 29 events, TARGET needs HR ≥ 1.44 for bare
p<0.05 and HR ≥ 1.68 for 80% power — far above any plausible generalizable expression signature.
Iterating converts the held-out cohort into a selection set:

```
10 attempts -> 40% chance of a spurious p<0.05
20 attempts -> 64%
```

That would manufacture "replication" while destroying the only property that makes Phase 3
publishable.

## Redesign options (NOT decided)

1. **Swap roles** — discover in TARGET (which has signal), validate in SGH. Cost: TARGET is
   expression-only, so the multi-modal aspect that makes Task A distinctive is lost.
2. **Change the discovery target** — from prognosis to what SGH *can* support: subtype structure
   and co-expression modules, which already replicate at ρ=0.81. Narrows the claim from "finds
   prognostic biomarkers" to "finds real structure", but is honest to the data.
3. **Pool cohorts** — GSE21257 (n=53), GSE16091 (n=34), GSE39055 (n=37) would take events from
   29 to ~60–90 and pull the detectable HR down to ~1.34. Still not enough for a subtle signature.
4. **Keep prognosis, score against the measured ceiling** — report Phase 3 relative to the
   self-capacity ceiling rather than as an absolute.

## Open items

- **Stability of Finding 3** — self-capacity is being re-run across 3 topk × 3 seeds to confirm
  the SGH null and TARGET signal are not one lucky split. Treat the exact HRs as provisional
  until that lands; the direction is what matters.
- **Confound in TARGET's self-capacity** — metastasis-at-diagnosis is a large effect in TARGET-OS
  and may be readable from expression. That is real prognostic signal, but closer to clinical
  stage than tumour biology. Worth checking before leaning on "TARGET is the better cohort".
- Original open item stands: GSA HRA003260 full WES + CNA would let SGH re-run without the
  `_noCNA_noSNV` tag.
