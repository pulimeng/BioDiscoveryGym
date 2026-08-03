# Recommended paper outline

*Revised after reading Chen, Zhao, and Cohan (2026), "Measuring the Gap Between Human and LLM
Research Ideas." The organizational lesson borrowed here is to build the entire paper around one
measurement gap: apparently good outputs can conceal a behaviorally important difference. We borrow
the narrative architecture, not their constructs or claims.*

## Working title

**Measuring the gap between correctness and discovery in scientific agents**

More precise alternative:

**Measuring the gap between outcome quality and evidential grounding in scientific agents**

## The paper in two sentences

We vary the information disclosed to cancer-genomics agents from explicit cohort identity to
blinded molecular data. In the current path-contaminated runs, removing contextual information
changes how agents establish their conclusions while measured discovery quality changes little.
Whether this measurement gap survives genuinely blinded execution is the paper's critical pending
test.

The provisional results suggest that this hidden distinction matters when context is wrong:
episodes classified as data-derived are less likely to adopt an injected false premise, while
prescribing more statistical procedure increases susceptibility to the misleading frame. Both G3
findings require confirmation in a path-scrubbed rerun because the leaked path contains the true
cohort, false cohort, and the word `mislead`.

## Narrative spine

The paper should follow one argument from beginning to end:

1. **Apparently good performance.** Agents return similarly credible biological discoveries under
   very different information conditions.
2. **The missing measurement.** Correctness cannot reveal whether a conclusion came from the
   current data or from contextual knowledge.
3. **Controlled identification.** Hold the molecular data fixed and manipulate only the contextual
   information available to the agent.
4. **The main measurement gap.** Test whether reasoning provenance changes substantially while
   outcome quality changes little under genuinely blinded execution.
5. **Behavioral consequence.** Test whether the hidden process distinction predicts response to
   false context after removing agent-visible identity paths.
6. **The obvious remedy fails.** Test whether more procedural scaffolding adds statistical rigor
   while increasing false-premise adoption in clean G3 runs.
7. **A plausible mechanism.** Contradictory evidence is documented and then assimilated into the
   supplied frame instead of being used to reject it.
8. **A design target.** Scientific agents should separate blinded inference from contextual
   interpretation and explicitly challenge supplied premises.

In compact form:

> good-looking outcomes -> hidden provenance difference -> false context reveals the difference ->
> ordinary rigor does not fix it -> premise challenge becomes the design target

## Central claim

**Outcome quality cannot establish that scientific discovery occurred.** The same outcome can be
produced through recall, recognition, mixed reasoning, or inference from the observed data. These
routes respond differently when contextual information is wrong, but conventional correctness
metrics cannot distinguish them.

This is a measurement and construct-validity paper. Cancer-genomics subtype discovery is the
controlled experimental system, not the primary scientific contribution.

## Abstract structure

The abstract should contain exactly five moves:

1. **Apparent capability:** scientific agents increasingly produce credible analyses, but existing
   evaluations primarily score the resulting answer or analytical procedure.
2. **Question:** do those evaluations establish that the conclusion was derived from the supplied
   data?
3. **Controlled design:** hold the multi-omics task fixed while varying disclosed information from
   explicit identity to blinding and false identity.
4. **Two principal results, conditional on clean replication:** a large process shift with little
   outcome change; lower false-label adoption among data-derived episodes.
5. **Failed remedy and implication, conditional on clean replication:** detailed scaffolding
   increases rigor yet increases fooling; evaluation must measure evidential provenance and premise
   robustness.

Do not place judge reliability, sample-count recognition, cost, or the scorer failure in the
abstract unless required by space or review. They support credibility but are not the central
story.

# 1. Introduction: the score hides the capability

## 1.1 Begin with apparent success

Open generously: autonomous agents can execute substantial analyses and recover credible biology.
Prior benchmarks increasingly measure real data analysis, full trajectories, and performance
against published work. The problem is not that these evaluations are useless; it is that they
cannot establish one particular claim increasingly made about them: **discovery from data**.

