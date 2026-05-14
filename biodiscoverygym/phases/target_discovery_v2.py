"""
Phase definition for target discovery benchmark — v2 (open-ended).

v1 gave the agent explicit stages (dependency → selectivity → tolerability → mechanism).
v2 gives only an objective: find a target with a definable patient population.
The agent must design its own analytical pipeline. Methodology is evaluated, not just conclusions.

Key differences from v1:
  - No stages in the prompt — analytical strategy is part of the task
  - Submit tool requires a patient biomarker and cell-line stratification evidence
  - Submit tool requires TCGA-derived patient population frequency estimate
  - Phase 2 validation focuses on clinical translation and resistance
  - Scoring rubric rewards methodological depth, not just logical chain

Scoring dimensions (0–2 each, max 10):
  biomarker_identification   — did the agent find a specific, testable molecular feature?
  cell_line_stratification   — is the biomarker-dependency link quantified in cell lines?
  patient_frequency          — is the patient population estimated from TCGA?
  mechanism_biomarker_link   — is there a mechanistic explanation for why biomarker predicts dependency?
  methodological_depth       — did the agent go beyond univariate filters?
"""

# ------------------------------------------------------------------
# Task prompt
# ------------------------------------------------------------------

TASK_PROMPT_V2 = """\
You are a computational biologist with access to population-scale genomic datasets.
All gene identifiers have been anonymized (GENE_XXXXX).

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
OBJECTIVE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Identify a therapeutic target for {indication} with a definable patient population.

A viable therapeutic hypothesis requires three things:
  1. A target gene that cancer cells depend on for survival
  2. A patient biomarker — a specific, testable molecular feature that identifies
     which patients carry this dependency (not all patients — a definable subset)
  3. Evidence that the biomarker-defined population exists in real patient tumors
     and represents a meaningful clinical opportunity

You have not been given an analytical pipeline — designing the methodology is part
of the task. Your approach will be evaluated on rigor and depth, not just conclusions.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
TOOL CALL BUDGET
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
You have {max_tool_calls} tool calls.
If you reach call {force_submit_at} without submitting, submit with whatever you have.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
WHAT YOUR SUBMISSION MUST INCLUDE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  target                        — the gene you are proposing
  analytical_approach           — the methodology you designed and why
  patient_biomarker             — the molecular feature defining the responsive population:
                                  what would be measured in a patient sample, and what
                                  threshold defines positivity?
  biomarker_cell_line_validation— quantitative evidence that biomarker-positive cell lines
                                  are more dependent than biomarker-negative lines
                                  (effect size, p-value, n per group, statistical method)
  patient_population_estimate   — frequency of the biomarker in real patient tumors (TCGA)
                                  and the estimated number of eligible patients
  mechanism_hypothesis          — why does the biomarker predict dependency on the target?
  drug_strategy                 — how would you exploit this target-biomarker pair
                                  therapeutically? What modality, what patient selection?
  evidence_gaps                 — what your analysis cannot prove, and the experiment
                                  that would address each gap

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
  hpa_normal     — DataFrame, GENE_XXXXX × 'tissue__celltype', protein level
                   encoded as int: -1=not tested, 0=not detected, 1=low, 2=medium, 3=high.

  POPULATION GENETICS:
  gnomad         — DataFrame, GENE_XXXXX × constraint metrics.
                   Columns: pLI, oe_lof_upper (LOEUF), obs_lof, exp_lof.

  PATIENT TUMOR DATA (TCGA, pan-cancer):
  tcga_expr      — DataFrame, samples × GENE_XXXXX, log2 TPM.
                   Index format: 'COHORT::TCGA-XX-XXXX'. Filter by tcga_meta.cancer_type.
  tcga_mut       — DataFrame, samples × GENE_XXXXX, binary (1 = damaging somatic mutation).
                   Same index as tcga_expr.
  tcga_meta      — DataFrame, patient metadata. Columns: cancer_type, vital_status,
                   days_to_death, tumor_stage.

  DRUG SENSITIVITY:
  prism_viability— DataFrame, cell_lines × compounds, log fold-change viability.
                   Negative = compound kills cells. Index = ACH-XXXXXX.
                   Column names are real compound names (not anonymized).

  PROTEOMICS:
  ccle_proteomics— DataFrame, cell_lines × GENE_XXXXX, log2 normalized TMT protein abundance.
                   ~375 cell lines × ~12,196 proteins. NaN = not detected.

  COSMIC CANCER GENE ANNOTATIONS:
  cosmic_cgc       — DataFrame, GENE_XXXXX index. ~763 curated driver genes.
                     Columns: cgc_tier, role_in_cancer, somatic, tumour_types_somatic.
  cosmic_hallmarks — DataFrame, GENE_XXXXX index. Semicolon-joined cancer hallmarks.
  cosmic_fusions   — DataFrame, columns: gene_5prime, gene_3prime (GENE_XXXXX), n_samples.
  cosmic_resistance— DataFrame, columns: gene (GENE_XXXXX), drug_name, drug_response.
  cosmic_mut_freq  — DataFrame, GENE_XXXXX index, column: n_mutated_samples.

  output_dir     — Path, save all plots and tables here.

run_code(code: str) → str
    Execute Python. pandas, numpy, scipy, sklearn, statsmodels, matplotlib,
    seaborn, gseapy, networkx available. Stateful — variables persist.

submit_target_discovery(...)   See tool schema. Call once when done.
"""


