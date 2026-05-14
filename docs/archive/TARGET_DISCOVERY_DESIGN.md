# Target Discovery Benchmark — Design Document

**Status:** v1 implemented, not yet run  
**Last updated:** 2026-05-09  
**Related files:** `biodiscoverygym/phases/target_discovery.py`, `biodiscoverygym/executor_target.py`, `agents/claude_agent_target.py`, `scripts/run_target_discovery.py`

---

## 1. What This Benchmark Tests

BioDiscovery Benchmark Step 1 (cohort study) tests whether an LLM can discover molecular subtypes in a patient cohort without being told what to look for. Step 2 (this benchmark) asks a different question:

> Given population-scale cancer dependency and normal tissue data, can an LLM reason its way to a computationally supported therapeutic target — without being told what criteria define a good target?

The key behaviors being evaluated:
- Does the agent construct a principled, multi-step evidence chain (not just report one number)?
- Does it check cancer selectivity against other lineages AND normal tissue?
- Does it assess human tolerability (gnomAD constraint)?
- Does it explicitly state what the computational data does *not* prove?
- Does it propose a logically ordered experimental roadmap?

---

## 2. Inspiration: The IRS4 Paper Reasoning Chain

The benchmark is motivated by the IRS4 paper (Science Advances, 2024), which identified IRS4 as a therapeutic target in T-cell leukemia/lymphoma using the following logic:

```
DepMap CRISPR data
  → IRS4 shows selective dependency in T-cell lines
  → is this real? check expression vs dependency correlation
  → cancer-specific? GTEx normal tissue expression is low
  → humans survive without it? gnomAD: low constraint (pLI ~0)
  → mechanism? PI3K/AKT pathway, STRING network
  → known cancer gene? OncoKB: not a known driver
  → patient relevance? TCGA: amplified in T-cell subset
  → state gaps: functional proof unshown, no in vivo data, not drugged yet
  → propose experiments: CRISPR validation in PDX-derived lines, dTAG system, etc.
```

This is the reasoning chain the benchmark is designed to elicit — without telling the agent what it is.

---

## 3. What Is and Is Not Anonymized

### Anonymized
- **All gene symbols → `GENE_XXXXX`** across every dataset (DepMap CRISPR, DepMap expression, GTEx, gnomAD) using a consistent seed-based permutation mapping.
- The same `GENE_XXXXX` identifier refers to the same gene in all datasets. The agent can cross-reference between datasets by identifier.

### Not Anonymized
- **Cell line IDs** (`ACH-XXXXXX`) — kept. Not useful for recall.
- **Disease and lineage labels** in `depmap_meta` (`OncotreeLineage`, `OncotreePrimaryDisease`, `OncotreeSubtype`) — kept. The agent needs these to identify which cell lines represent the target indication and to reason about selectivity.
- **GTEx tissue names** — kept. The agent needs to know it's looking at "Liver" or "Brain" to reason about on-target toxicity.
- **gnomAD metric column names** (`pLI`, `oe_lof_upper`) — kept. These are analysis concepts, not gene identities.

### Rationale
The purpose of anonymization is to prevent **gene-level recall**: if the agent sees "TP53", it can immediately recall that TP53 is a tumor suppressor enriched in aggressive cancers and skip the data reasoning. With `GENE_XXXXX`, the agent must earn its conclusions from the data.

Disease labels are kept deliberately. Knowing the agent is working on "AML" does not tell it which gene is a good target — those identities are hidden. The selectivity reasoning (AML-specific vs pan-cancer vs normal) requires knowing the indication.

---

## 4. Why Pan-Cancer DepMap (Not Indication-Filtered)

The executor loads all ~1100 cell lines, not just the ones matching the indication. This is intentional.

The selectivity reasoning step requires a comparator: "this gene is essential in AML but not in other cancers." If we pre-filtered to only AML cell lines, the agent could not make that comparison — it would only see AML dependency scores with no baseline.