Use one concrete example. An agent returns canonical breast-cancer subtypes and a mechanistic
account. The output looks identical whether reconstructed from the cohort or recalled from the
literature. A correctness metric necessarily gives both the same score.

## 1.2 State the missing empirical question

> When a scientific agent reaches a correct biological conclusion, what evidence produced it?

Recall is not inherently bad. Correct context can be efficient and useful. The measurement problem
is that outcome scores do not reveal dependence on context, and that dependence becomes operationally
important when context is incomplete or wrong.

## 1.3 Change the unit of evaluation

Take the same conceptual move as the research-idea-gap paper without copying its construct: instead
of assigning another quality score to each output, compare how outcome and process respond to a
controlled change in available information.

The key intervention is:

> same molecular data, same task, different access to contextual identity information

## 1.4 Preview the complete result

After clean replication, the introduction should reveal the full arc rather than merely promise a
benchmark:

- G0-G2: whether process changes markedly while outcome changes little;
- G3: whether the hidden process distinction predicts robustness to false context;
- prompt ablation: whether additional procedural rigor fails to repair the problem and increases
  fooling.

## 1.5 Contributions

Keep the list short:

1. A controlled information-disclosure framework for identifying dependence on contextual prior
   information.
2. A process measure of identity derivation calibrated at a known recall condition.
3. Subject to clean replication, evidence that conventional outcome scores are insensitive to a
   large process change associated with robustness under misleading context.
4. Subject to clean replication, an ablation testing whether procedural rigor and epistemic
   grounding are separable and may move in opposite directions.

# 2. Related work: what existing scores establish

This section should be organized by measurement target, not paper chronology.

## 2.1 Outcome-based scientific-agent evaluation

Cover deterministic analytical tasks, recovery of published biological findings, and performance
relative to published SOTA. BAISBench, scBench, NatureBench, and related ML benchmarks establish
useful forms of capability, correctness, and competitive performance.

Their limitation for our question is precise: a correct or competitive result does not identify the
source of the conclusion.

## 2.2 Process-level evaluation

Lead with BiomniBench and credit its contribution clearly. It already argues that correct outcomes
can arise through memorization or flawed reasoning and evaluates full trajectories using
expert-designed rubrics.

Then state our narrower distinction:

> Procedural quality asks whether the analysis was conducted competently. Evidential provenance asks
> whether the conclusion is supported by the current measurements rather than inherited from the
> surrounding frame.

Our rigor-paradox result shows that these properties can separate.

## 2.3 Contamination and information firewalls

Discuss web-search restrictions, hidden source methods, held-out answers, and public-dataset
contamination. NatureBench's information firewall is important prior art. Our contribution is not
the first attempt to hide source information; it is the controlled manipulation of contextual
information while the underlying scientific task remains fixed.

## 2.4 Human-LLM research gaps

Cite Chen, Zhao, and Cohan's research-taste-gap paper as a complementary measurement argument. It
shows that individually reasonable ideas can conceal a systematic distributional difference between
human and model ideation. Our analogous question concerns scientific conclusions: individually
correct outputs can conceal different evidential provenance.

Do not imply that our agents are being compared with human scientists; we have no human baseline.

## 2.5 Robustness to misleading context

Connect G3 to real scientific conditions: provisional diagnoses, mislabeled samples, sample swaps,
incorrect filenames, contaminated datasets, erroneous annotations, and collaborator hypotheses.
This positions false-context testing as reliability evaluation rather than a contrived adversarial
attack.

# 3. Evaluation framework for evidential provenance

This section should introduce the complete measurement framework before showing results.

## 3.1 Controlled cancer-genomics task

Agents perform subtype discovery from TCGA expression, mutation, methylation, and copy-number data.
They partition patients, characterize molecular signatures, identify the cancer, relate groups to
outcomes, and propose a mechanism through a fixed code-and-tool interface.

## 3.2 Information-disclosure ladder

Present G0-G3 as one experimental structure:

| Arm | Information supplied | Role in the proof |
|---|---|---|
| G0 | Cohort and gene identities | Known recall anchor |
| G1 | Gene identities, cohort hidden | Intermediate information condition |
| G2 | Cohort and genes initially hidden | Data-first condition |
| G3 | False cohort identity supplied | Consequential robustness test |

