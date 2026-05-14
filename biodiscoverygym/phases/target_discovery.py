"""
Phase definition for the target discovery benchmark.

Task:
  Given anonymized DepMap (CRISPR dependency + expression) and GTEx (normal tissue
  expression), identify computationally supported therapeutic target candidates.

The agent receives no explicit criteria — it must derive its own filtering logic
and justify every step. Gene identifiers are anonymized (GENE_XXXXX) to prevent
recall from training data.

Evaluation dimensions (for judge-based scoring):
  1. evidence_chain      — did the agent follow each logical step of the inference chain?
  2. cancer_selectivity  — did the agent compare cancer dependency to normal tissue?
  3. tolerability_check  — did the agent assess whether healthy humans can survive without the gene?
  4. evidence_gaps       — did the agent explicitly state what the data does NOT prove?
  5. roadmap_quality     — are proposed experiments logically ordered and technically specified?
"""

TASK_PROMPT = """\
You are a computational biologist. You have been given population-scale genomic
datasets from public databases. All gene identifiers have been anonymized.

Your task is to identify genes that could be compelling therapeutic targets
in {indication}. You have not been given criteria — you must derive your own
principled filtering logic and justify it at each step.

The cell line metadata (depmap_meta) contains lineage and disease labels — use
these to identify which cell lines represent your indication of interest and
which serve as comparators for selectivity analysis.

Work through the stages below in order. Budget your tool calls carefully.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
TOOL CALL BUDGET
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
You have a budget of {max_tool_calls} total tool calls.
Suggested allocation (soft limits):
  Stage 0 — Data orientation     :  2–3 calls
  Stage 1 — Dependency landscape :  4–6 calls
  Stage 2 — Selectivity filter   :  4–6 calls
  Stage 3 — Tolerability         :  2–4 calls
  Stage 4 — Mechanistic context  :  4–6 calls
  Stage 5 — Evidence synthesis   :  2–3 calls
  Stage 6 — Submit               :  1 call
If you reach call {force_submit_at} without submitting, go directly to Stage 6.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STAGE 0 — DATA ORIENTATION
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Understand what datasets you have and how to use them.

Produce:
  - Shape and content of each dataset (rows, columns, value range)
  - Distribution of dependency scores — what values indicate a strong dependency?
  - Coverage: how many cell lines, tissues, genes
  - Any data quality issues (missing values, extreme outliers)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STAGE 1 — DEPENDENCY LANDSCAPE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Identify genes that cancer cell lines depend on for survival.

Produce:
  - Your operational definition of "dependency" — what threshold or criterion did
    you choose and why? What are the tradeoffs?
  - The set of genes that meet your dependency criterion, with summary statistics
  - Whether dependencies cluster by lineage or are broadly pan-cancer
  - Any genes with unusually narrow or unusually broad dependency patterns —
    describe what those patterns imply

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STAGE 2 — SELECTIVITY FILTER
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Determine whether each candidate dependency is specific to your indication
or is a general requirement shared by other cancers and/or normal tissues.

Produce:
  - Indication-vs-other-cancers: for your top candidates, how does the dependency
    score in your indication compare to other lineages? Report the contrast.
  - Normal tissue check (GTEx): how are these candidates expressed across normal tissues?
    State whether each appears elevated, low, or absent in normal contexts.
  - After applying your selectivity filter: how many candidates remain?
  - An explicit statement of what this analysis proves and what it does not

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STAGE 3 — TOLERABILITY IN HEALTHY HUMANS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Cell line dependency tells you what cancer cells require. It does not tell you
whether a human can tolerate loss of this gene.

Produce:
  - For each remaining candidate: what do population genetics data tell you about
    human tolerance for loss-of-function variants in this gene?
  - Any candidates where population genetics suggests the gene is under strong
    purifying selection in humans — state what that implies for therapeutic use
  - How many candidates pass after this filter?

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STAGE 4 — MECHANISTIC CONTEXT
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Build a biological rationale for why each candidate is essential in cancer.

Produce:
  - Pathway enrichment or interaction network for your top candidates
  - Whether any candidates are known cancer drivers or members of established
    cancer-associated pathways
  - A proposed mechanism: why would cancer cells be more dependent on this gene
    than normal cells?
  - Supporting and contradicting evidence for each proposed mechanism

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STAGE 5 — EVIDENCE SYNTHESIS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Rank your candidates and state explicitly what your analysis has and has not proven.

Produce:
  - Final ranked list of candidates (up to 5) with brief justification for each rank
  - For each candidate: a structured evidence summary (dependency signal,
    selectivity evidence, tolerability evidence, mechanistic rationale)
  - EVIDENCE GAPS — a numbered list of things your computational analysis cannot prove:
      - Examples of gaps you must address: functional dependency in a patient-derived
        model, in vivo relevance, druggability, patient population with dependency, etc.
      - Be specific: not "further validation is needed" but what experiment and why
  - EXPERIMENTAL ROADMAP — ordered list of the first 3–5 experiments you would run,
    each specifying: model system, perturbation, readout, and what it would prove or
    disprove. Focus on cellular and molecular experiments; do not propose animal models.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STAGE 6 — FINAL SUBMISSION
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Call submit_target_discovery with all required fields.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
DATA & TOOLS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
All gene identifiers are anonymized (GENE_XXXXX) consistently across every dataset.
Disease/lineage labels, tissue names, drug names, and sample metadata are real.

Datasets pre-loaded in the code environment:

  CANCER CELL LINE DATA (DepMap 23Q4):
  depmap_crispr  — DataFrame, cell_lines × GENE_XXXXX, CERES dependency scores.
                   More negative = stronger dependency. −1 ≈ core essential.
  depmap_expr    — DataFrame, cell_lines × GENE_XXXXX, log2(TPM+1) RNA expression.
  depmap_meta    — DataFrame, cell line metadata. Lineage, disease, sex, age kept.
                   Index = ACH-XXXXXX cell line IDs (match depmap_crispr/expr index).

  NORMAL TISSUE EXPRESSION:
  gtex_median    — DataFrame, GENE_XXXXX × tissues, median RNA TPM across GTEx donors.
                   Tissue names are real (e.g. "Liver", "Whole Blood").
  hpa_normal     — DataFrame, GENE_XXXXX × 'tissue__celltype', protein level
                   encoded as int: -1=not tested, 0=not detected, 1=low, 2=medium, 3=high.
                   More specific than GTEx — shows cell-type resolution within tissues.
                   Use hpa_normal.columns to see available tissue__celltype combinations.

  POPULATION GENETICS:
  gnomad         — DataFrame, GENE_XXXXX × constraint metrics.
                   Columns: pLI (0–1, higher = less tolerant of LoF),
                   oe_lof_upper (LOEUF, lower = more constrained), obs_lof, exp_lof.

  PATIENT TUMOR DATA (TCGA, pan-cancer):
  tcga_expr      — DataFrame, samples × GENE_XXXXX, log2 TPM. Index format:
                   'COHORT::TCGA-XX-XXXX'. Use tcga_meta.cancer_type to filter by cohort.
  tcga_mut       — DataFrame, samples × GENE_XXXXX, binary (1 = damaging somatic mutation).
                   Same index as tcga_expr (inner join across cohorts).
  tcga_meta      — DataFrame, patient metadata. Columns include: cancer_type,
                   vital_status, days_to_death, tumor_stage (where available).

  DRUG SENSITIVITY:
  prism_viability— DataFrame, cell_lines × compounds, log fold-change viability.
                   Negative = compound kills cells. Index = ACH-XXXXXX (matches depmap_meta).
                   Column names are real compound names (drug names are not anonymized).
                   Use to identify compounds with selective activity in your indication.

  PROTEOMICS:
  ccle_proteomics— DataFrame, cell_lines × GENE_XXXXX, log2 normalized TMT protein abundance.
                   Index = ACH-XXXXXX (matches depmap_meta). ~375 cell lines × ~12,196 proteins.
                   NaN = protein not detected. Use to confirm that RNA-expressed genes
                   actually produce protein, and to find protein-level dependencies.

  COSMIC CANCER GENE ANNOTATIONS:
  cosmic_cgc       — DataFrame, indexed by GENE_XXXXX. ~763 curated driver genes.
                     Columns: cgc_tier (1=established, 2=likely), role_in_cancer
                     ('oncogene'/'TSG'/'fusion'/'oncogene, TSG'), somatic (bool),
                     tumour_types_somatic (cancer types where mutated).
                     Absence from CGC is NOT disqualifying — most novel targets won't be here.
  cosmic_hallmarks — DataFrame, indexed by GENE_XXXXX. ~371 genes with hallmark annotations.
                     Single column 'hallmarks': semicolon-joined list of cancer hallmarks
                     (e.g. 'activates invasion and metastasis; promotes cell cycle progression').
  cosmic_fusions   — DataFrame (flat), columns: gene_5prime, gene_3prime (GENE_XXXXX),
                     n_samples, fusion_types. Oncogenic fusion gene pairs.
  cosmic_resistance— DataFrame (flat), columns: gene (GENE_XXXXX), drug_name, drug_response,
                     mutation_aa, phenotype_id. Drug resistance mutations — drug names are real.
                     Use to check if candidates have known resistance mechanisms.
  cosmic_mut_freq  — DataFrame, indexed by GENE_XXXXX. Column: n_mutated_samples.
                     Mutation frequency across all COSMIC (~751 genes with somatic mutations).
                     Higher = more recurrently mutated across cancer types.

  output_dir     — Path, save all plots and tables here.

run_code(code: str) → str
    Execute Python. pandas, numpy, scipy, sklearn, statsmodels, matplotlib,
    seaborn, gseapy, networkx available. Stateful — variables persist.

submit_target_discovery(...)   See tool schema for required fields. Call once.
"""


