# The pilot is a condition, not a mistake

**Decision 2026-08-03: keep the 450-episode pilot campaign. Do not delete or archive it.**
`results/tcga/ladder/` + `results/tcga/lean/`, 1.4G.

## Why

The pilot was run with an identity shortcut sitting in the plumbing: the agent's working directory
encoded the arm, cohort and seed (and on the mislead arm, the planted cohort and the word
`mislead`). We found it, quantified it, and fixed it — see `DATA_INTEGRITY_AUDIT.md`.

The instinct is to treat that campaign as spoiled. It is not. **It is the shortcut-available
condition of a two-condition experiment**, and the clean rerun is the shortcut-removed condition:

| condition | identity shortcut in plumbing | data |
|---|---|---|
| **A — pilot** | **available** | `results/tcga/{ladder,lean}` (450 eps) |
| **B — clean rerun** | removed (`48d1db0`) | pending |

The manipulation is exactly the thing the paper is about: *does an agent exploit an available
shortcut to a conclusion, and does the outcome score notice?* The pilot already answers the first
half. Shortcut-taking ranged **0% (GPT-lean) to 81% (Gemini, both prompts)** while G2 outcome
spanned only 0.477–0.503 — the arm that shortcut most scored highest and was not penalised at all.

## What the pilot can and cannot support

**CAN — and these are leak-independent or leak-*about*:**
- That the channel exists and is exploited, with per-model rates (`shortcut_analysis.py`).
- That outcome scores do not penalise taking it. This is the thesis in its purest form.
- G0 calibration (109/126 recalled-prior) — G0 discloses identity anyway.
- Cost, the scorer-failure audit, sample-count recognition.
- Anything comparing the two arms where the leak is symmetric (Gemini 17 vs 17) or near-absent
  (GPT 1 vs 0).

**CANNOT:**
- Clean absolute G2 provenance rates. An episode that read the cohort from its folder was not
  deriving.
- Clean G3 robustness magnitudes. The G3 path leaks true cohort, planted cohort *and* `mislead`.

## Using A-vs-B as a paired comparison — the condition

Tempting and defensible, **but only if the path fix is the sole difference.** Between pilot and
rerun we have also: repaired 78 scorer failures, added the refuse-on-judge-failure guard, and plan
to raise G3 from 3 seeds to 8. So:

- Restrict any paired A-vs-B analysis to the **common 3 seeds**, and use the extra G3 seeds for
  power in condition B only.
- Re-score condition A with the current scorer so both sides are scored identically.
- Report it as **quasi-experimental**: the conditions differ in time and in the scorer patch, not
  only in the shortcut. Do not call it a controlled manipulation.

Stated that way it is a real result. Overstated, a reviewer will point out that two campaigns run
weeks apart differ in more than one variable — and they will be right.