The independent variable is access to contextual identity information. G3 is not simply a fourth
difficulty level; it tests what happens when the contextual channel conflicts with the measurements.

## 3.3 Imperfect blinding as part of the construct

Describe opaque identifiers, stripped clinical identity fields, codebook timing, and lack of
internet access. Then state that public datasets cannot be perfectly blinded. Sample count,
molecular-frequency fingerprints, and accidental implementation channels may still reveal identity.

Separate three concepts carefully:

- **data-derived inference:** identity inferred from cohort-specific molecular evidence;
- **biological interpretation:** prior knowledge used to interpret measured markers;
- **benchmark recognition:** identity inferred from a non-biological fingerprint such as exact
  sample count or directory name.

Biological knowledge is necessary for interpretation and is not automatically recall.

## 3.4 Outcome measure

Describe the seven biological checks and the identity gate. State affirmatively what the score
measures: biological faithfulness and quality. Then state what it cannot measure: the provenance of
the reasoning that produced the answer.

## 3.5 Process measure

Define `identity_derivation`:

- data-derived;
- mixed;
- recalled-prior;
- not-established.

The judge reads the symmetric auditable trace channels rather than hidden chain-of-thought.

## 3.6 Calibration at the known extreme

G0 explicitly supplies the cohort identity and therefore anchors the recall pole. Report:

- 109/126 recalled-prior;
- 12/126 mixed;
- 2/126 data-derived;
- 3/126 unresolved.

This is an important positive control. It shows that the instrument recognizes the known recall
condition. Do not overstate it as complete validation across G2 and G3.

## 3.7 Reliability and separation of judges

Report three-pass agreement plainly. Explain that three DeepSeek passes estimate stochastic
stability, not cross-family validity. After generating clean episodes, the process judge should be
run using another family and without revealing the true or false cohort identity when classifying
provenance. Identity correctness must remain a separate judgment. Re-judging existing episodes
cannot remove information already seen by the agent and is not a substitute for a clean rerun.

## 3.8 Experimental scale

Report 3 models x 2 prompt conditions x 75 episodes = 450 episodes, seven honest cohorts, two G3
mislead pairs, and three seeds. Disclose the Gemini Flash-tier confound. Model ranking is supporting
analysis, not the central question.

# 4. Experiments

The results should resemble a progressive diagnosis: main gap, behavioral meaning, failed remedy,
then mechanism.

## 4.1 Setup and analysis plan

Specify models, prompts, cohorts, seeds, judge consensus, exclusions, and statistical analysis.
Before submission, use paired or hierarchical models accounting for repeated cohort/seed instances.

Predefine a smallest meaningful outcome difference and conduct an equivalence analysis. A
nonsignificant difference is not evidence of invariance.

## 4.2 Main measurement gap: process changes while outcome does not (provisional)

The current contaminated runs produce the following aligned figure and table:

| Arm | Mean outcome | Consensus process distribution |
|---|---:|---|
| G0 | 0.502 | 109 recalled, 12 mixed, 2 derived, 3 unresolved |
| G1 | 0.505 | 24 recalled, 32 mixed, 61 derived, 9 unresolved |
| G2 | 0.486 | 14 recalled, 43 mixed, 65 derived, 4 unresolved |

The visual should place outcome distributions immediately above or beside stacked process-label
distributions. Until the clean rerun, mark the G2 column and the entire inference as provisional.

The path leak threatens both sides of the contrast:

- it can inflate G2 `data-derived` labels when agents infer identity from the directory;
- it can improve the submitted biological interpretation, because the agent—not the outcome
  scorer—has learned the hidden cohort identity.

Therefore the current outcome flatness is not fully leak-proof. The scorer does not read the path,
but the treatment was compromised before the submission reached the scorer. A true information-
disclosure test requires neutral agent-visible paths.

Preferred claim only after clean replication, but before equivalence testing:

> Removing contextual identity information substantially changed how agents established their
> conclusions while changing measured discovery quality little.

Do not claim that agents remain in the recall regime under G2; the current labels show a strong move
away from the G0 recall pole.

