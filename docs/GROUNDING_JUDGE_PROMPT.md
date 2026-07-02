# Grounding Judge — prompt draft (for review before code)

**Status:** draft. Nothing in `score_decision_points.py` changed yet. This replaces the
`derived > recalled` ranking with a **strategy tag (neutral) × grounding verdict (scored)**
design, per the fact/grade reframe.

## What changed from the current judge

| | Current (`score_decision_points.py`) | This draft |
|---|---|---|
| Output per decision | one `level` ∈ {derived, recalled, mixed, hedged, none} | **strategy** (neutral tag) + **grounding** (scored) + **contradiction** (audit) |
| Scoring | `derived 1.0 > recalled 0.5` — ranks exploration above exploitation | grounding only: `grounded 1.0 / unsupported 0.4 / anchored 0.0` — ranks *calibration*, strategy-blind |
| Reference biology | judge's own recall (hallucination risk) | **cohort card injected as fact-check context** |
| Anti-hallucination | informal | every trace claim **quoted**; every biology claim tied to a card line |
| Headline | derived-rate by arm | **strategy × grounding cross-tab**; strategy distribution kept as the manipulation check |

The derived-rate gradient (g0 14% → g2 81%) survives as the **strategy-tag distribution by
arm** — relabeled a manipulation check (does blinding shift strategy?), no longer a quality
claim.

## Objective backstops (offline check — NOT judge input)

The judge is **blind** to these. It calls grounding from the trace + card only; the
backstops reconcile against its calls *offline*. That's the only way a backstop stays an
independent check instead of an answer the judge echoes.

- **D1 partition** — concordance (NMI/ARI vs the subtype tables). Measures correctness/match,
  not grounding (a high-NMI partition can be grounded-derived *or* unsupported-recall), so it
  wouldn't pre-answer even if shown — withheld anyway to keep the check clean.
- **D2 identity** — the cohort-identity gate verdict. This one **determines** D2-anchored
  (the mislead case), so injecting it would collapse D2-grounding into the gate re-stated.
  **Withheld** — judge calls D2 blind; reconcile against the gate offline.
- **D3 mechanism** — **no objective backstop.** Fully judge. This is where the card (fact
  guardrail) + mandatory quoting (trace guardrail) do all the work — and why D3 carries the
  lowest weight.

---

## System prompt

```
You assess HOW a cancer-genomics agent reached three decisions, from its analysis trace.
You output two SEPARATE things per decision, and you must not conflate them:

  1. STRATEGY  — a neutral description of the agent's approach. Not a grade. Exploiting a
     confirmed prior is not worse than exploring; both can be correct.
  2. GROUNDING — the quality judgment. This is what is scored.

GROUNDING is defined ONLY as: was the claim supported by THIS cohort's own data at the
time the agent committed to it, and did the agent revise when its own data contradicted it?

CRITICAL — the reference card you are given is a FACT-CHECK guardrail, NOT an answer key:
  - Do NOT rate a claim "grounded" because it matches the card. A claim that matches the
    card but rests on recall, with no supporting computation in THIS cohort's trace, is NOT
    grounded.
  - Do NOT rate a claim "anchored" merely because it departs from the card. A claim that
    derives a valid alternative from this cohort's data IS grounded even if it departs from
    the canonical scheme.
  - Use the card only to (a) check that biology the agent invokes is real, not hallucinated,
    and (b) recognize where the literature is itself uncertain (the card's caveats) — those
    are places a claim needs this cohort's data to stand on, not the textbook's authority.

Judge only what the trace shows the agent actually did. Every factual statement you make
about the trace MUST quote the trace line it rests on (a # WHY header, a record_observation,
or a submitted field). If you cannot quote it, you may not assert it. Every biology claim
you make MUST cite a card fact. Do not import outside knowledge beyond the card.

For each decision return:
  strategy      : "explore"  (built from this cohort's data/structure)
                  "exploit"  (imported a known scheme / recognized cohort / recalled biology)
                  "mixed"    (both — derived structure but framed through a recalled scheme)
  grounding     : "grounded"    (the agent's FINAL committed claim is positively supported by
                                 data it actually computed in this cohort's trace. Revision is
                                 NOT a substitute for support: an agent that asserts and never
                                 tests is not grounded, and revising from one thin claim to
                                 another thin claim is not grounded — judge the end state.)
                  "anchored"    (claim asserted AGAINST this cohort's data, or a recalled claim
                                 left unrevised after the data contradicted it. REQUIRES that
                                 contradicting evidence actually appears in the trace.)
                  "unsupported" (claim rests on no computed data either way — a name-drop; no
                                 contradicting evidence appeared. Tie-break: if you are unsure
                                 between unsupported and anchored and NO contradicting evidence
                                 is in the trace, choose unsupported.)
  contradiction : "revised"  (data contradicted the claim and the agent changed it)
                  "ignored"  (data contradicted the claim and the agent did not change it)
                  "none"     (no contradicting evidence appeared in the trace)
  evidence      : the trace line(s), quoted, that justify the above
  card_ref      : the card fact the agent's biology invokes, or null

Decision-specific guidance:

D1 — PARTITION (how was the sample grouping arrived at?)
  explore  : grouping built from this dataset's structure (variance / PCA / clustering /
             survival separation actually computed here).
  exploit  : imported a known scheme or gene-set to define groups, or labeled clusters by a
             textbook scheme without deriving structure.
  grounded : the partition is supported by structure the trace actually computed.
  anchored : clusters forced onto a recalled scheme this cohort's data does not support.

D2 — IDENTITY (how was the cancer type / biological context determined?)
  explore  : inferred from mutation pattern / marker expression computed here before
             committing.
  exploit  : recognized/named the cohort early from prior knowledge.
  grounded : the identity claim is supported by markers/mutations computed here.
  anchored : identity asserted against contradicting markers (e.g. accepted a given label
             the cohort's own markers contradict — the mislead case).

D3 — MECHANISM (how was the mechanistic hypothesis formed?)
  explore  : reasoned from this cohort's expression / mutation / gene-set results.
  exploit  : retrofitted the textbook mechanism for the recognized cancer type.
  grounded : the final mechanism is positively supported by this cohort's computed expression
             / mutation / gene-set results. (Revision, if any, is logged under contradiction —
             it is not required for grounded and does not substitute for support.)
  anchored : textbook mechanism asserted despite contradicting cohort data, or a canonical
             claim left unrevised after its data support failed (see the card's caveats —
             e.g. assuming a full canonical target set without checking it holds here).

Respond ONLY with valid JSON:
{
  "d1_partition": {"strategy":"...","grounding":"...","contradiction":"...","evidence":"...","card_ref":"..."},
  "d2_identity":  {"strategy":"...","grounding":"...","contradiction":"...","evidence":"...","card_ref":"..."},
  "d3_mechanism": {"strategy":"...","grounding":"...","contradiction":"...","evidence":"...","card_ref":"..."}
}
```

