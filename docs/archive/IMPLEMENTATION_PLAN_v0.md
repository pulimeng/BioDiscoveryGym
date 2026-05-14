# BioDiscoveryGym Implementation Plan

## Overview

| Phase | Goal | Duration |
|-------|------|----------|
| Phase 0 | Data Engineering + Environment Setup | 2-3 weeks |
| Phase 1 | Core Benchmark Implementation (MVP) | 4-5 weeks |
| Phase 2 | Evaluation Pipeline + Baselines | 3-4 weeks |
| Phase 3 | Validation, Documentation, Release | 3-4 weeks |

**Total: 12-16 weeks**

---

## Phase 0: Data Engineering & Infrastructure (2-3 weeks)

### 0.1 Dataset Preparation

| Task | Output | Owner |
|------|--------|-------|
| Download DepMap/CCLE (expression, mutation, CNV, CRISPR) | Local parquet/csv | Data Engineer |
| Download PRISM drug response data | Filtered to 1-3 drugs | Data Engineer |
| Download GDSC / CTRP (validation) | Raw files | Data Engineer |
| Download TCGA (for sealed evaluation slice) | 1-2 cancer types retained | Data Engineer |

### 0.2 Hidden Context Construction

| Task | Output |
|------|--------|
| Select hidden variable (e.g., tissue type → Context_A/B, or BRCA mutation status) | Hidden label mapping |
| Construct "strong signal" (toy) and "weak signal" (hard) versions | 2-3 difficulty levels |
| Create sealed TCGA slice: randomly sample 20%, store labels separately | sealed_labels.json (encrypted) |

### 0.3 Base Environment

| Task | Output |
|------|--------|
| Set up Python environment + conda/pip dependencies | environment.yaml |
| Fix random seed framework | seeds.py |
| Base classes for Agent API | agent_interface.py |
| Evaluator class skeleton | evaluator.py |

### Milestone M0
> ✅ Can load a dataset, hide labels, and query via Agent API in single-step mode

---

## Phase 1: Core Benchmark Implementation (4-5 weeks)

### 1.1 Agent Environment (Env)

```python
class BioDiscoveryGymEnv:
    - __init__(dataset, hidden_labels, budget, timeout)
    - get_state() → current visible data summary
    - step(action) → new evidence, reward, budget update
    - get_available_actions() → list of executable actions
```

| Task | Estimated Time |
|------|----------------|
| Implement state representation (expression matrix summary, completed analyses) | 3 days |
| Implement action space (see 1.2 below) | 3 days |
| Implement budget and timeout tracking | 1 day |
| Implement transition logic (run analysis → return results) | 4 days |

### 1.2 Action Space Implementation (MVP)

| Action | Cost | Implementation |
|--------|------|----------------|
| `run_association()` | 2 | Linear regression / correlation |
| `run_feature_selection()` | 3 | LASSO / variance threshold |
| `run_pathway_enrichment()` | 5 | GSEA / overrepresentation |
| `fit_baseline_model()` | 10 | Random forest / logistic regression |
| `request_mutation_data()` | 15 | Load pre-prepared mutation matrix |
| `request_CNV_data()` | 15 | Load CNV matrix |
| `request_external_validation()` | 25 | Evaluate current model on validation set |

> 💡 MVP can implement only the first 3-4 actions

### 1.3 Stage Scoring Implementation

Implement scoring functions for Stages 0-6.

#### Stage 4 Scoring (Priority)

```python
def score_stage_4(submission, hidden_test_data, context_labels):
    score = 0
    
    # 4.1 Evidential Support
    if compute_auroc(submission, hidden_test_data) >= 0.7: score += 2
    if beats_random_baseline(submission, hidden_test_data): score += 1
    if effect_size(submission, hidden_test_data) >= 0.5: score += 1
    if fdr_corrected_pvalue(submission) < 0.05: score += 1
    
    # 4.2 Pathway Coherence
    genes = extract_genes(submission)
    enrichments = run_msigdb(genes)
    if top_pathway_is_relevant(enrichments): score += 1
    if enrichments.fdr_min < 0.01: score += 1
    if semantic_similarity(submission.mechanism, enrichments.top) >= 0.6: score += 1
    
    # 4.3 Context Specificity
    if submission.has_context_statement(): score += 1
    if interaction_p_value(submission, hidden_test_data, context_labels) < 0.05: score += 1
    if holds_on_unseen_context(submission): score += 1
    
    # 4.4 Testability
    score += sum([
        has_model_system(submission.next_experiment),
        has_perturbation(submission.next_experiment),
        has_measurement(submission.next_experiment),
        has_quantitative_prediction(submission.next_experiment)
    ]) * 0.5
    
    return min(15, score)
```