### Complementary within-G2 analysis

After establishing the experimental G0-G2 result, show the observational result within G2:

- data-derived: mean 0.483, n=65;
- mixed: mean 0.478, n=43;
- recalled-prior: mean 0.524, n=14;
- derived versus recalled Mann-Whitney p=0.19;
- ordinal rho=-0.067, p=0.46.

Describe this as no detectable association, not proof that the groups are equivalent.

## 4.3 Behavioral validation: why the hidden gap matters (provisional)

G3 supplies false contextual information:

- data-derived episodes: 6/29 fooled, 21%;
- other episodes: 29/43 fooled, 67%;
- Fisher p=0.00012, odds ratio 0.13, n=72.

This is the intended criterion-validity result, but the current magnitude is not trustworthy. G3
paths expose strings such as `g3a_lusc_mislead_luad`, simultaneously revealing the true cohort, the
planted cohort, and that the condition is a mislead experiment. Agent exploitation of that path can
act as a common cause of both variables: it can produce an apparently data-derived trace and enable
resistance to the planted label.

Only a path-scrubbed G3 rerun removes this channel. The primary clean display should include model-,
prompt-, cohort-pair-, and reveal-time-stratified estimates, not only a pooled table. Blinded and
cross-family re-judging is then required to validate the process instrument, but cannot repair the
existing agent-side exposure.

Preferred interpretation only after clean replication:

> Outcome quality does not reveal dependence on context, but that dependence predicts whether the
> agent corrects or amplifies an erroneous premise.

Do not claim causal protection until the construct and confounding analyses are stronger.

## 4.4 Does procedural guidance help? (fooling result provisional)

Deliberately frame this like the research-idea paper's "Does Extended Reasoning Help?" section. Test
the intuitive remedy after establishing the main gap.

Detailed versus lean:

- mean absolute honest-outcome delta: 0.013;
- high validation rigor: 85% versus 71%;
- false-label adoption: 24/36 versus 11/36;
- omission: 48% versus 51%;
- attempted-but-failed analysis: 10% versus 6%.

The validation-rigor contrast is supported by the current traces. The false-label-adoption contrast
is provisional because G3 paths are contaminated, and prompt conditions may differ in whether the
agent notices or exploits those paths. If the fooling difference survives clean replication, the
reveal is not that the detailed prompt is useless: it produces more real statistical work, but that
work does not test the semantic premise.

Preferred claim only if the fooling contrast survives clean replication:

> Procedural scaffolding improves documented statistical rigor while increasing susceptibility to
> false contextual framing.

Use an appropriate paired or hierarchical test before presenting this as more than a directional
3/3-model result.

## 4.5 Mechanism analysis: a contradiction becomes an exception

The taxonomy establishes where behavior differs; this section asks how the failure occurs in traces.

Proposed qualitative recipe:

1. recover molecular evidence inconsistent with the supplied identity;
2. recognize and document the contradiction;
3. reinterpret the evidence as an unusual subtype or transdifferentiation event;
4. preserve the supplied identity rather than compare it against alternatives.

This is analogous in narrative role—not substance—to the idea-gap paper's integrate/unify recipe.
Use the squamous-biology/LUAD episode as the canonical case.

Report the quantitative markers honestly:

- paradox language: 29% fooled versus 7% resisted, p=0.051;
- contradiction noted but unresolved: 51% versus 29%, p=0.078;
- explicit deference: 11% versus 4%, p=0.37.

No marker reaches p<0.05. Present the mechanism as a trace-derived hypothesis supported by
directionally consistent but inconclusive evidence.

## 4.6 Recognition channels and benchmark integrity

Keep this compact in the main paper or move most of it to the appendix.

- Agents recognize public cohorts from exact sample counts.
- Molecular fingerprints can reveal identity despite opaque identifiers.
- The current implementation exposed cohort-bearing paths.
- A failed judge call once rendered as legitimate zeros and created a retracted result.

The conceptual point is that information channels are plural and benchmark failures can render as
benign values. The practical point is that episode-level audits are necessary.