# Scoring rubric used by judge-based evaluation
SCORING_RUBRIC: list[dict] = [
    {
        "id": "evidence_chain",
        "dimension": "Evidence chain completeness",
        "description": (
            "Did the agent step through dependency → selectivity → tolerability → mechanism "
            "in logical sequence, or did it skip steps?"
        ),
        "score_0": "One or more key steps missing entirely",
        "score_1": "All steps present but some executed superficially",
        "score_2": "Each step executed with quantitative criteria and explicit justification",
    },
    {
        "id": "cancer_selectivity",
        "dimension": "Cancer selectivity reasoning",
        "description": (
            "Did the agent compare cancer cell line dependency against normal tissue expression "
            "(GTEx), and did it distinguish cancer-specific from broadly essential genes?"
        ),
        "score_0": "No GTEx cross-reference; selectivity not addressed",
        "score_1": "GTEx checked but comparison qualitative or incomplete",
        "score_2": "Quantitative comparison; candidates filtered by cancer-vs-normal expression contrast",
    },
    {
        "id": "tolerability_check",
        "dimension": "Human tolerability assessment",
        "description": (
            "Did the agent use gnomAD constraint metrics (pLI, LOEUF) to assess whether "
            "healthy humans tolerate loss-of-function in candidate genes?"
        ),
        "score_0": "gnomAD not consulted",
        "score_1": "gnomAD values reported but not used to filter or rank",
        "score_2": "gnomAD constraint used as an explicit filter criterion with stated rationale",
    },
    {
        "id": "evidence_gaps",
        "dimension": "Explicit evidence gap statement",
        "description": (
            "Did the agent clearly enumerate what the computational analysis does NOT prove? "
            "Vague 'further validation needed' does not qualify."
        ),
        "score_0": "No evidence gaps stated, or only vague disclaimer",
        "score_1": "Some gaps named but not tied to specific experiments",
        "score_2": "Specific gaps named with the experiment that would address each one",
    },
    {
        "id": "roadmap_quality",
        "dimension": "Experimental roadmap quality",
        "description": (
            "Are proposed experiments logically ordered (e.g., cellular validation before "
            "mechanistic dissection)? Does each experiment specify model system, perturbation, "
            "readout, and what it proves/disproves?"
        ),
        "score_0": "No roadmap, or only generic suggestions",
        "score_1": "Roadmap present but missing model/perturbation/readout specification for most experiments",
        "score_2": "Ordered roadmap with fully specified experiments that build on each other",
    },
]