# ------------------------------------------------------------------
# Submit tool
# ------------------------------------------------------------------

SUBMIT_TOOL_V2: dict = {
    "name": "submit_target_discovery",
    "description": (
        "Submit your target discovery findings. Call exactly once when done. "
        "This ends the session — cannot be revised."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "target": {
                "type": "string",
                "description": "Anonymized gene identifier (GENE_XXXXX) of your primary target.",
            },
            "analytical_approach": {
                "type": "string",
                "description": (
                    "Describe the overall analytical strategy you designed. "
                    "What methods did you apply, in what order, and why? "
                    "What alternatives did you consider and reject?"
                ),
            },
            "patient_biomarker": {
                "type": "object",
                "properties": {
                    "feature_type": {
                        "type": "string",
                        "enum": [
                            "mutation",
                            "high_expression",
                            "low_expression",
                            "amplification",
                            "deletion",
                            "multi_gene_signature",
                            "other",
                        ],
                        "description": "Type of molecular feature.",
                    },
                    "feature_gene": {
                        "type": "string",
                        "description": (
                            "Anonymized gene identifier (GENE_XXXXX) that defines the biomarker. "
                            "May be the same as target or a different gene."
                        ),
                    },
                    "description": {
                        "type": "string",
                        "description": (
                            "Precise description: what would be measured in a patient sample, "
                            "and what threshold or criterion defines positivity?"
                        ),
                    },
                },
                "required": ["feature_type", "feature_gene", "description"],
                "description": "The molecular feature that identifies which patients carry this dependency.",
            },
            "biomarker_cell_line_validation": {
                "type": "object",
                "properties": {
                    "n_positive_lines":         {"type": "integer", "description": "Number of biomarker-positive cell lines."},
                    "n_negative_lines":         {"type": "integer", "description": "Number of biomarker-negative cell lines."},
                    "mean_dependency_positive": {"type": "number",  "description": "Mean CRISPR score in biomarker-positive lines."},
                    "mean_dependency_negative": {"type": "number",  "description": "Mean CRISPR score in biomarker-negative lines."},
                    "effect_size":              {"type": "number",  "description": "Cohen's d or equivalent effect size."},
                    "p_value":                  {"type": "number",  "description": "P-value for the dependency difference."},
                    "statistical_method":       {"type": "string",  "description": "Statistical test used (e.g. Welch t-test, Mann-Whitney U)."},
                },
                "required": [
                    "n_positive_lines", "n_negative_lines",
                    "mean_dependency_positive", "mean_dependency_negative",
                    "effect_size", "p_value", "statistical_method",
                ],
                "description": "Quantitative evidence that the biomarker stratifies dependency in cell lines.",
            },
            "patient_population_estimate": {
                "type": "object",
                "properties": {
                    "tcga_cohort":         {"type": "string",  "description": "TCGA cancer type(s) used (e.g. 'LUAD', 'pan-cancer')."},
                    "n_patients_total":    {"type": "integer", "description": "Total patients in the relevant TCGA cohort."},
                    "n_biomarker_positive":{"type": "integer", "description": "Patients with the biomarker."},
                    "frequency_percent":   {"type": "number",  "description": "Biomarker prevalence as a percentage."},
                    "method":              {"type": "string",  "description": "How biomarker positivity was determined from TCGA data."},
                },
                "required": [
                    "tcga_cohort", "n_patients_total",
                    "n_biomarker_positive", "frequency_percent", "method",
                ],
                "description": "Estimated frequency of the biomarker in real patient tumors from TCGA.",
            },
            "mechanism_hypothesis": {
                "type": "string",
                "description": (
                    "Why does the biomarker predict dependency on the target? "
                    "State the mechanistic link between the molecular feature and the dependency."
                ),
            },
            "drug_strategy": {
                "type": "string",
                "description": (
                    "How would you therapeutically exploit this target-biomarker pair? "
                    "Include: proposed modality, patient selection strategy, "
                    "and why this combination is actionable."
                ),
            },
            "evidence_gaps": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Numbered list of things your analysis cannot prove. "
                    "Each item must name the gap AND the experiment that would address it. "
                    "Minimum 3 items."
                ),
            },
            "confidence": {
                "type": "string",
                "enum": ["high", "medium", "low"],
                "description": "Overall confidence in your target-biomarker hypothesis.",
            },
        },
        "required": [
            "target",
            "analytical_approach",
            "patient_biomarker",
            "biomarker_cell_line_validation",
            "patient_population_estimate",
            "mechanism_hypothesis",
            "drug_strategy",
            "evidence_gaps",
            "confidence",
        ],
    },
}