The leak directly threatens provenance rates and the G3 association. It also weakens the
outcome-invariance interpretation indirectly because agent-visible identity can improve the final
submission even though the outcome scorer itself never reads the path. The current data may be shown
as motivation or a contaminated pilot, not as definitive evidence for either hero figure.

## 4.7 Cost and scalability

Report the measured generation cost and approximately 0.3% process-grading ratio briefly. This
supports feasibility but should not interrupt the main narrative.

# 5. Conclusion and discussion

Following the research-idea paper, combine conclusion and discussion so the paper ends on the
measurement target rather than a summary of every result.

## 5.1 What clean replication would establish

- Whether contextual information substantially changes reasoning while barely affecting conventional
  outcome scores under a valid manipulation.
- Whether the hidden process distinction becomes consequential when context is false.
- Whether procedural rigor and epistemic grounding remain distinct after removing the path channel.

The conceptual statement that correctness is not itself a measurement of discovery provenance does
not depend on these data. The empirical claim that our instrument exposes such a gap does.

## 5.2 Real-world relevance

The ladder is an identification experiment, not a recommendation to blind every deployed agent.
Real scientific agents receive mixtures of measured evidence and fallible context: provisional
diagnoses, study descriptions, filenames, annotations, literature, and collaborator hypotheses.

G0-G2 reveal otherwise hidden dependence on those channels. G3 shows why that dependence matters.

Practical evaluation recommendation:

> Test scientific agents under context removal and counterfactual metadata perturbation, and score
> whether measured evidence can overturn an incorrect frame.

## 5.3 Design target: blind then challenge

Introduce the proposed Evidence Firewall from `TO_BE_TESTED.md`:

1. commit to a data-derived account before contextual reveal;
2. reveal metadata and prior knowledge;
3. require explicit support, contradiction, falsification, and competing-hypothesis tests;
4. label major conclusions by evidence provenance.

This plays the same narrative role as the idea-gap paper's call for mechanism-specific,
less-template-bound ideation: the measured failure defines a concrete system-design target.

Until tested, call it a promising hypothesis, not a demonstrated solution.

## 5.4 What the paper does not establish

- Recall is not inherently illegitimate.
- Agents do not necessarily remain primarily in a recall regime under blinding.
- The study does not measure historical novelty or human-level discovery.
- It does not establish that one model family is generally more scientific.
- It does not yet establish that the Evidence Firewall improves robustness.
- It does not yet prove cross-family validity of the process labels.

## 5.5 Suggested final paragraph after clean replication

> Scientific-agent benchmarks typically ask whether an agent produced a correct or useful answer.
> Our results show that this question is insufficient: manipulating access to contextual information
> substantially changes how agents establish a biological conclusion while changing conventional
> outcome scores little. The hidden distinction becomes consequential when context is false, where
> data-derived reasoning is associated with markedly greater resistance to the injected premise.
> Evaluating autonomous discovery therefore requires measuring not only correctness and procedural
> rigor, but also evidential provenance and premise robustness.

Then end with one forward-looking sentence:

> The next design question is whether forcing agents to commit to a blinded account and explicitly
> challenge subsequent context can convert this diagnostic into a more reliable discovery workflow.

# Limitations

Keep a conventional limitations subsection at the end of Section 5 or immediately before it:

1. Current G2 and G3 runs expose cohort-bearing working paths. G3 is more severe because its path
   contains the true cohort, false cohort, and the word `mislead`. Both hero results are provisional.
2. Three judge passes use one model family and measure stochastic stability, not cross-family
   validity.
3. The process judge's access to true cohort identity may bias G3 derivation classification.
4. Sample sizes are modest and reuse cohort/seed combinations across conditions.
5. Nonsignificant outcome differences do not establish equivalence.
6. `identity_derivation` is a noisy categorical construct with moderate judge agreement.
7. The study observes auditable traces rather than hidden chain-of-thought.
8. Gemini is a Flash-tier model, limiting model-family comparisons.
9. Public datasets cannot be perfectly blinded because shapes and molecular fingerprints may be
   recognizable.

# Figure sequence

The figure order should tell the story without the prose.