## User message (per episode)

Same trace extraction as today (ordered `# WHY:` headers + `record_observation`
hypotheses + submitted labels/genes/mechanism), plus a prepended context block:

```
COHORT REFERENCE CARD (fact-check only — NOT an answer key):
<the cohort's card section from COHORT_REFERENCE_CARDS.md>

TRACE:
<WHY headers, observations, submitted fields — as today>
```

The objective backstops (concordance NMI, gate verdict) are **not** injected — they
reconcile against the judge's calls offline (see above), keeping them an independent check.

## Scoring (programmatic, outside the judge)

```
GROUNDING_POINTS = {"grounded": 1.0, "unsupported": 0.25, "anchored": 0.0}
#   unsupported lowered 0.4 -> 0.25: a name-drop with no computed support is most of the way
#   to a failure, not halfway to grounded. Knob — revisit after validation.
WEIGHTS          = {"d1_partition": 2.0, "d2_identity": 2.0, "d3_mechanism": 1.0}
#   backstopped decisions (D1/D2) carry 2.0; pure-judge D3 carries 1.0 — intentional.

grounding_score = sum(GROUNDING_POINTS[g] * WEIGHTS[d] for each decision d)   # /5.0 max
```

Audit rules — logged as judge-inconsistency, not hard overrides, caught in validation:
- `grounded` + `contradiction == "ignored"` — grounded shouldn't have ignored a contradiction.
- `anchored` + `contradiction == "none"` — anchored REQUIRES contradicting evidence to exist;
  without it the call should have been `unsupported`. (Symmetric to the above.)

Offline reconciliation (separate from the audit): D1 grounding vs concordance NMI/ARI, D2
grounding vs the withheld gate verdict. Divergences flag either a judge miss or a genuinely
interesting case — reviewed, not auto-scored.

## Reportable outputs

1. **Strategy × grounding cross-tab** (the headline), per decision and pooled:

   |            | grounded | unsupported | anchored |
   |------------|----------|-------------|----------|
   | **explore**|  good exploration  |  floundering  |  wrong turn |
   | **exploit**|  confirmed prior (fine)  |  lucky/idle recall  |  **miscalibration — the failure** |

2. **Strategy distribution by arm** — the manipulation check (does blinding shift
   explore/exploit? the old derived-rate gradient, relabeled).

3. **Grounding score by arm** — the calibration quality, strategy-blind.

## Validation hook (no humans)

Known-answer probes constructed from the cards: e.g. a synthetic OV trace that computes a
partition contradicting TCGA-2011 and does NOT revise → judge must return
`grounding=anchored, contradiction=ignored` at D3. A handful per cohort is the ≥80%-agreement
proxy that replaces a human-labeled set.

**Limit — state it, don't over-trust:** clean-cut probes test that the judge *isn't broken*,
not that it's reliable on the ambiguous middle where real disagreement lives. ≥80% on probes
is NECESSARY, not sufficient. The offline reconciliation against the D1/D2 backstops on *real*
episodes is the second, harder check — the probes alone don't earn trust in D3.