# ------------------------------------------------------------------
# Scoring rubric
# ------------------------------------------------------------------

SCORING_RUBRIC_V2: list[dict] = [
    {
        "id": "biomarker_identification",
        "dimension": "Patient biomarker identification",
        "description": (
            "Did the agent identify a specific, testable molecular feature that defines "
            "the responsive patient population? Vague population definitions do not qualify."
        ),
        "score_0": "No biomarker identified, or only 'cancer type' as stratification",
        "score_1": "Biomarker named but not quantitatively validated or threshold not specified",
        "score_2": "Specific biomarker with positivity criterion, validated in cell lines with effect size",
    },
    {
        "id": "cell_line_stratification",
        "dimension": "Cell line biomarker stratification",
        "description": (
            "Did the agent demonstrate that biomarker-positive cell lines are more dependent "
            "than biomarker-negative lines, with proper statistical quantification?"
        ),
        "score_0": "No stratification analysis, or only visual inspection",
        "score_1": "Stratification shown but missing effect size or sample sizes are very small",
        "score_2": "Quantitative comparison with n per group, effect size, p-value, and appropriate test",
    },
    {
        "id": "patient_frequency",
        "dimension": "Patient population estimation from TCGA",
        "description": (
            "Did the agent estimate the frequency of the biomarker in real patient tumors "
            "using TCGA data, and is the estimate credible?"
        ),
        "score_0": "No TCGA analysis, or frequency not reported",
        "score_1": "TCGA consulted but frequency estimate is rough or method not specified",
        "score_2": "TCGA frequency reported with patient counts, cohort specified, and method described",
    },
    {
        "id": "mechanism_biomarker_link",
        "dimension": "Mechanistic link between biomarker and dependency",
        "description": (
            "Is there a coherent mechanistic explanation for why the biomarker predicts "
            "dependency on the target — not just correlation, but a plausible causal model?"
        ),
        "score_0": "No mechanistic explanation, or purely correlational argument",
        "score_1": "Mechanism proposed but speculative and not tied to specific biological evidence",
        "score_2": "Specific mechanistic model with supporting evidence from the data",
    },
    {
        "id": "methodological_depth",
        "dimension": "Methodological sophistication",
        "description": (
            "Did the agent go beyond simple univariate filters? Examples of deeper methods: "
            "regression of dependency on molecular features, co-essentiality network analysis, "
            "multi-omics corroboration, survival stratification in TCGA."
        ),
        "score_0": "Only sequential threshold filters on individual datasets",
        "score_1": "At least one integrative or multivariate analysis attempted",
        "score_2": "Multiple datasets integrated with statistical models; approach justified by the question",
    },
]


