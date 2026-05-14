# BioDiscoveryGym Implementation Plan v1

> Supersedes `IMPLEMENTATION_PLAN_v0.md`.
> v0 covered overall architecture and phases. v1 focuses on what changed during Phase 0 execution
> and what needs to happen next, with explicit notes on simplifications made for now vs. full design.

---

## What Changed from v0

### Episode Groups: Simplified for Now

**v0 plan:** use rich paper-derived labels (PAM50 subtypes, HPV status, MSI, BRAF) for TCGA episodes.

**What we actually did:** used `primary_diagnosis` from GDC clinical API, filtered to top-2 classes.
This gives clean binary splits without needing supplementary data downloads.

| Cohort | Current hidden context (v1) | Intended full context (future) |
|--------|-----------------------------|-------------------------------|
| BRCA | Ductal vs Lobular (GDC diagnosis) | PAM50 subtypes (5 classes) from TCGA paper |
| UCEC | Endometrioid vs Serous (GDC diagnosis) | MSI-H / MSS / POLE from TCGA paper |
| PRAD | Adenocarcinoma vs Acinar cell (GDC diagnosis) | Gleason grade group from supplementary |
| LUAD | Adenocarcinoma vs Mixed subtypes (GDC diagnosis) | KRAS/EGFR mutation status from cBioPortal |
| HNSC | *(not sealed yet — GDC diagnosis too imbalanced)* | HPV status from TCGA paper |
| COAD | *(not sealed yet — GDC diagnosis useless)* | MSI status from TCGA paper |
| SKCM | *(not sealed yet — GDC diagnosis too imbalanced)* | BRAF mutation from cBioPortal |
| KIRC | *(not sealed yet — all one diagnosis type)* | Stage / grade from supplementary |
| LIHC | *(not sealed yet — all one diagnosis type)* | HBV/HCV status from TCGA paper |
| LUSC | *(not sealed yet — second class is Not Reported)* | Histology subtype from supplementary |

**Why binary is fine for now:** rare classes have <30 samples — not enough signal for an agent to find.
Full multi-class episodes require downloading TCGA paper supplementary annotations from cBioPortal
or paper supplementary tables. This is a Phase 1 data task.

### Label Anonymization

Labels are now anonymized to `Context_A` / `Context_B` before writing to disk.
A `label_mapping.json` (evaluator-only) records what each context actually means.
`_ALWAYS_STRIP` in `DataAnonymizer` extended with TCGA clinical columns:
`primary_diagnosis`, `tumor_stage`, `morphology`, `site_of_resection_or_biopsy`,
`tissue_or_organ_of_origin`.

### Package Installation

`biodiscoverygym` must be installed before any script that imports it:
```bash
pip install -e ".[llm,bio,dev]"
```
This was missing from the original setup instructions and caused the step 5 failure.

### Sealed Slice Per-Cohort Layout

Each cohort gets its own subdirectory under `data/sealed/`:
```
data/sealed/
├── brca/
│   ├── public_labels.json     # 80% — Context_A/B labels, used for scoring
│   ├── sealed_labels.json     # 20% — locked, evaluator only
│   └── label_mapping.json     # Context_A → "Infiltrating duct carcinoma, NOS"
├── prad/
├── ucec/
└── luad/
```

---

## Phase 0 Status: Data Downloads

| Step | Script | Status |
|------|--------|--------|
| DepMap 23Q4 | `download_depmap.py` | ✅ Done (1.7 GB) |
| PRISM | `download_prism.py` | ✅ Done (91 MB) |
| GDSC | `download_gdsc.py` | ✅ Done (49 MB) |
| TCGA (10 cohorts) | `download_tcga.py` | ✅ Done (5.6 GB) |
| Sealed slices (4 cohorts) | `build_sealed_slice.py` | ✅ Done (BRCA, PRAD, UCEC, LUAD) |
| MSigDB + STRING DB | `download_genesets.py` | ⏳ Next |
| GTEx v8 | `download_gtex.py` | ⏳ Next |
| OncoKB + DGIdb | `download_cancer_genes.py` | ⏳ Next |

---

## Phase 0 Remaining: Full Episode Labels (Future Data Task)

To unlock all 10 cohorts and multi-class episodes, download paper-derived annotations:

**Source: cBioPortal API** (freely scriptable, no registration)
- BRCA: PAM50 subtypes (`SUBTYPE` field in BRCA TCGA PanCan study)
- LUAD: EGFR / KRAS / ALK mutation status
- SKCM: BRAF V600E mutation status
- COAD: MSI status (MSI-H / MSS)
- HNSC: HPV status (positive / negative)

**Source: TCGA paper supplementary tables** (manual download or GDC annotation endpoint)
- UCEC: POLE / MSI-H / MSS / CN-low / CN-high (TCGA 2013 Nature)
- PRAD: Gleason grade groups
- KIRC: Stage (I/II vs III/IV)
- LIHC: HBV/HCV infection status
- LUSC: Histological subtype

Script to write: `scripts/download_tcga_annotations.py` — pulls from cBioPortal for the 5
scriptable cohorts; documents the manual steps for the rest.

---

## Phase 1: Core Benchmark (Not Started)

See v0 for full task list. Priority order unchanged:

1. `DataLoader.load_tcga()` — extract TPM from batch tarballs, build expression matrix
2. Action implementations in `env.py` (`_run_association`, `_run_feature_selection`, etc.)
3. Stage scoring (0–6) in `biodiscoverygym/scoring/`
4. `pytest tests/test_m0_milestone.py -v` — M0 gate

**Note:** `load_tcga()` is a prerequisite for everything. The 10 cohorts of expression tarballs
are downloaded but not yet extracted into agent-readable matrices. This is the first Phase 1 task.

---

## How to Resume

```bash
cd /Users/lpu/myprojects/BioDiscovery
conda activate biodiscoverygym

# Finish Phase 0 downloads:
bash scripts/download_all.sh   # resumes from step 6 (genesets), skips completed steps

# Validate M0 (synthetic data, no TCGA loading needed yet):
pytest tests/test_m0_milestone.py -v

# Next real task: implement DataLoader.load_tcga()
```

---

*Last updated: 2026-05-04*