DepMap has ~30–50 AML cell lines, which is enough for a meaningful dependency analysis. The remaining ~1050 lines from other lineages serve as the pan-cancer comparator. The agent uses `depmap_meta` lineage labels to split them.

---

## 5. Why Not Checkpoint Inhibitors

Checkpoint inhibitor discovery was considered as an alternative task framing and rejected for v1.

| | AML target (pHTI-style) | Checkpoint inhibitor |
|---|---|---|
| Core question | Which gene do AML cells depend on for survival? | Which checkpoint molecule does the tumor use to evade immunity? |
| Key data needed | DepMap CRISPR dependency | Tumor-immune interface: checkpoint expression, immune infiltration, patient response |
| Fit with current data | DepMap + GTEx + gnomAD — correct tool | **Wrong data** — CRISPR knockout of PD-L1 doesn't kill a cancer cell line |
| Gene anonymization | Effective | Weaker — ligand-receptor pairs reveal mechanism |
| Scoring | Clear rubric | Hard to define objectively |

The fundamental mismatch: DepMap CRISPR screens measure what kills a cancer *cell line in a dish*. Checkpoint biology is about the tumor-immune interface — it requires tumor microenvironment data, immune infiltration scores, and immunotherapy response cohorts, none of which are in scope for v1.

Checkpoint inhibitor discovery is a legitimate future benchmark track but requires a separate dataset build.

---

## 6. Indication Parameter

The `--indication` argument accepts a free-form string that is inserted verbatim into the system prompt:

```bash
python scripts/run_target_discovery.py --indication "Acute Myeloid Leukemia"
python scripts/run_target_discovery.py --indication "non-small cell lung cancer"
python scripts/run_target_discovery.py  # default: "cancer" (pan-cancer mode)
```

The agent is told it is looking for targets in that indication and uses `depmap_meta` lineage/disease columns to identify which cell lines represent it.

---

## 7. Key Design Dilemma: Mutation-Stratified Indications

### The Problem
Real precision oncology targets are often mutation-stratified. "AML with FLT3-ITD mutation" and "AML without FLT3-ITD mutation" are essentially different diseases. In real drug discovery, you would filter to the FLT3-ITD subgroup and find dependencies specific to it.

### Why This Conflicts with Anonymization
If we pass `--indication "AML with FLT3-ITD mutation"`, the agent sees the gene name "FLT3" — which defeats the anonymization. It can immediately recall FLT3 inhibitor biology from training data.

Three options were considered:

| Option | Description | Problem |
|--------|-------------|---------|
| A | Pass real mutation name in indication string | Breaks gene anonymization — agent recalls FLT3 biology |
| B | Anonymize mutation: "AML with mutation in GENE_XXXXX" | Technically works but artificial; agent has to find which lines carry it |
| C | No mutation stratification — lineage-only indication | Clean, well-posed, matches IRS4 paper design |

### Decision: Defer Mutation Stratification to v2
**v1 supports lineage-only indications.** Mutation-stratified indications are a separate, harder benchmark requiring:
- Loading `OmicsSomaticMutationsMatrixDamaging.csv` into the executor (with gene anonymization applied)
- A different indication framing: "a lineage defined in part by a specific driver mutation — identify the mutation and its associated dependencies"
- A separate scoring rubric for mutation identification accuracy

This is meaningful work but complicates both implementation and scoring before the baseline task is even validated.

---

## 8. Evaluation Rubric (v1)

Five dimensions, each scored 0–2 by an LLM judge (not yet written):

| Dimension | Score 0 | Score 1 | Score 2 |
|-----------|---------|---------|---------|
| `evidence_chain` | Step(s) missing entirely | All steps present but superficial | Each step has quantitative criteria + justification |
| `cancer_selectivity` | No GTEx cross-reference | GTEx checked but qualitative | Quantitative cancer-vs-normal contrast; candidates filtered |
| `tolerability_check` | gnomAD not consulted | gnomAD values reported but unused | gnomAD used as explicit filter with stated rationale |
| `evidence_gaps` | None stated, or only vague disclaimer | Gaps named but not tied to experiments | Specific gaps + the experiment that would address each |
| `roadmap_quality` | No roadmap or only generic suggestions | Roadmap missing model/perturbation/readout spec | Ordered roadmap with fully specified experiments |