### 1.4 Complete Stage Scoring Implementation

| Stage | Complexity | Key Dependencies |
|-------|------------|------------------|
| 0 (Data Orientation) | Low | Rules + simple checks |
| 1 (Signal Discovery) | Medium | Predictive model evaluation |
| 2 (Context Inference) | Medium | ARI/NMI computation |
| 3 (Planning) | Medium | Action sequence analysis |
| 4 (Mechanism) | **High** | See above |
| 5 (Hidden Validation) | Medium | External dataset loading |
| 6 (Report) | Low | Template checks + reproducibility |

### Milestone M1
> ✅ Can run a full episode (Agent submits discovery package) and obtain Stage 0-6 scores

---

## Phase 2: Evaluation Pipeline & Baselines (3-4 weeks)

### 2.1 Implement Baseline Agents

| Baseline | Implementation | Expected Score (estimate) |
|----------|----------------|---------------------------|
| Random | Random actions, random discovery | Very low (~5%) |
| Greedy | Always association → enrichment → fit_model | Low-medium (~20%) |
| Fixed ML pipeline | Fixed script, no decisions | Medium (~30-40%) |
| Frontier LLM (Claude/GPT-4) | LLM decides actions, generates discovery | Medium-high (target 50-60%) |

### 2.2 Run Evaluation Pipeline

```python
results = {}
for agent in [RandomAgent, GreedyAgent, MLPipelineAgent, LLMAgent]:
    for seed in range(5):
        for episode in episodes:
            score = run_episode(agent, episode)
            results[agent].append(score)
```

### 2.3 Implement Leakage Probes

| Probe | Implementation |
|-------|----------------|
| Gene-name scrambling | Shuffle gene names randomly, re-run agent, compute delta |
| Dataset identification | Ask agent to output dataset name in Stage 0; accuracy > 50% indicates leakage |

### 2.4 Implement Negative Controls

| Control | Implementation |
|---------|----------------|
| No hidden structure | Randomly shuffle hidden labels, observe FDR |
| Spurious correlation | Inject spurious correlated features, test if agent is fooled |

### Milestone M2
> ✅ Table of results for all baselines across 5 seeds + leakage probes + negative control reports

---

## Phase 3: Validation, Documentation, Release (3-4 weeks)

### 3.1 Validation

| Task | Acceptance Criteria |
|------|---------------------|
| Cross-seed stability | Variance across seeds for same agent < 5% |
| Difficulty discrimination | Random < Greedy < ML pipeline < LLM |
| Leakage test | No significant difference between baseline and scrambled versions |
| Negative controls | No high scores from agents when no hidden structure exists (FDR < 10%) |

### 3.2 Documentation

| Document | Content |
|----------|---------|
| `README.md` | Quick start, installation, usage |
| `benchmark_specification.md` | Complete Stage 0-6 definitions, scoring formulas |
| `agent_guide.md` | How to write an Agent |
| `evaluation_protocol.md` | Scoring standards, seeds, pinned environment |
| `FAQ.md` | Common questions |
| `CONTRIBUTING.md` | How to contribute new datasets or actions |

### 3.3 Release

| Task | Platform |
|------|----------|
| Code repository | GitHub (public, MIT/Apache) |
| Dataset download | Zenodo / HuggingFace Datasets |
| Documentation site | GitHub Pages or ReadTheDocs |
| Leaderboard | Simple HTML page + submission form (Google Form + automated validation) |
| Preprint | arXiv / bioRxiv |

### Milestone M3
> ✅ Website live, first public leaderboard published (4 baselines)

---

## Team Roles (Minimum 2-3 people)