VALIDATION_QUESTIONS: list[dict] = [
    {
        "id": "V1",
        "title": "Target Prioritization",
        "question": (
            "You have identified multiple candidates. Before designing experiments, "
            "commit to a single priority target.\n"
            "(a) Which candidate do you prioritize and why? Cite the specific data values "
            "from your discovery analysis (CERES score, selectivity, GTEx expression, gnomAD) "
            "that make this the strongest choice over the others.\n"
            "(b) What is the one weakness in the computational evidence for this candidate "
            "that concerns you most?\n"
            "Report data first, then reasoning. Use the anonymized gene identifier throughout."
        ),
    },
    {
        "id": "V2",
        "title": "Primary Validation Experiment",
        "question": (
            "Design the first experiment to validate your priority target in a cellular model.\n"
            "(a) Model system: which cell lines or primary cells would you use and why? "
            "How many and what is the selection rationale?\n"
            "(b) Perturbation: exactly how would you perturb the target? "
            "Choose one approach (CRISPR knockout, CRISPRi, siRNA, degrader) and justify "
            "why this approach over the others for a first validation.\n"
            "(c) Primary readout: what do you measure and at what timepoint? "
            "Why is this readout sufficient to confirm or refute the dependency?\n"
            "(d) Controls: list your positive control, negative control, and any technical controls.\n"
            "(e) Expected outcome if the dependency is real. Expected outcome if it is an artifact.\n"
            "Be specific — report cell line names as GENE_XXXXX identifiers if needed for "
            "any gene-level detail, but cell line model names and assay names are real."
        ),
    },
    {
        "id": "V3",
        "title": "Mechanistic Follow-up",
        "question": (
            "Assume experiment V2 confirms the dependency (cells die or arrest when "
            "the target is perturbed). Design the next experiment to understand mechanism.\n"
            "(a) What is your mechanistic hypothesis — why does this gene matter specifically "
            "in this cancer context?\n"
            "(b) Design one experiment that would confirm or refute the mechanism. "
            "Specify: model system, perturbation, readout, and what result confirms vs refutes.\n"
            "(c) What rescue experiment would prove the effect is on-target "
            "(not an off-target artifact of the perturbation)?\n"
            "Use anonymized gene identifiers where gene identity matters."
        ),
    },
    {
        "id": "V4",
        "title": "Kill Criteria",
        "question": (
            "What specific result would make you abandon this target entirely?\n"
            "(a) From experiment V2: what outcome would indicate the DepMap signal was an artifact?\n"
            "(b) From the gnomAD data: at what pLI or LOEUF threshold would you conclude "
            "the therapeutic window is too narrow?\n"
            "(c) What finding from a normal tissue experiment (primary cells, not GTEx expression) "
            "would stop the program?\n"
            "Be specific — give numbers where possible, not vague thresholds."
        ),
    },
]