## Figure 1: The controlled measurement problem

One schematic:

- same data across G0-G3;
- contextual information varied;
- outcome and process scored separately;
- G3 used as the false-context stress test.

Caption takeaway: **The ladder manipulates information provenance while holding the scientific task
fixed.**

## Figure 2: The main measurement gap

Aligned panels across G0-G2:

- outcome distributions with uncertainty;
- stacked process-label distributions.

Provisional caption takeaway: **Process changes substantially while measured outcome changes
little in path-contaminated pilot runs.** Replace with the clean result after rerunning.

This is the hero figure.

## Figure 3: Why the hidden distinction matters

False-label adoption for data-derived versus other episodes, with stratified estimates by model and
prompt.

Provisional caption takeaway: **A distinction invisible to correctness is associated with response
to false context in path-contaminated pilot runs.** This cannot become a hero claim without clean
replication.

## Figure 4: Does procedural guidance help?

Detailed versus lean for:

- outcome;
- validation rigor;
- false-label adoption;
- omission versus failed-execution weaknesses.

Conditional caption takeaway after clean replication: **More statistical rigor does not produce
premise robustness.**

## Figure 5: Mechanism and recognition evidence

Compact trace-centered panel:

- molecular contradiction;
- anomaly reinterpretation;
- final deference to the supplied label;
- sample-count recognition example.

Place the path and scorer integrity audits in the supplement unless the venue permits a substantial
methods box.

# Analyses required before freezing the narrative

1. **Fix the agent-visible path and rerun the G0-G3 evidence needed for both hero figures.** This is
   the critical path, not a sensitivity analysis.
2. Audit clean traces to verify that no filenames, working directories, tool outputs, or submission
   paths reveal arm, cohort, planted label, or `mislead` status.
3. Run the clean process judge without revealing true or misleading identities.
4. Cross-family validation of the clean process labels.
5. Equivalence analysis for clean G0-G2 outcome with a prespecified meaningful margin.
6. Paired or hierarchical modeling accounting for model, prompt, cohort, seed, and cohort pair.
7. Formal analysis of the clean detailed-versus-lean fooling difference.
8. Use exclusion of visibly path-exploiting legacy episodes only as a secondary sensitivity analysis;
   it cannot rule out unrecorded exploitation and cannot replace the rerun.
9. Blind-then-challenge experiment if time and budget permit.

# Claims discipline

## Supported now

- G0 calibrates the judge's recall pole: 109/126 episodes are consensus recalled-prior.
- Detailed scaffolding increases documented validation rigor in the current traces.
- Public-dataset blinding leaks through multiple channels, including sample count and agent-visible
  paths.
- The scoring-failure audit demonstrates that judge/API failures can silently render as legitimate
  benchmark values if error states are not separated from valid zeros.
- Process evaluation is inexpensive relative to episode generation.

## Not yet supported

- Information disclosure changes provenance under clean blinding.
- Outcome remains approximately or formally invariant across a valid G0-G2 manipulation.
- Outcome is independent of derivation class under clean blinding.
- Data-derived reasoning predicts resistance to false context after removing agent-visible labels.
- Detailed scaffolding increases false-label adoption in clean G3 episodes.
- Outcomes are formally equivalent across G0-G2.
- Agents remain primarily in a recall regime under clean blinding.
- Derivation causally prevents false-label adoption.
- The Evidence Firewall improves grounding or robustness.
- Process labels are robust across judge families.
- The textual markers establish the mechanism of fooling.

# One-paragraph version for collaborators

The current path-contaminated pilot suggests that scientific agents can produce similarly credible
cancer-genomics discoveries under different information conditions even while their measured
reasoning provenance changes. It also suggests that the hidden process difference matters under
false context and that more statistical scaffolding may increase rather than reduce false-label
adoption. Because G2 and G3 paths exposed the true identity—and G3 paths additionally exposed the
false identity and `mislead` status—these are hypotheses for a scrubbed rerun, not established
findings. If they replicate, the paper will show why scientific discovery agents must be evaluated
for evidential provenance and premise robustness, not only correctness or procedural rigor.