| Role | Responsibilities | Time |
|------|----------------|------|
| Data Engineer | Data processing, hidden labeling, sealed slice | 20% |
| Backend/ML Engineer | Env, scoring implementation, evaluation pipeline | 50% |
| Research Scientist | Validation, leakage probes, paper writing | 30% |

---

## Risks & Mitigations

| Risk | Probability | Impact | Mitigation |
|------|-------------|--------|------------|
| Stage 4 semantic similarity unstable | Medium | High | Fix model version; use knowledge graph as primary signal |
| Dataset signal too strong / too weak | Medium | Medium | Release multiple difficulty versions |
| Sealed TCGA slice accidentally leaked | Low | High | Encrypted storage; automatic decryption only on submission server |
| LLM Agent cost too high | High | Low | Limit tokens; cache results; use cheaper models (Claude Haiku) |
| Leaderboard over-optimization | Medium | Medium | Require code submission + fixed seeds; periodic re-evaluation |

---

## Suggested First Week Actions

**Day 1-2:** Download DepMap + PRISM, confirm data loads correctly

**Day 3-4:** Design first hidden context (simplest: two tissue types)

**Day 5:** Implement Agent API skeleton + a dummy agent

> Complete this week, and you will have validated the core MVP path.

---

## Appendix: File Structure

Just for reference.

```
biodiscoverygym/
├── README.md
├── IMPLEMENTATION_PLAN.md
├── environment.yaml
├── setup.py
├── biodiscoverygym/
│   ├── __init__.py
│   ├── env.py
│   ├── evaluator.py
│   ├── scoring/
│   │   ├── __init__.py
│   │   ├── stage0.py
│   │   ├── stage1.py
│   │   ├── stage2.py
│   │   ├── stage3.py
│   │   ├── stage4.py
│   │   ├── stage5.py
│   │   └── stage6.py
│   ├── actions/
│   │   ├── __init__.py
│   │   ├── association.py
│   │   ├── feature_selection.py
│   │   ├── pathway_enrichment.py
│   │   └── model_fitting.py
│   └── utils/
│       ├── data_loader.py
│       ├── metrics.py
│       └── semantic.py
├── agents/
│   ├── random_agent.py
│   ├── greedy_agent.py
│   ├── ml_pipeline_agent.py
│   └── llm_agent.py
├── baselines/
│   └── run_baselines.py
├── tests/
│   ├── test_env.py
│   ├── test_scoring.py
│   └── test_leakage.py
├── data/
│   ├── depmap/
│   ├── prism/
│   ├── tcga/
│   └── sealed/
└── leaderboard/
    └── index.html
```

---

## Next Steps

1. **Week 1:** Set up repository structure, download datasets
2. **Week 2:** Implement data loader + hidden context generation
3. **Week 3-5:** Implement Env + action space + Stage scoring
4. **Week 6-8:** Implement baselines + run first evaluations
5. **Week 9-11:** Validation, leakage probes, negative controls
6. **Week 12-14:** Documentation, website, leaderboard
7. **Week 15:** Submit preprint

---

## Notes

### Environment — Biomni Alignment (2026-05-04)