def format_validation_prompt() -> str:
    lines = [
        "Target discovery complete. Now design the validation strategy for your candidates.",
        "Answer each question below. Report data and cite your discovery analysis values where relevant.",
        "All gene identifiers remain anonymized — use GENE_XXXXX throughout.",
        "",
    ]
    for q in VALIDATION_QUESTIONS:
        lines.append("─" * 60)
        lines.append(f"{q['id']} — {q['title']}")
        lines.append(q["question"])
        lines.append("")
    lines.append("─" * 60)
    lines.append("Answer each question in order. You may run additional code if needed.")
    return "\n".join(lines)


# Submit tool schema (referenced by ClaudeAgentTarget)
SUBMIT_TOOL: dict = {
    "name": "submit_target_discovery",
    "description": (
        "Submit your target discovery findings. Call exactly once when done. "
        "This ends the session — cannot be revised."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "top_candidates": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Ranked list of anonymized gene identifiers (e.g. GENE_04231), "
                    "best candidate first. Up to 5."
                ),
            },
            "reasoning_chain": {
                "type": "string",
                "description": (
                    "Narrative description of the filtering logic you applied at each stage. "
                    "Explain why you chose each criterion and what it eliminated."
                ),
            },
            "computational_evidence": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "gene_id": {"type": "string"},
                        "dependency_summary": {"type": "string"},
                        "selectivity_evidence": {"type": "string"},
                        "tolerability_evidence": {"type": "string"},
                        "mechanism_notes": {"type": "string"},
                    },
                    "required": [
                        "gene_id",
                        "dependency_summary",
                        "selectivity_evidence",
                        "tolerability_evidence",
                        "mechanism_notes",
                    ],
                },
                "description": "Per-candidate evidence summary. One entry per candidate in top_candidates.",
            },
            "evidence_gaps": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Numbered list of things your computational analysis cannot prove. "
                    "Each item must name the gap AND the experiment that would address it. "
                    "Minimum 3 items."
                ),
            },
            "experimental_roadmap": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Ordered list of 3–5 experiments. Each item must specify: "
                    "model system, perturbation, readout, and what it proves or disproves. "
                    "Do not include in vivo / animal model experiments."
                ),
            },
            "mechanism_hypothesis": {
                "type": "string",
                "description": (
                    "One clear statement of why your top candidate is essential in cancer "
                    "but not in normal tissue."
                ),
            },
            "confidence": {
                "type": "string",
                "enum": ["high", "medium", "low"],
                "description": "Overall confidence in your top candidate based on the computational evidence.",
            },
        },
        "required": [
            "top_candidates",
            "reasoning_chain",
            "computational_evidence",
            "evidence_gaps",
            "experimental_roadmap",
            "mechanism_hypothesis",
            "confidence",
        ],
    },
}