# ------------------------------------------------------------------
# Phase 2 validation questions
# ------------------------------------------------------------------

VALIDATION_QUESTIONS_V2: list[dict] = [
    {
        "id": "V1",
        "title": "Biomarker Clinical Translation",
        "question": (
            "Your patient biomarker defines the responsive population computationally. "
            "Now translate it to a clinical test.\n"
            "(a) What assay would you run on a patient biopsy to determine eligibility? "
            "Specify: tissue source, assay type (IHC, NGS, RNA-seq, FISH), and the positivity threshold.\n"
            "(b) What is the expected false-positive rate of this test — which patients would "
            "be enrolled but are unlikely to respond?\n"
            "(c) Is this assay already in clinical use for another indication, or would it "
            "require development? What is the regulatory path?\n"
            "Use anonymized gene identifiers throughout."
        ),
    },
    {
        "id": "V2",
        "title": "Clinical Cohort Design",
        "question": (
            "Design the patient cohort for a proof-of-concept clinical study.\n"
            "(a) Inclusion criteria: how would you select patients using your biomarker? "
            "State the exact criterion a physician would apply.\n"
            "(b) Based on your TCGA frequency estimate, how many patients would need to be "
            "screened to enroll 30 biomarker-positive patients?\n"
            "(c) Primary endpoint: what would you measure and at what timepoint? "
            "Why is this endpoint appropriate for this target and population?\n"
            "(d) What is your go/no-go decision rule at the primary endpoint?"
        ),
    },
    {
        "id": "V3",
        "title": "Resistance and Escape",
        "question": (
            "Assume the drug works initially but patients relapse. Design a resistance analysis.\n"
            "(a) From your CRISPR data: are there co-essential genes that could compensate "
            "if your target is inhibited? Identify the top 2–3 candidates.\n"
            "(b) From the mutation and expression data: what secondary alterations co-occur "
            "with your biomarker that might modulate response?\n"
            "(c) Design one experiment to model acquired resistance in vitro. "
            "Specify: cell line, perturbation, selection strategy, readout.\n"
            "Use anonymized gene identifiers where gene identity matters."
        ),
    },
    {
        "id": "V4",
        "title": "Kill Criteria",
        "question": (
            "What would stop this program?\n"
            "(a) What TCGA biomarker frequency would make the patient population too small "
            "to be commercially viable? Give a number.\n"
            "(b) What cell-line stratification result would indicate the biomarker doesn't "
            "actually predict dependency — give a specific effect size or p-value threshold.\n"
            "(c) What gnomAD finding would indicate the therapeutic window is too narrow "
            "for the proposed modality?\n"
            "(d) What finding from a normal tissue experiment (primary cells) would "
            "stop the program regardless of the cancer data?"
        ),
    },
]


def format_validation_prompt_v2() -> str:
    lines = [
        "Target discovery complete. Now stress-test your target-biomarker hypothesis.",
        "Answer each question below. Cite your discovery analysis values where relevant.",
        "All gene identifiers remain anonymized — use GENE_XXXXX throughout.",
        "",
    ]
    for q in VALIDATION_QUESTIONS_V2:
        lines.append("─" * 60)
        lines.append(f"{q['id']} — {q['title']}")
        lines.append(q["question"])
        lines.append("")
    lines.append("─" * 60)
    lines.append("Answer each question in order. You may run additional code if needed.")
    return "\n".join(lines)
