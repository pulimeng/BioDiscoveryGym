# Methodology — principles this project learned the hard way

*Written 2026-08-04, after an audit that retracted one finding, three false-positive gates, a
silently corrupted scoring run, and a blinding leak we shipped ourselves.*

Every principle below is here because we violated it first. They are written with the incident
attached, because a principle without its incident is forgettable — and because the incidents are
the evidence that the principle is worth the cost.

---

## 1. The failure mode that renders as a benign value

**The deepest one. Every serious defect this project found had the same shape.**

| what failed | what it looked like |
|---|---|
| Working path contained the cohort name | a save location |
| LLM judge threw an exception | `0.0` — a real score |
| Identity gate errored | *"not fooled"* — a model resisting a trick |
| Audit found no episodes to check | `PASS` |

None of these raised. None appeared in a log as an error. Each produced a value a downstream
consumer would accept without question, and one of them — `mechanism_grounding = 0.000` across 75
episodes — became a clean-looking finding that reached project memory, a talk outline and a
manuscript draft before anyone read an individual episode.

**Rule: never let an error state share a code path with a legitimate value.** If a component can
fail, its failure must be structurally distinguishable from its success. The scorers now refuse to
write a file when any judge errors. The audit fails when it finds nothing to audit.

**Corollary — the discriminator is often already in the data and simply unread.** `judge.py`
recorded `{"error": ...}` for failures and `{"reason": ...}` for legitimate zeros the entire time.
Nothing consumed the distinction. The fix was ten lines, not a redesign.

## 2. Audit at the episode level; aggregates are where failures stop looking like failures

Both major defects were invisible at every level of aggregation and were found only by reading
individual episodes. That is not a coincidence — **aggregation is precisely the operation that
converts an anomaly into a plausible number.** A 0.000 among 74 real scores moves a mean slightly.
A leaked cohort in 45 of 126 episodes shifts a rate.

The corollary is uncomfortable: a report that looks reasonable is weak evidence that the data
beneath it is. Reports are for communicating findings, not for finding faults.

## 3. Scope an audit to where you do *not* expect the problem

The first pass at the failed-gate audit scanned only `g3*`, because the fooling metric lives there.
It found 12. Scanning every arm found **78**, including an entire 75-episode run whose
`mechanism_grounding` had been zeroed — a different defect that the narrow scope would never have
surfaced.

**Scoping an audit to where you expect the problem is how you miss its extent.**

## 4. A gate must be tested in both directions, against real data

`audit_blinding.py` was wrong **three times**, and every time in the same direction — rejecting good
data:

1. It flagged G0's cohort disclosure, which is that arm's *definition*. Unpassable by construction.
2. It flagged the opaque `_work/<uuid>` path the blinding fix creates. Unpassable after the fix.
3. It flagged the agent's own `=== CONFIRMING OVARIAN CANCER IDENTITY ===` echoed back through a
   tool result. That is the behaviour being measured.

All three were found by running it against real episodes, not by reasoning about it. **A detector
that has never fired proves nothing; a detector that fires on everything is equally useless.** Test
against known-bad data (it must fail) *and* known-good data (it must pass). We now do both on every
change.

This is also the argument for the smoke test: **$12 caught three false-positive modes and a real
harness bug**, any of which would have cost days inside a $1,470 production run.

## 5. Distinguish who authored the text

The audit's hardest bug came from treating `tool_result` as harness output. It is mostly **stdout
from the agent's own code coming back**. An agent printing "this looks like ovarian" has *derived*
something; flagging it makes derivation indistinguishable from leakage — the exact confusion the
audit exists to prevent.

**Split by author, not by channel.** Cohort names are checked in harness-authored text only. Harness
*state* the agent cannot invent — an episode label, an identity-bearing path, the word `mislead` —
is checked everywhere.

## 6. Some disclosure is the design, not a defect

G0 tells the agent the cohort. G3 tells it a *false* one. A gate that flags those conflates *"the
manipulation worked"* with *"the blinding failed"* and can never pass. **Gates must know the
experimental design.** What must never leak, in any arm, is the plumbing.

## 7. Score the neutral axis neutrally

The instrument has two axes and they are not interchangeable:

- **strategy** — derived / mixed / recalled. **Scored neutrally.** Efficient recall is legitimate
  science; a pathologist recognising a tumour is not failing.
- **support** — grounded / unsupported / anchored. **This carries the failure.**

12 of 14 recalled blinded episodes were *grounded* — the agent recalled the cohort **and had
computed evidence for it**. Building the analysis on the strategy axis alone would have produced
the claim "agents recall instead of discovering", which the data refutes. The defensible claim is
narrower and stronger: **unwarranted recall is the failure mode, and correctness cannot see it.**

## 8. A judge must not be told the answer it is grading

The process judge was shown `COHORT: OV` and asked how the agent established identity. That lets it
grade *correctness* instead of *process* — and on the mislead arm it makes the headline result
partly **circular**: told the truth, the judge reads an agent concluding "BRCA", knows that is
wrong, and can label it `recalled-prior` *because* it is wrong. The result then reports
"recalled → more fooled" when "recalled" was assigned partly because the agent was fooled.

**Withhold from the judge everything it is not evaluating**, including the arm — `mode='G3A'`
announces that a false label was planted. Rejoin metadata at analysis time, where you know it and
the judge did not.