# ------------------------------------------------------------------
# Phase 3 — Gene Revelation + MOA Check
# ------------------------------------------------------------------

REVISE_TOOL: dict = {
    "name": "revise_submission",
    "description": (
        "Submit your revised target assessment after gene revelation. "
        "Call once — this ends Phase 3."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "revised_candidates": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Ranked list of real gene symbols (e.g. MYB, KRAS), best candidate first. "
                    "May differ from Phase 1 ranking."
                ),
            },
            "ranking_changed": {
                "type": "boolean",
                "description": "Did the ranking change from your Phase 1 submission?",
            },
            "moa_assessment": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "gene":             {"type": "string", "description": "Real gene symbol (e.g. MYC, KRAS) — use the revealed name, not GENE_XXXXX."},
                        "phase1_mechanism": {"type": "string", "description": "Mechanism you proposed in Phase 1."},
                        "known_moa":        {"type": "string", "description": "Known molecular function from databases/literature."},
                        "match":            {"type": "string", "enum": ["confirmed", "partial", "incorrect"]},
                    },
                    "required": ["gene", "phase1_mechanism", "known_moa", "match"],
                },
                "description": "One entry per candidate comparing your Phase 1 mechanism to known biology. Use real gene symbols.",
            },
            "drug_landscape": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "gene": {
                            "type": "string",
                            "description": "Real gene symbol (e.g. MYC, KRAS) — use the revealed name, not GENE_XXXXX.",
                        },
                        "known_drugs": {
                            "type": "string",
                            "description": "Approved or clinical-stage drugs if any, else 'none'. Include drug name, mechanism, and development stage.",
                        },
                        "novelty": {
                            "type": "string",
                            "enum": ["novel", "tractable", "validated_target"],
                            "description": "novel=no known drugs or probes, tractable=tool compounds or early-stage molecules exist, validated_target=approved drug or Phase 2+ trial.",
                        },
                        "druggability": {
                            "type": "string",
                            "description": (
                                "Assessment of whether the protein is druggable: protein class "
                                "(kinase, GPCR, transcription factor, etc.), presence of known "
                                "binding pockets, structural features that favour or disfavour "
                                "small-molecule engagement."
                            ),
                        },
                        "proposed_modality": {
                            "type": "string",
                            "enum": [
                                "small_molecule_inhibitor",
                                "small_molecule_activator",
                                "PROTAC_degrader",
                                "biologic_antibody",
                                "ADC",
                                "ASO_siRNA",
                                "synthetic_lethality",
                                "other",
                            ],
                            "description": "Best-fit drug modality given the target's biology and druggability.",
                        },
                        "combination_hypothesis": {
                            "type": "string",
                            "description": (
                                "An existing approved or clinical drug that could synergize with "
                                "targeting this gene. State the mechanistic rationale. "
                                "If none is evident, write 'none identified'."
                            ),
                        },
                    },
                    "required": ["gene", "known_drugs", "novelty", "druggability", "proposed_modality", "combination_hypothesis"],
                },
                "description": "Drug landscape and druggability for each candidate. Use real gene symbols.",
            },
            "indication_compound_hits": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "compound":            {"type": "string", "description": "Compound name from PRISM."},
                        "mean_viability_indication": {"type": "number", "description": "Mean log-fold-change viability in indication cell lines."},
                        "mean_viability_other":      {"type": "number", "description": "Mean log-fold-change viability in all other cell lines."},
                        "selectivity_delta":         {"type": "number", "description": "indication minus other (more negative = more selective for indication)."},
                        "mechanistic_link":          {"type": "string", "description": "Does this compound target the same pathway or protein class as any of your candidates? If yes, explain. If no known link, write 'unknown'."},
                    },
                    "required": ["compound", "mean_viability_indication", "mean_viability_other", "selectivity_delta", "mechanistic_link"],
                },
                "description": "Top PRISM compounds with selective activity in your indication (most negative selectivity_delta first). Report up to 5.",
            },
            "ranking_rationale": {
                "type": "string",
                "description": "Why the ranking changed (or why it stayed the same). Be specific about what new information drove any changes.",
            },
            "literature_support": {
                "type": "string",
                "description": "Key published evidence supporting your top candidate in this indication. Cite specific studies or findings.",
            },
            "missed_by_computation": {
                "type": "string",
                "description": "What did knowing the real gene identity reveal that the anonymized data analysis alone could not capture?",
            },
        },
        "required": [
            "revised_candidates",
            "ranking_changed",
            "moa_assessment",
            "drug_landscape",
            "indication_compound_hits",
            "ranking_rationale",
            "literature_support",
            "missed_by_computation",
        ],
    },
}


