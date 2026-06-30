# Decision-point explore/exploit rubric (draft)

**Status:** design draft. Not wired into the scorer yet. Companion to
`docs/EXPLORE_EXPLOIT_SCORING.md`.

## Idea
Score the agent's **approach at the 2–3 decisions where exploration vs exploitation
actually bites**, graded from the *trace* (not self-report), as a discrete level →
programmatic points. Combines BiomniBench's machinery (judge picks a level, points
computed from a table, judge validated vs humans) with NatureBench's *content* (the
level **is** the explore/exploit axis: derived-from-data vs recalled/translated-to-a-
known-scheme). Neither paper scores explore/exploit per decision — this does.

**Substrate:** each episode's `run_code` `# WHY:` headers + code + `record_observation`
hypotheses. These are *action-grounded* (tied to what the agent actually ran), so they
dodge the self-report confound that affects the belief-trail confidence metrics.

## The three decision points

### D1 — Partition derivation (*how was the grouping arrived at?*)
| level | meaning | trace cue (from real episodes) |
|---|---|---|
| **Derived** (explore) | grouping built from molecular structure of *this* dataset (variance/PCA/clustering); method chosen from the data | g2_brca: PCA → top-500 variable genes → k-scan with silhouette + survival |
| **Recalled** (exploit) | imported a known scheme/gene-set, or labeled clusters by a textbook scheme without deriving structure | g1_brca: *"use the PAM50 genes specifically to cluster"* |
| **Mixed** | derived structure but forced/framed through a recalled scheme | g0_brca: derives clusters but frames as PAM50/HER2 from the start |
| **None** | no defensible partition |  |

### D2 — Cohort identity (*how was the cancer type / context determined?*)
| level | meaning | trace cue |
|---|---|---|
| **Derived** (explore) | inferred from data evidence accumulated in analysis (mutation pattern, marker expression computed here) | g2_brca: *"GENE_11228 85% mutation in Basal → likely TP53"* → confirmed |
| **Recalled** (exploit) | named the cohort from recognition early, before/without the data work | g1_brca: *"check known breast cancer genes to confirm tissue type"* (step 5) |
| **Hedged** | did not commit / stayed uncertain |  |
| *(G3 only: **Fooled** = adopted the mislead identity — scored in the separate G3 track)* |  |  |

### D3 — Mechanism reasoning (*how was the mechanistic hypothesis formed?*)
| level | meaning | trace cue |
|---|---|---|
| **Derived** (explore) | reasoned from this cohort's data; **revised against the prior when data contradicted it** | g2_brca: *"survival INVERTED from expected PAM50 → CRITICAL REVISION"* |
| **Recalled** (exploit) | retrofitted to the textbook mechanism for the recalled type; ignored contradictory data |  |
| **Mixed / Hedged** | partial grounding |  |
| **None** | no mechanism |  |

## Level → points (process quality)
Exploration = genuine discovery → full credit; recall = a shortcut that *may* still land
the right answer (cf. NatureBench: "methodological translation" is how most successes
happen) → **partial**, not zero.

| level | points |
|---|---|
| Derived | 1.0 |
| Mixed | 0.6 |
| Recalled | 0.5 |
| Hedged | 0.3 |
| None / Fooled | 0.0 |

Per-decision weights (tunable): **D1 partition ×2, D2 identity ×2, D3 mechanism ×1**
→ episode **process score** ∈ [0, 5] (or normalize to 0–1). Judge returns only the
level; points are computed programmatically from this table.

## Keep outcome correctness SEPARATE (the publishable cross-tab)
The level scores *how* (process); a separate correctness flag scores *whether the
decision was right* vs ground truth (partition concordance, true cohort, mechanism
plausibility). The interesting cells:
- **Derived + Correct** — genuine discovery (the goal).
- **Recalled + Correct** — lucky/lazy exploit (right answer, no discovery).
- **Derived + Wrong** — honest exploration that missed.
- **Recalled + Wrong** — confidently wrong recall (worst).

Reporting this 2×2 per arm is the headline result outcome-only scoring cannot produce.

## How it composes (explore/exploit metrics)
- **Per episode:** the three levels (a derivation profile) + the process score.
- **Per arm:** `derived_rate` (fraction Derived) at each decision point.
- **Recall-reliance / exploration signal:** `derived_rate(G2) − derived_rate(G0)` and the
  G0→G1→G2 curve — does the agent *shift* toward derivation when blinding forces it (good
  adaptive balance) or recall regardless (lazy exploit)?
- **G3 (separate track):** D2 with the `Fooled` level = mislead-susceptibility, split by
  early/late drop.

## Judge protocol (to implement)
1. Judge reads the episode trace (WHY headers + code + RO hypotheses) and the discovery.
2. For each of D1/D2/D3 returns **only** the categorical level (+ a one-line evidence quote).
3. Points computed programmatically from the level→points table; correctness flags from
   the existing computational scorers (concordance, cohort gate, etc.).
4. **Validate the judge vs human labels** on a sample (BiomniBench: 597 criteria / 35
   tasks). Target ≥80% exact agreement before trusting at scale.

## Open knobs
- Per-decision weights (2/2/1 above).
- Recalled = 0.5 vs lower (how much to penalize the shortcut).
- Whether "Mixed" is a real level or collapses into Derived/Recalled.
- Judge model choice + the validation set size.
