# Cohort Reference Cards — literature ground truth for the support judge

**Status:** draft for review. Seven cards (BRCA / LIHC / LUAD / OV / UCEC / PRAD / LUSC), one per benchmark cohort.

## Role of these cards (read before using)

These cards are a **fact-check reference** for the support judge: curated, citable
canonical biology per cohort, so the judge does not invent or misremember the "textbook"
narrative when it assesses an agent's claims. The **caveats** record where the literature
*itself* is uncertain.

They are a reference, **not** a grading rubric. All grading logic — what counts as grounded
vs. anchored, and in particular the principle that *scoring rests on support from this
cohort's own data, not on matching the card* — lives in the judge prompt, deliberately not
here, so the criteria exist in one place and cannot drift between two documents. (The card
is canonical-by-construction, so it would bias the judge toward rewarding recall unless the
rubric states this explicitly; enforcing that is the judge prompt's job, not the card's.)

Each card lists **Objective anchors** — the claims checkable from data present in *this
benchmark* (expression genes, mutation calls, survival) versus what exists only as recall
(e.g. IHC status, smoking history, platinum response). This is factual scope, not grading:
it tells the judge what the trace *could* show.

---

## BRCA — Breast invasive carcinoma

**Canonical refs:** TCGA, *Nature* 2012 (490:61–70, "Comprehensive molecular portraits of
human breast tumours"); Parker et al., *JCO* 2009 (PAM50 intrinsic subtypes).

**Subtypes (PAM50 intrinsic):**

| Subtype | Defining markers | Character |
|---|---|---|
| **Luminal A** | ESR1, PGR, FOXA1, GATA3, XBP1, BCL2; low MKI67 | ER+/PR+, low proliferation, best prognosis; PIK3CA/MAP3K1 mut, TP53 rare |
| **Luminal B** | ESR1+ but high MKI67/cell-cycle; sometimes ERBB2+ | ER+ high-proliferation, worse than LumA; more TP53 than LumA |
| **HER2-enriched** | ERBB2 amplification/overexpression, GRB7; ER− | HER2 signaling, high proliferation, frequent TP53 |
| **Basal-like** | KRT5/KRT14/KRT17, FOXC1, MIA, EGFR; ER−/PR−/HER2− | mostly triple-negative; TP53 ~80%, BRCA1 dysfunction, RB1 loss, genomically unstable |

**Recurrent alterations:** PIK3CA (luminal), TP53 (basal/HER2), GATA3, MAP3K1, CDH1
(lobular), MYC/ERBB2/CCND1 amplifications.

**Mechanistic axes:** (1) ER signaling — luminal vs non-luminal, the dominant axis; (2)
ERBB2/HER2 amplification; (3) proliferation gradient (LumA low → LumB/Basal high, MKI67 /
cell-cycle); (4) basal / TP53-driven genomic instability.

**Literature caveats:** "Normal-like" is widely regarded as a low-tumor-purity artifact,
not a real subtype. Luminal A/B is a continuum of proliferation, not a clean binary; a
cohort may not split them cleanly.

**Objective anchors (checkable in this benchmark):** ESR1/PGR/ERBB2/MKI67/KRT5/FOXC1
expression by cluster; PIK3CA/TP53/GATA3/CDH1 mutation frequency by cluster; survival by
cluster (LumA best, Basal/HER2 worse). ER/PR/HER2 IHC status is **not** in the data — any
"receptor-status" claim must be inferred from ESR1/PGR/ERBB2 expression, not asserted.

---

## LIHC — Liver hepatocellular carcinoma

**Canonical refs:** TCGA, *Cell* 2017 (169:1327, integrative HCC characterization); Hoshida
et al., *Cancer Res* 2009 (S1/S2/S3 classes); Boyault et al., *Hepatology* 2007 (G1–G6).

**Molecular classes (the reproducible axis):**

| Class | Defining features | Character |
|---|---|---|
| **Proliferation** (Hoshida S1/S2) | TP53 mut, high AFP, progenitor/stem (EPCAM, KRT19), activated AKT/mTOR, IGF, RAS/MAPK, chromosomal instability, E2F/cell-cycle | aggressive, worse survival |
| **Non-proliferation** (Hoshida S3) | CTNNB1 mut (Wnt/β-catenin), retained hepatocyte differentiation, HNF4A metabolic program | less aggressive, better differentiated |

**Recurrent alterations:** CTNNB1 (~25–30%; Wnt activation → GLUL, LGR5, AXIN2, TBX3;
associated with well-differentiated / metabolic / non-proliferative), TP53 (~30%;
proliferative/progenitor), AXIN1, ARID1A, ARID2, KEAP1/NFE2L2, TERT promoter. **AFP** =
progenitor/hepatoblast marker, elevated in aggressive/proliferative. **HNF4A** = master
hepatocyte-differentiation TF, drives the metabolic program.

**Mechanistic axes:** (1) proliferation vs differentiation (the primary axis); (2) CTNNB1/Wnt
(differentiated, metabolic) vs TP53 (proliferative, progenitor) — the two dominant mutually
suggestive mutation programs; (3) metabolic (bile-acid, fatty-acid, xenobiotic) vs
proliferative (E2F, cell cycle) transcriptional programs.

**Literature caveats:** CTNNB1 and TP53 tracks are tendencies, not laws — cohorts contain
CTNNB1-wt non-proliferative and mixed tumors. Not every canonical Wnt target (AXIN2, GLUL)
is co-expressed in every CTNNB1-mut tumor. Boyault G1–G6 and Hoshida S1–S3 are distinct
schemes and are not interchangeable.

**Objective anchors:** CTNNB1/TP53/AXIN1 mutation frequency by cluster (Fisher test);
AFP/HNF4A/EPCAM/KRT19/GLUL/AXIN2 expression by cluster; metabolic vs cell-cycle gene-set
direction; survival (proliferation worse). No IHC / serum-AFP labs — AFP claims are from
expression only.

---

## LUAD — Lung adenocarcinoma

**Canonical refs:** TCGA, *Nature* 2014 (511:543, molecular profiling of LUAD); Wilkerson
et al., *Clin Cancer Res* 2012 (expression subtypes).

**Transcriptional subtypes:**

| Subtype | Defining markers | Character |
|---|---|---|
| **Terminal respiratory unit (TRU / bronchioid)** | NKX2-1/TTF-1, surfactant (SFTPC, SFTPB, NAPSA); EGFR-enriched | well-differentiated, never-smoker–enriched, better prognosis |
| **Proximal-inflammatory (squamoid)** | immune/inflammatory program; NF1 + TP53 co-mutation | inflammatory |
| **Proximal-proliferative (magnoid)** | high proliferation; KRAS mut, STK11/LKB1 loss, TP53 | worse prognosis |

**Recurrent alterations:** KRAS (~30%; proximal-proliferative, smokers), EGFR (~15%; TRU,
never-smokers, targetable), TP53 (~50%), STK11/LKB1 (~15%; metabolic reprogramming,
immune-cold, frequent KRAS co-mutant), KEAP1/NFE2L2 (oxidative-stress/NRF2), NKX2-1/TTF-1
(lineage TF, amplified). Targetable fusions: ALK, ROS1, RET.

**Mechanistic axes:** (1) lineage differentiation (NKX2-1/TTF-1 + surfactant = TRU); (2)
dominant oncogenic driver — EGFR (TRU) vs KRAS (proximal-proliferative), largely mutually
exclusive; (3) STK11/KEAP1 co-mutation → metabolic/immune-cold state; (4) proliferation.

**Literature caveats:** EGFR and KRAS mutations are near-mutually-exclusive. The three
expression subtypes are less crisp than BRCA/OV and often don't reproduce cleanly at k=4.
TTF-1/NKX2-1 negativity does not by itself exclude LUAD.

**Objective anchors:** KRAS/EGFR/TP53/STK11/KEAP1 mutation frequency by cluster (Fisher);
NKX2-1/NAPSA/SFTPB/SFTPC expression by cluster; proliferation gene-set direction; survival
by cluster. Smoking status / fusion calls are **not** in the data — smoker/never-smoker and
ALK/ROS1 claims are recall unless a proxy is computed.

---

## OV — Ovarian serous cystadenocarcinoma (HGSOC)

**Canonical refs:** TCGA, *Nature* 2011 (474:609, integrated genomic analyses of ovarian
carcinoma); Verhaak et al., *JCI* 2013 (subtype refinement / prognostic signature).

**Backbone (not a subtype discriminator):** near-universal **TP53 mutation (~96%)**;
BRCA1/2 germline+somatic (~20%) → homologous-recombination deficiency; very high
copy-number instability (CCNE1, MYC, MECOM amplifications); few other recurrent point
mutations. HGSOC is a **copy-number–driven**, not mutation-driven, disease.

**Transcriptional subtypes (4):**

| Subtype | Defining markers | Character |
|---|---|---|
| **Immunoreactive** | T-cell chemokines CXCL11, CXCL10, CXCL13, CD3/CD8 | immune infiltration |
| **Differentiated** | MUC16 (CA125), MUC1, SLPI; secretory/fallopian markers | differentiated |
| **Proliferative** | MKI67, MCM2, PCNA; TFs HMGA2, SOX11; low differentiation | high proliferation, worse |
| **Mesenchymal** | stromal FAP, ANGPTL2, ANGPTL1, desmoplasia/collagen | stromal-rich, worst prognosis |

**Mechanistic axes:** (1) TP53 loss + HRD/genomic instability = the universal backbone
(present in ~all — so it does **not** separate subtypes); (2) the transcriptional axis —
immune infiltration vs stromal/mesenchymal vs proliferation vs differentiation; (3)
copy-number events (CCNE1 amp = HR-proficient, poor platinum response) rather than mutations.

**Literature caveats:** The four transcriptional subtypes have weak, poorly reproducible
prognostic separation (stated in the source literature); the mesenchymal (worst) vs
immunoreactive (best) survival contrast is the most robust. Immune/stromal signals are
heavily tumor-purity confounded — a "mesenchymal" cluster may be low-purity stroma. TP53
mutation is near-universal (~96%), so its presence does not distinguish subtypes.

**Objective anchors:** CXCL11/MUC16/MKI67/FAP expression by cluster; TP53 mutation frequency
(expect ~universal → non-discriminating); proliferation vs immune vs stromal gene-set
direction; survival by cluster (weak — see caveat). BRCA1/2 germline status and platinum
response are **not** in the data — HRD/platinum claims are recall unless a CNA/expression
proxy is computed.

---

## UCEC — Uterine corpus endometrial carcinoma

**Canonical refs:** TCGA, *Nature* 2013 (497:67, integrated genomic characterization of
endometrial carcinoma) — the four-group genomic classification.

**Backbone:** UCEC is defined by a **mutation-burden / copy-number** axis more than a clean
transcriptional one. PI3K/PTEN-pathway alteration is near-ubiquitous in endometrioid tumors
(PTEN loss, PIK3CA, PIK3R1). Histology splits endometrioid (estrogen-driven, favorable) vs
serous (TP53-mutant, aggressive).

**Genomic subtypes (4, TCGA 2013):**

| Subtype | Defining feature | Character |
|---|---|---|
| **POLE (ultramutated)** | POLE exonuclease-domain mutation; extreme SNV burden | best prognosis despite high grade |
| **MSI (hypermutated)** | microsatellite instability, MLH1 promoter hypermethylation | high SNV burden, endometrioid |
| **Copy-number low (endometrioid)** | MSS, low CN; PTEN/PIK3CA/CTNNB1/ARID1A/KRAS mut | estrogen-driven, favorable |
| **Copy-number high (serous-like)** | TP53 mutation, high CN, low SNV rate | serous + high-grade endometrioid, worst prognosis |

**Mechanistic axes:** (1) mutation burden — POLE/MSI hypermutation vs the CN-defined groups
(the primary axis, genomic not transcriptional); (2) PI3K/PTEN activation (endometrioid); (3)
TP53 + copy-number instability = the serous-like/CN-high pole; (4) estrogen signaling
(ESR1/PGR) in endometrioid vs its loss in serous.

**Literature caveats:** the four groups are **genomic** (SNV burden + CN + TP53), so expression
clustering may not recover them cleanly — the CN-low vs CN-high (endometrioid vs serous-like)
split is the most transcriptionally visible. POLE and MSI are hypermutation states, not
lineages. Grade/stage confound the endometrioid–serous axis.

**Objective anchors:** POLE / MLH1 status and total mutation count by cluster; TP53 mutation
frequency (marks CN-high/serous-like); PTEN/PIK3CA/CTNNB1/ARID1A frequency (endometrioid);
ESR1/PGR expression; copy-number burden (needs CNA). MSI status and grade are not in the
expression data — hypermutation must be read off the mutation matrix.

---

## PRAD — Prostate adenocarcinoma

**Canonical refs:** TCGA, *Cell* 2015 (163:1011, the molecular taxonomy of primary prostate
cancer).

**Backbone:** primary prostate cancer is **quiet at the point-mutation level** — driven by
recurrent ETS gene fusions and copy-number, under androgen-receptor (AR) signaling. ~74% fall
into seven driver-defined classes; ETS fusions (esp. TMPRSS2-ERG) dominate.

**Molecular classes (7, driver-defined):**

| Class | Defining lesion | Notes |
|---|---|---|
| **ERG** | TMPRSS2-ERG fusion (~46%) | ERG overexpression; most common |
| **ETV1 / ETV4 / FLI1** | other ETS-family fusions/overexpression | collectively another ~10–15% |
| **SPOP** | SPOP mutation | mutually exclusive with ETS; distinct CN |
| **FOXA1** | FOXA1 mutation | AR-cofactor, ETS-negative |
| **IDH1** | IDH1 mutation | rare, younger patients |

(~26% remain unclassified by driver.)

**Mechanistic axes:** (1) ETS-fusion status (ERG-high vs ERG-low) — the dominant, most
transcriptionally visible axis; (2) AR signaling output (KLK3/PSA, NKX3-1); (3) PTEN loss /
PI3K activation (aggressive); (4) TP53/RB1/BRCA2 loss in the more aggressive tail.

**Literature caveats:** primary PRAD has **excellent survival** (few events) → survival/outcome
endpoints are weak here. The 7-class scheme is fusion/mutation-defined, not a transcriptional
taxonomy — expression clustering mainly recovers **ERG-high vs ERG-low**. Gleason grade drives
aggression; if absent from the data, aggressiveness claims are recall.

**Objective anchors:** ERG expression (TMPRSS2-ERG fusion proxy) by cluster; SPOP / FOXA1 /
TP53 / PTEN mutation frequency; AR / KLK3 / NKX3-1 expression; PTEN CN loss (needs CNA).
Gleason and PSA are clinical fields, not expression — check whether they are provided.

---

## LUSC — Lung squamous cell carcinoma

**Canonical refs:** TCGA, *Nature* 2012 (489:519, comprehensive genomic characterization of
squamous cell lung cancers); Wilkerson et al. (the four expression subtypes).

**Backbone:** near-universal **TP53 mutation (~90%)** and CDKN2A loss; squamous lineage TFs
**SOX2 (3q amplification) and TP63**. Critically, LUSC **lacks the EGFR/KRAS/ALK drivers of
LUAD** — squamous markers (TP63, SOX2, KRT5/6/14) vs adeno markers (NKX2-1/TTF1, NAPSA, SFTPC)
are the key discriminator from lung adenocarcinoma.

**Expression subtypes (4, Wilkerson):**

| Subtype | Defining markers | Character |
|---|---|---|
| **Classical** | KEAP1/NFE2L2 (oxidative stress), xenobiotic/KRT, hypermethylation | most common |
| **Basal** | cell-adhesion, KRT5/KRT6, high TP63/SOX2 | basal squamous |
| **Secretory** | immune / secretory (surfactant-like), MUC genes | immune-infiltrated |
| **Primitive** | proliferation, MKI67/cell-cycle | high proliferation, worst prognosis |

**Mechanistic axes:** (1) the squamous lineage program (SOX2/TP63/KRT) — defines LUSC and
separates it from LUAD; (2) NFE2L2/KEAP1 oxidative-stress activation (classical); (3)
proliferation gradient (primitive worst); (4) immune/secretory infiltration.

**Literature caveats:** TP53 (~90%) and the squamous markers are near-universal → they identify
LUSC but do **not** separate the four subtypes. The Wilkerson subtypes have modest, not strong,
prognostic separation (primitive-worst is the most robust). Secretory/immune signal is
tumor-purity confounded. FGFR1 and SOX2 amplifications need CNA to see.

**Objective anchors:** SOX2 / TP63 / KRT5 expression (squamous identity, vs LUAD's
NKX2-1/NAPSA); TP53 mutation frequency (~universal → non-discriminating); MKI67 (primitive);
KEAP1/NFE2L2 mutation frequency (classical); SOX2/FGFR1 amplification (needs CNA); survival by
cluster (weak).

---

## Downstream

The rubric that consumes these cards — strategy tag (neutral) × support verdict (scored),
the revision check, quote-backed evidence, and the `grounded ≠ matches-the-card` safeguard —
is defined in the **judge prompt** (to be drafted), not here.