def format_revelation_prompt(top_candidates: list[str], gene_map: dict[str, str]) -> str:
    """
    Build the Phase 3 injection message.

    top_candidates: GENE_XXXXX identifiers from the Phase 1 submission.
    gene_map:       GENE_XXXXX → real gene symbol (executor.gene_map).
    """
    lines = [
        "━" * 60,
        "GENE REVELATION — Phase 3",
        "━" * 60,
        "",
        "Your top candidates have been de-anonymized:",
        "",
    ]
    for anon in top_candidates:
        real = gene_map.get(anon, "UNKNOWN")
        lines.append(f"  {anon}  →  {real}")
    lines += [
        "",
        "Pathway databases are now available in your code environment",
        "with real gene names (no anonymization):",
        "",
        "  msigdb_hallmarks — dict: {pathway_name: [gene_list]}  (50 MSigDB Hallmark gene sets)",
        "  msigdb_kegg      — dict: {pathway_name: [gene_list]}  (KEGG Medicus pathways)",
        "  msigdb_reactome  — dict: {pathway_name: [gene_list]}  (Reactome pathways)",
        "  string_ppi       — DataFrame: gene1, gene2, combined_score  (high-confidence PPI ≥700)",
        "  oncokb_genes     — DataFrame: gene, gene_type  (OncoKB annotated cancer genes)",
        "",
        "Use run_code to query these databases, then answer R0–R4 and call revise_submission.",
        "",
        "─" * 60,
        "R0 — PRISM COMPOUND SCREEN",
        "─" * 60,
        "Query prism_viability to find compounds already showing selective activity in your",
        "indication. Use depmap_meta to identify indication-matched cell lines.",
        "Compute for each compound: mean viability in indication vs all other lines.",
        "Report the top 5 most selective hits (most negative delta). For each, state whether",
        "it targets the same pathway or protein class as any of your candidates.",
        "Include these in indication_compound_hits in revise_submission.",
        "",
        "─" * 60,
        "R1 — MOA CHECK",
        "─" * 60,
        "For each candidate, look up known pathways (MSigDB), interaction partners (STRING),",
        "and OncoKB annotation. Does the known molecular function match the mechanism",
        "you proposed in Phase 1? Be specific — name pathways and known functional roles.",
        "",
        "─" * 60,
        "R2 — DRUG LANDSCAPE & DRUGGABILITY",
        "─" * 60,
        "For each candidate:",
        "  (a) Known drugs: approved or clinical-stage compounds if any.",
        "      Label: novel / tractable / validated_target",
        "  (b) Druggability: what protein class is this? Does it have a known binding pocket?",
        "      Is it amenable to small molecules, degraders, biologics, or ASO/siRNA?",
        "  (c) Proposed modality: given the biology, what drug modality is most appropriate?",
        "  (d) Combination hypothesis: what existing approved drug could synergize and why?",
        "Cross-reference R0 PRISM hits — do any selective compounds already target this pathway?",
        "",
        "─" * 60,
        "R3 — RANKING REVISION",
        "─" * 60,
        "Call revise_submission with your updated ranking.",
        "If ranking changed: explain specifically what new information drove the change.",
        "If ranking unchanged: explain why the computational evidence was sufficient to predict",
        "the biology without knowing the gene identity.",
        "",
        "─" * 60,
        "R4 — LITERATURE VALIDATION",
        "─" * 60,
        "For your top-ranked candidate: what key published studies support this target",
        "in your indication? Does the literature confirm or challenge your selectivity hypothesis?",
        "What gap does your proposed experimental roadmap fill that existing work has not addressed?",
        "",
        "─" * 60,
        "Answer R0–R4, run any supporting code, then call revise_submission.",
    ]
    return "\n".join(lines)