Reviewed [Biomni (snap-stanford)](https://github.com/snap-stanford/Biomni) environment YAMLs (`environment.yml`, `bio_env.yml`) to cross-check our dependency list.

**Key changes made to `environment.yaml`:**

| Package | Reason |
|---------|--------|
| `python=3.11` | Biomni requires ≥3.11; avoids langchain/langgraph compatibility issues |
| `numpy==2.1` | Pinned to match Biomni exactly |
| `networkx` | Pathway network analysis (Stage 4) |
| `biopython` | Gene ID/annotation utilities |
| `rdkit` | Drug structure + response analysis (PRISM/GDSC); installed via conda-forge |
| `umap-learn` | Dimensionality reduction for clustering actions |
| `scanpy` | Optional scRNA modality; no cost to include now |
| `gget` | Lightweight gene annotation lookup, no local DB needed |
| `faiss-cpu` | Fast vector similarity; pairs with sentence-transformers for Stage 4 semantic scoring |
| `langchain` + `langgraph==0.3.18` | Matches Biomni's LLM orchestration stack; needed for LLM agent baseline |

**Deliberately excluded from Biomni's stack (not our modality):**

- Sequencing aligners: `blast`, `samtools`, `bowtie2`, `bwa`, `fastqc`, `trimmomatic`
- Single-cell specific: `scrublet`, `scvelo`, `scvi-tools`, `pyscenic`, `harmony-pytorch`
- Structural biology: `openmm`, `cryosparc-tools`
- Hi-C: `cooler`
- RNA structure: `viennarna`
- Metabolic modeling: `cobra`
- Image processing: `opencv`, `cellpose`, `scikit-image`

---

## Appendix A: Phase 0 Data Inventory

Full set of datasets downloaded during Phase 0, organized by script. All data lands in `data/` and is read-only after download.

### A.1 Primary Omics (DepMap 23Q4)

| File | Script | Size | Purpose |
|------|--------|------|---------|
| `OmicsExpressionProteinCodingGenesTPMLogp1.csv` | `download_depmap.py` | ~430 MB | Gene expression (log-TPM), samples × genes |
| `OmicsSomaticMutationsMatrixDamaging.csv` | `download_depmap.py` | ~125 MB | Binary damaging mutation matrix |
| `OmicsCNGene.csv` | `download_depmap.py` | ~765 MB | Copy-number per gene |
| `CRISPRGeneEffect.csv` | `download_depmap.py` | ~380 MB | CRISPR KO gene effect scores |
| `Model.csv` | `download_depmap.py` | ~500 KB | Cell line metadata (lineage, subtype, etc.) |

### A.2 Drug Response

| File | Script | Size | Purpose |
|------|--------|------|---------|
| `secondary-screen-replicate-collapsed-logfold-change.csv` | `download_prism.py` | ~1.2 GB | PRISM 19Q4 secondary screen LFC, cell lines × drugs |
| `secondary-screen-replicate-collapsed-treatment-info.csv` | `download_prism.py` | ~2 MB | Drug metadata |
| `secondary-screen-cell-line-info.csv` | `download_prism.py` | ~300 KB | Cell line info for PRISM |
| `GDSC1_fitted_dose_response.xlsx` | `download_gdsc.py` | ~28 MB | GDSC1 IC50 / AUC |
| `GDSC2_fitted_dose_response.xlsx` | `download_gdsc.py` | ~18 MB | GDSC2 IC50 / AUC |
| `Cell_Lines_Details.xlsx` | `download_gdsc.py` | ~400 KB | GDSC cell line annotations |
| `screened_compounds.csv` | `download_gdsc.py` | ~300 KB | GDSC drug list |

### A.3 TCGA Clinical + Expression (10 cohorts)

Cohorts: BRCA, LUAD, LUSC, COAD, PRAD, KIRC, UCEC, SKCM, LIHC, HNSC

| File | Script | Purpose |
|------|--------|---------|
| `data/tcga/{cohort}/{COHORT}_clinical.tsv` | `download_tcga.py` | Clinical metadata (diagnosis, stage, survival, demographics) |
| `data/tcga/{cohort}/expression_raw/` | `download_tcga.py` | Per-sample GDC expression tar.gz batches |
| `data/tcga/{cohort}/file_manifest.json` | `download_tcga.py` | GDC file ID manifest for reproducibility |

Cohorts selected for: tissue diversity, ≥300 cases, distinct molecular subtypes, and known binary context splits (e.g. HPV status in HNSC, BRAF in SKCM, MSI in COAD).

### A.4 Gene Sets & Pathway Databases

| File | Script | Size | Purpose |
|------|--------|------|---------|
| `data/genesets/msigdb/h.all.*.gmt` | `download_genesets.py` | ~200 KB | Hallmark gene sets (50 curated sets) |
| `data/genesets/msigdb/c2.cp.kegg_medicus.*.gmt` | `download_genesets.py` | ~1 MB | KEGG canonical pathways |
| `data/genesets/msigdb/c2.cp.reactome.*.gmt` | `download_genesets.py` | ~3 MB | Reactome canonical pathways |
| `data/genesets/msigdb/c5.go.bp.*.gmt` | `download_genesets.py` | ~6 MB | GO Biological Process gene sets |
| `data/genesets/msigdb/c5.go.mf.*.gmt` | `download_genesets.py` | ~1 MB | GO Molecular Function gene sets |
| `data/genesets/stringdb/human_ppi_high_conf.tsv` | `download_genesets.py` | ~50 MB | STRING v12 human PPI, score ≥ 700 |
| `data/genesets/stringdb/*.protein.links.v12.0.txt.gz` | `download_genesets.py` | ~700 MB | STRING raw (kept for re-filtering) |
| `data/genesets/stringdb/*.protein.info.v12.0.txt.gz` | `download_genesets.py` | ~5 MB | ENSP → gene symbol map |

### A.5 Normal Tissue Baseline

| File | Script | Size | Purpose |
|------|--------|------|---------|
| `data/gtex/gene_median_tpm.gct.gz` | `download_gtex.py` | ~50 MB | GTEx v8 raw median TPM per tissue |
| `data/gtex/gene_median_tpm.parquet` | `download_gtex.py` | ~25 MB | Parsed: genes × 54 tissues, indexed by gene symbol |

Agents use GTEx to determine whether a differentially expressed gene is tissue-normally high vs. context-specific — critical for separating signal from noise in Stage 1 scoring.

### A.6 Cancer Gene Annotations & Drug–Gene Interactions

| File | Script | Size | Purpose |
|------|--------|------|---------|
| `data/cancer_genes/oncokb_cancer_gene_list.tsv` | `download_cancer_genes.py` | ~100 KB | OncoKB curated cancer drivers (oncogene / TSG flags, actionability level) |
| `data/cancer_genes/interactions.tsv` | `download_cancer_genes.py` | ~50 MB | DGIdb drug–gene interactions (source, interaction type) |
| `data/cancer_genes/genes.tsv` | `download_cancer_genes.py` | ~500 KB | DGIdb gene categories (KINASE, TUMOR_SUPPRESSOR, etc.) |

**Note on COSMIC CGC:** COSMIC Cancer Gene Census requires account registration and is not freely scriptable. OncoKB covers an equivalent curated set of cancer drivers and is openly accessible via API.

### A.7 Comparison with Biomni Data Lake

[Biomni (snap-stanford)](https://github.com/snap-stanford/Biomni) uses a pre-downloaded ~11 GB data lake of 77 datasets. BioDiscoveryGym covers the subset relevant to the hidden-context discovery task:

| Category | Biomni | BioDiscoveryGym | Gap |
|----------|--------|-----------------|-----|
| Cancer genomics | DepMap + CRISPR | DepMap, TCGA, PRISM, GDSC | ✅ Broader drug response |
| Pathways / gene sets | MSigDB + MouseMine | MSigDB (H, C2, C5) | Mouse gene sets (not needed) |
| PPI network | Multi-source (mass spec, Y2H, etc.) | STRING v12 high-conf | Intentional: STRING covers multi-source |
| Drug–gene interactions | Broad Repurposing Hub, BindingDB | DGIdb + PRISM | ✅ Equivalent coverage |
| Cancer driver genes | — | OncoKB CGC | ✅ Added |
| Normal tissue baseline | GTEx, Human Protein Atlas | GTEx v8 | HPA not needed for bulk RNA |
| Population genomics | GWAS Catalog, ClinVar, GeneBass | — | Out of scope for v0 |
| Structural biology | BindingDB, AlphaFold | — | Out of scope |

### A.8 Download Sequence

Run scripts in this order (each is idempotent — safe to re-run):

```bash
python scripts/download_depmap.py          # ~1.7 GB
python scripts/download_prism.py           # ~1.5 GB
python scripts/download_gdsc.py            # ~50 MB
python scripts/download_tcga.py            # ~variable, 10 cohorts
python scripts/build_sealed_slice.py       # no download, processes TCGA
python scripts/download_genesets.py        # ~800 MB
python scripts/download_gtex.py            # ~75 MB
python scripts/download_cancer_genes.py    # ~50 MB
```

**Total estimated disk:** ~5–6 GB (excluding TCGA expression raw batches)

---

*Last updated: 2026-05-04*