Maximum score: 10. Each dimension is independent.

### What a Score-10 Submission Looks Like
- Dependency threshold chosen and justified (e.g. CERES < −0.5 in >50% of indication lines)
- Indication-vs-other-cancer CERES contrast reported quantitatively for each candidate
- GTEx checked: candidate expressed low in relevant normal tissues
- gnomAD pLI/LOEUF checked: candidate is not under strong purifying selection
- Mechanism proposed linking cancer biology to dependency
- Evidence gaps named precisely: e.g. "CERES score proves depletion in proliferating cells, not that the mechanism is on-target — requires rescue experiment with catalytically dead construct"
- Roadmap ordered: (1) CRISPR validation in primary patient-derived AML cells → (2) dTAG or CRISPRi for dose-response → (3) interaction proteomics to confirm mechanism

---

## 9. Submit Schema

```
submit_target_discovery(
    top_candidates        : list[str]      # GENE_XXXXX identifiers, ranked, up to 5
    reasoning_chain       : str            # narrative of filtering logic at each stage
    computational_evidence: list[dict]     # per-candidate: dependency_summary,
                                           #   selectivity_evidence, tolerability_evidence,
                                           #   mechanism_notes
    evidence_gaps         : list[str]      # min 3; each must name gap + experiment
    experimental_roadmap  : list[str]      # 3–5 ordered experiments; no animal models;
                                           #   each specifies model, perturbation, readout
    mechanism_hypothesis  : str            # one sentence: why is this essential in cancer?
    confidence            : str            # "high" | "medium" | "low"
)
```

---

## 10. Data Available to Agent

| Variable | Source | Shape | Notes |
|----------|--------|-------|-------|
| `depmap_crispr` | DepMap 23Q4 CRISPRGeneEffect | 1100 × 18443 | CERES scores, genes anonymized |
| `depmap_expr` | DepMap 23Q4 OmicsExpression | 1479 × 19193 | log2(TPM+1), genes anonymized |
| `depmap_meta` | DepMap 23Q4 Model.csv | 1921 × 8 | lineage/disease kept, cell line names dropped |
| `gtex_median` | GTEx v8 | 56200 × 54 | median TPM per tissue, genes anonymized |
| `gnomad` | gnomAD v2.1.1 | genes × 6 cols | pLI, LOEUF, obs/exp_lof; genes anonymized. **Requires `download_gnomad.py` first.** |

Plus file-based access to: `data/genesets/` (MSigDB, STRING), `data/cancer_genes/` (OncoKB).

---

## 11. v1 Scope and v2 Roadmap

### v1 (implemented)
- [x] Lineage-only indications via `--indication`
- [x] Gene anonymization across DepMap + GTEx + gnomAD (seed-based, consistent across datasets)
- [x] 6-stage system prompt (no explicit criteria given)
- [x] `submit_target_discovery` schema with evidence_gaps + roadmap fields
- [x] 5-dimension scoring rubric defined
- [x] `gene_map.json` saved alongside every session log (GENE_XXXXX → real symbol, for post-hoc scoring)
- [x] gnomAD v2.1.1 downloaded (19,704 genes, 5 constraint columns)
- [x] 50 tool call default (force_submit at call 42)
- [ ] LLM judge scorer (`scripts/score_target_discovery.py`) — not yet written
- [ ] First session run

### v2 (deferred)
- Mutation-stratified indications (load mutation matrix, anonymize, framing update)
- Novelty control: same questions answered without data access (literature recall baseline)
- Stage A pre-commitment variant: agent commits to candidate list before seeing scoring criteria
- Multi-indication comparison: same session run for AML vs NSCLC vs BRCA
