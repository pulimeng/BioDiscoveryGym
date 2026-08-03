# To be tested: a blind-then-challenge protocol

**Status:** Proposed intervention, not an established result.

## Motivation

The current results suggest that prescribing more statistical procedure is not enough to make an
agent question a false premise. The detailed six-stage scaffold increases documented validation
rigor, but it does not improve outcome quality and makes agents more likely to adopt an injected
false cohort label. In several traces, contradictory molecular evidence is recorded faithfully but
then explained away to preserve the supplied identity.

This suggests that the missing capability is not additional statistical validation. It is explicit
validation of the **premise itself**.

## Proposed strategy

Test a two-pass **blind-then-challenge** protocol, provisionally called the **Evidence Firewall**.
The agent must form a data-derived account before receiving contextual information. After context
is revealed, it must treat that information as a hypothesis to test rather than a fact to absorb.

### Pass 1: blinded discovery

Before cohort identity or semantic metadata are revealed, require the agent to commit to:

1. A patient partition supported by the measured data.
2. Molecular signatures distinguishing the proposed groups.
3. Associations with survival or other available phenotypes.
4. A candidate cancer identity, alternatives, and calibrated uncertainty.
5. A compact evidence ledger separating direct observations from interpretations.

The Pass 1 account should be saved before contextual information becomes available and should not
be silently rewritten later.

### Pass 2: context reveal and premise challenge

Reveal the reported cohort identity, clinical annotations, and relevant prior information. Then
require the agent to answer explicitly:

1. What evidence supports the supplied identity?
2. What evidence contradicts it?
3. What observation would falsify the supplied identity?
4. Which alternative identity best explains the contradictory evidence?
5. Could the discrepancy reflect sample mislabeling, contamination, mixture, or an unusual subtype?
6. Does the evidence justify accepting, rejecting, or remaining uncertain about the supplied label?

The agent must compare at least two hypotheses:

- **H1:** the supplied cohort identity is correct;
- **H2:** the strongest identity inferred from the molecular data is correct.

The comparison should use predefined molecular and clinical evidence rather than narrative
plausibility alone.

### Provenance-separated submission

Require every major conclusion to carry one of four provenance labels:

- **data-derived:** supported directly by computations on the current cohort;
- **context-supported:** proposed from metadata or prior knowledge and subsequently supported by the data;
- **prior-only:** imported from external knowledge without cohort-specific support;
- **unresolved conflict:** contextual and measured evidence remain inconsistent.

## Experimental test

Add the Evidence Firewall as a third prompt condition alongside:

1. the existing detailed six-stage scaffold;
2. the existing lean prompt;
3. the proposed blind-then-challenge prompt.

Use the same models, cohorts, seeds, tools, call budget, codebook timing, and outcome scorer. The
critical comparison is on G3, with G2 serving as the honest-label control. Any new run must first
remove cohort-bearing working paths and other avoidable identity leaks.

### Primary hypothesis

The blind-then-challenge protocol reduces adoption of the false G3 cohort label relative to both
the detailed and lean prompts.

### Secondary hypotheses

1. Outcome quality remains approximately equivalent across prompt conditions.
2. Validation rigor does not materially deteriorate under blind-then-challenge.
3. Agents more often resolve contradictions rather than merely record them.
4. Conclusions contain a larger proportion of explicitly data-derived claims.
5. The protocol increases appropriate uncertainty when the data cannot distinguish competing
   identities.

### Failure criteria

The intervention should be considered unsuccessful if it:

- does not reduce false-label adoption;
- reduces fooling only by causing agents to hedge on every episode;
- materially damages outcome quality or analytical rigor;
- produces provenance labels without changing the underlying reasoning;
- or succeeds only for one model or one misleading cohort pair.

## Measurements

### Primary endpoint

- G3 false-label adoption rate, reported overall and by model, prompt, cohort pair, and reveal time.

### Secondary endpoints

- normalized outcome score;
- validation-rigor rating;
- true-cohort recovery rate;
- hedging rate;
- contradiction detected, resolved, or ignored;
- frequency of explicit competing-hypothesis comparisons;
- provenance-label distribution;
- judge agreement and cross-family robustness.

The process judge used for this test should not be shown the true or misleading cohort identity
when classifying derivation or premise-challenge behavior. Identity correctness should be scored
separately from reasoning provenance.

## Interpretation

If successful, this experiment would turn the paper from a diagnosis into a demonstrated design
recommendation: rigorous scientific agents should separate data-derived inference from contextual
interpretation and explicitly test supplied premises against the measurements.

If unsuccessful, that result is also informative. It would show that prompting an agent to challenge
premises is insufficient, motivating architectural separation between a blinded discovery agent and
an independent context-audit agent.

## Language permitted before testing

Until the intervention is evaluated, describe it only as a proposed design implication:

> Our results suggest that improving scientific agents requires more than prescribing rigorous
> analytical procedures. A promising design is to separate data-derived inference from contextual
> interpretation: agents should first commit to a blinded account of the observed structure, then
> treat metadata and prior knowledge as hypotheses to be tested against that account. Explicit
> premise-challenge checkpoints and competing-hypothesis tests may prevent contradictory evidence
> from being documented but ignored.

Do not claim that the Evidence Firewall improves grounding or robustness until the experiment has
been run and evaluated.