## 9. Match the machinery to the sample size

At ~21 episodes per arm, hierarchical models with random effects for 2–3-level factors are not
estimable and imply precision the design lacks. We replaced them with effect sizes, confidence
intervals, and **structure shown per stratum rather than modelled away**, with a rule fixed in
advance: *a pooled estimate whose strata disagree is reported as heterogeneous, not as a headline.*

**But do not simplify away a test that a claim you are making requires** — and note the escape
hatch in that sentence. We wanted "outcome is equivalent across arms", which a non-significant
difference cannot establish, so we kept an equivalence test to license it.

The better move was available and we missed it for two rounds: **drop the claim instead.** Report
the largest pairwise difference against observed episode-level variation, put it beside the process
change, and let the juxtaposition do the work. No equivalence assertion, no equivalence test, and
nothing lost — because the design could never have supported "equivalent across scientific tasks"
anyway.

So the rule has two halves: never remove a test that a claim you are keeping depends on; and before
adding statistical machinery to license a claim, check whether the claim itself is one the design
can carry. (See §14.)

## 10. Preregistration converts exploration into method

The pilot was genuinely exploratory: constructs changed mid-flight, many analyses were tried, one
finding was retracted. That history is legitimate — and unregistered, it reads as *"they kept
looking until something worked."*

Freezing predictions before the confirmatory data exists changes the reading of the same history to
*"an exploratory campaign exposed a defect; hypotheses were frozen; the confirmatory experiment
followed."* **Amend freely before the run and log every amendment; amend nothing after.**

Register the *interpretation* of each plausible outcome, but do not claim every outcome is a
finding — some are failures you have committed in advance to reporting as failures.

## 11. Contamination can be a condition rather than a write-off

Our blinding leak handed agents an identity shortcut. That makes the pilot the **shortcut-available
condition** of a two-condition experiment whose other half is the clean rerun — and the
manipulation is exactly what the paper studies.

**But state the limits.** The pilot cannot give clean absolute provenance rates. And treating
pilot-vs-rerun as a paired comparison is only defensible if the blinding fix is the *sole*
difference, which it is not — we also repaired 78 scores, added a scorer guard, and changed G3
seeds. It is **quasi-experimental**, and calling it controlled would invite a correct objection.

## 12. Stand on the claim that does not depend on your data

The conceptual claim — *correctness cannot certify that a conclusion came from the evidence* — needs
no run at all. Every empirical result here is provisional until the clean rerun; that one is not.

When a project's empirical spine is fragile, identify the part of the argument that survives any
outcome and build the paper's frame on it. **Then the data determines how strong the paper is, not
whether there is one.**

## 13. Record what the data killed

Reporting nulls and retractions is cheap and buys disproportionate trust:

- **[RETRACTED]** "Flash collapses under lean" — an artifact of a failed API call.
- **[NOT SUPPORTED]** "blinded agents recognise rather than derive" — 52% data-derived, 94% grounded.
- **[NULL]** recall tracks literature volume — flat 44–61% across cohorts.

Each was an idea we held. Marking them explicitly, in the documents where someone would otherwise
resurrect them, is worth more than the space it costs. **Evidence tags travel with claims**
(SOLID / WEAK / NULL / RETRACTED) so that strength survives the trip between documents.

## 14. Do not overinterpret your own benchmark

**The reflexive one, and the strongest argument for restraint here.** A paper whose thesis is *"do
not overinterpret benchmark numbers"* is held to that standard first. Aggressively restrained
statistics are not a weakness of such a paper — they are the thesis applied to itself.

Concretely, for a design with 3 models, 7 cohorts, **2 mislead pairs** and correlated episodes:

- **Report an evidence hierarchy**, with formal tests last: construct demonstration → controlled
  contrasts → replication across models/prompts/cohorts/judges → effect sizes with uncertainty →
  tests as supporting diagnostics.
- **Replication beats significance.** The same direction across most models, prompts and cohorts is
  stronger evidence than a small p-value on pooled correlated episodes.
- **Pseudoreplication is the real risk, not low power.** Bootstrap over *cohorts*, not episodes —
  7 cohorts are not 126 independent draws.
- **Drop a claim rather than reach for a test to license it.** We wanted "outcome is equivalent
  across arms" and kept an equivalence test to justify it. Better: do not claim equivalence. Report
  the difference against observed variation and let it stand beside the process change.
- **Name the ceiling you cannot raise.** G3 has 2 mislead pairs. More seeds narrow intervals but
  create no new independent units. Say so rather than letting seed count imply more evidence than
  exists.
- **Fix the language in advance**, because wording is where overinterpretation enters — "associated
  with", not "predicts"; "a pattern to test", not "an effect".

## 15. Motivate broadly, claim narrowly

The general framing — outcome metrics cannot identify whether a conclusion is grounded — is what
makes the work matter beyond genomics. The evidence is seven TCGA cohorts of one task family.

Lead with the general problem; claim only what the evidence carries. **Do not let the framing write
cheques the evidence cannot cash.**

---

## The shortest version

> Failures render as benign values. Aggregates hide them. Gates need testing in both directions.
> Judges must not see the answer. Machinery should match sample size, and a paper warning against
> overinterpreting benchmarks must not overinterpret its own. Freeze predictions before the data.
> Build the argument on the part that does not depend on the run.
