# BioDiscoveryGym — Data Setup

Complete setup for both benchmarks (Task B: target discovery + Task A: cohort analysis).

---

## Prerequisites

```bash
conda env create -f environment.yaml
conda activate biodiscoverygym
pip install -e .
export ANTHROPIC_API_KEY="sk-..."
```

---

## Option A: One-command setup

```bash
bash scripts/download_all.sh
```

This downloads everything (~50 GB total) and builds all caches. Safe to re-run — skips completed steps.

For target discovery only (no anomaly-benchmark extras):
```bash
bash scripts/download_all.sh --target-discovery-only
```

To skip the large TCGA raw downloads (e.g., if you already have parquets):
```bash
bash scripts/download_all.sh --skip-tcga
```

---

## Option B: Manual step-by-step

### 1. DepMap 23Q4 (~4 GB)
```bash
python scripts/download_depmap.py
```
Downloads: CRISPR gene effect, RNA expression, mutation matrix, CNV, cell line metadata.

### 2. PRISM drug screen (~800 MB)
```bash
python scripts/download_prism.py
```

### 3. GTEx normal tissue (~75 MB)
```bash
python scripts/download_gtex.py
```

### 4. gnomAD gene constraint (~10 MB)
```bash
python scripts/download_gnomad.py
```

### 5. Human Protein Atlas — normal tissue (~30 MB)
```bash
python scripts/download_hpa.py
```

### 5b. CCLE proteomics — mass-spec protein abundance (~31 MB)
```bash
python scripts/download_ccle_proteomics.py
```
378 cancer cell lines × 12,196 proteins (Nusinow et al. 2020). Complements RNA expression — lets the agent check if a gene's protein is actually present.

### 6. TCGA expression + clinical (~25 GB raw, ~2 GB parquet)

Download raw files from GDC:
```bash
# Target discovery cohorts (10):
python scripts/download_tcga.py --cohorts BRCA COAD HNSC KIRC LIHC LUAD LUSC OV PRAD SKCM

# Anomaly detection adds UCEC:
python scripts/download_tcga.py --cohorts UCEC
```

Build expression.parquet caches (required before running benchmarks):
```bash
python scripts/process_tcga.py                  # all target-discovery cohorts
python scripts/process_tcga.py --cohorts UCEC   # cohort analysis (Task A)
```

### 7. TCGA somatic mutations (~200 MB)
```bash
python scripts/download_mutations.py --cohorts BRCA COAD HNSC KIRC LIHC LUAD LUSC OV PRAD SKCM UCEC
```

### 8. (Anomaly detection only) Additional data
```bash
python scripts/download_gdsc.py
python scripts/download_rppa.py   --cohorts BRCA PRAD UCEC LUAD LIHC LUSC OV
python scripts/download_subtypes.py
python scripts/download_genesets.py
python scripts/download_cancer_genes.py
```

### 13. PrimeKG knowledge graph (~50 MB, optional)
```bash
python scripts/download_primekg.py
```

Downloads from Harvard Dataverse (doi:10.7910/DVN/IXA7BM) and splits into four parquets:

| File | Edges | Content |
|------|------:|---------|
| `data/networks/primekg_gene_gene.parquet` | ~642k | Protein-protein interactions |
| `data/networks/primekg_gene_drug.parquet` | ~24k | Drug-gene targets |
| `data/networks/primekg_gene_disease.parquet` | ~95k | Gene-disease associations |
| `data/networks/primekg_gene_pathway.parquet` | ~84k | Pathway membership |

Used by the `--primekg` agent flag for Prize-Collecting Steiner Tree analysis and path-finding. Pass `--skip-download /path/to/kg.csv` to use a locally cached `kg.csv`.

### 14. OpenTargets actionability (~5 MB, optional)
```bash
python scripts/download_opentargets.py
```

Queries the OpenTargets Platform GraphQL API (no auth required) for ~1,200 OncoKB cancer genes. Takes ~5 minutes.

| File | Rows | Content |
|------|-----:|---------|
| `data/opentargets/ot_tractability.parquet` | ~32k | SM/AB/PROTAC tractability buckets per gene |
| `data/opentargets/ot_known_drugs.parquet` | ~46k | Approved/clinical drugs × disease per gene |

Automatically revealed to the agent at Stage 5 (alongside the gene codebook) when the files exist. No flag required.

---

## Verify setup

```bash
# Check data sizes
du -sh data/*/

# Smoke test — loads all target discovery datasets
python -c "
from biodiscoverygym.executor_target import TargetDiscoveryExecutor
e = TargetDiscoveryExecutor()
ns = e.namespace
for k in ['depmap_crispr','depmap_expr','gtex_median','gnomad','hpa_normal',
          'tcga_expr','tcga_mut','prism_viability']:
    df = ns.get(k)
    print(f'  {k:20s}: {df.shape if df is not None else \"NOT FOUND\"}')
print(f'  gene_map entries : {len(e.gene_map):,}')
"
```

Expected output:
```
  depmap_crispr       : (1100, 18443)
  depmap_expr         : (1479, 19193)
  gtex_median         : (56200, 54)
  gnomad              : (19704, 5)
  hpa_normal          : (11167, 265)
  tcga_expr           : (3409, 19938)   # grows with more cohorts
  tcga_mut            : (1260, 8469)    # grows with more cohorts
  prism_viability     : (489, 13008)
  gene_map entries    : 72,505
```

---

## Data summary

| Dataset | Source | Path | Used by |
|---------|--------|------|---------|
| DepMap CRISPR | figshare 23Q4 | `data/depmap/CRISPRGeneEffect.csv` | target discovery |
| DepMap RNA | figshare 23Q4 | `data/depmap/OmicsExpressionProteinCodingGenesTPMLogp1.csv` | target discovery |
| DepMap metadata | figshare 23Q4 | `data/depmap/Model.csv` | target discovery |
| GTEx v8 | Google Storage | `data/gtex/gene_median_tpm.parquet` | target discovery |
| gnomAD v2.1.1 | Google Storage | `data/gnomad/gnomad.v2.1.1.lof_metrics.by_gene.tsv` | target discovery |
| HPA normal tissue | proteinatlas.org | `data/hpa/normal_tissue.tsv` | target discovery |
| TCGA expression | GDC API | `data/tcga/{cohort}/expression.parquet` | both |
| TCGA mutations | GDC API | `data/tcga/{cohort}/mutations.parquet` | both |
| PRISM secondary | figshare | `data/prism/secondary-screen-replicate-collapsed-logfold-change.csv` | target discovery |
| CCLE proteomics | Gygi lab / Broad | `data/ccle_proteomics/protein_quant_current_normalized.csv.gz` | target discovery |
| COSMIC CGC | COSMIC v99 | `data/cosmic/cancer_gene_census.parquet` | target discovery |
| COSMIC Hallmarks | COSMIC v99 | `data/cosmic/cancer_hallmarks.parquet` | target discovery |
| COSMIC Fusions | COSMIC v99 | `data/cosmic/fusion_genes.parquet` | target discovery |
| COSMIC Resistance | COSMIC v99 | `data/cosmic/resistance_mutations.parquet` | target discovery |
| COSMIC Mut Freq | COSMIC v99 | `data/cosmic/mutation_freq.parquet` | target discovery |
| MSigDB Hallmarks | MSigDB v2023.2 | `data/genesets/h.all.v2023.2.Hs.symbols.gmt` | target discovery (Phase 3) |
| MSigDB KEGG | MSigDB v2023.2 | `data/genesets/c2.cp.kegg_medicus.v2023.2.Hs.symbols.gmt` | target discovery (Phase 3) |
| MSigDB Reactome | MSigDB v2023.2 | `data/genesets/c2.cp.reactome.v2023.2.Hs.symbols.gmt` | target discovery (Phase 3) |
| STRING PPI | STRING v11 | `data/genesets/human_ppi_high_conf.tsv` | cohort analysis (Stage 5) |
| OncoKB genes | OncoKB | `data/cancer_genes/oncokb_cancer_gene_list.tsv` | cohort analysis (Stage 5) |
| GDSC | EMBL-EBI | `data/gdsc/` | cohort analysis (Task A) |
| TCGA RPPA | UCSC Xena | `data/tcga/{cohort}/rppa.parquet` | cohort analysis (Task A) |
| PrimeKG gene-gene | Harvard Dataverse | `data/networks/primekg_gene_gene.parquet` | mechanistic reasoning (--primekg) |
| PrimeKG gene-drug | Harvard Dataverse | `data/networks/primekg_gene_drug.parquet` | mechanistic reasoning (--primekg) |
| PrimeKG gene-disease | Harvard Dataverse | `data/networks/primekg_gene_disease.parquet` | mechanistic reasoning (--primekg) |
| PrimeKG gene-pathway | Harvard Dataverse | `data/networks/primekg_gene_pathway.parquet` | mechanistic reasoning (--primekg) |
| OpenTargets tractability | OpenTargets API | `data/opentargets/ot_tractability.parquet` | actionability (Stage 5) |
| OpenTargets known drugs | OpenTargets API | `data/opentargets/ot_known_drugs.parquet` | actionability (Stage 5) |

---

## Run benchmarks

### Task A — cohort analysis

```bash
# G2 — data-driven (default)
python scripts/run_episode.py --cohort BRCA --seed 42 --save-log results/ep.json

# G2 + PrimeKG (PCST + path-finding)
python scripts/run_episode.py --cohort BRCA --seed 42 --primekg --save-log results/ep.json

# G0 — explicit retrieval ceiling
python scripts/run_episode.py --cohort BRCA --explicit-retrieval --seed 42

# G1 — implicit retrieval (real gene names from call 0)
python scripts/run_episode.py --cohort BRCA --gene-codebook-gate 0 --seed 42

# mislead (wrong barcodes injected)
python scripts/run_episode.py --cohort OV --mislead-cohort BRCA --seed 42

# Score a single episode (v3: scores + trace)
python scripts/score_episode_v3.py results/{id}/episode.json --save

# Multi-seed cohort benchmark (G0 × 3 seeds + G1 × 5 seeds + G2 × 5 seeds = 13 runs)
bash scripts/run_cohort.sh --tag run6_canonical --cohort OS

# Score all episodes in a results folder
bash scripts/score_all_withMeth.sh results/external/run6_canonical/
```

### Task B — target discovery

```bash
python scripts/run_target_discovery.py --save-log results/td.json
python scripts/run_target_discovery.py --indication "Acute Myeloid Leukemia" --phase2 --phase3 --save-log results/aml.json
```

### Tests

```bash
pytest tests/ -v
```
