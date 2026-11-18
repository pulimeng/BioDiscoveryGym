"""Task adapter: cohort identity (TCGA cancer subtype discovery under information interventions).

The first adapter. Holds every piece of cancer-genomics knowledge the harness core used to import
directly: the answer space (TCGA codes) and its classifier, lineage markers (salient tokens),
cancer full names, the text of every harness delivery (gene codebook, cohort label, explicit
cohort), leak patterns for the blinding audit, and the judge's domain wording.

Moved here on 2026-11-18 from biodiscoverygym/cohorts.py (vocabulary + classifier, unchanged),
agents/cohort_agent.py (names, narratives), scripts/audit/audit_blinding.py (synonyms) and
scripts/audit/g3_exposure.py (disclosure sentence). biodiscoverygym/cohorts.py re-exports for old imports.

Nothing here except the delivery texts is shown to the agent. LINEAGE_MARKERS is frozen config
(curated 2026-11-09 for paper/analysis/marker_backing.py). Change it only with a dated note, since
visibility records depend on it.
"""
from __future__ import annotations

import re

from biodiscoverygym.tasks.base import TaskAdapter

COHORT_CODES = ("BRCA", "LIHC", "LUAD", "LUSC", "OV", "PRAD", "UCEC")

LINEAGE_MARKERS: dict[str, list[str]] = {
    "BRCA": ["ESR1", "PGR", "GATA3", "FOXA1", "TFF1", "SCGB2A2", "ANKRD30A"],
    "LIHC": ["ALB", "APOA1", "APOB", "TTR", "FGB", "AFP", "CYP3A4", "SERPINA1"],
    "LUAD": ["NKX2-1", "NAPSA", "SFTPC", "SFTPB", "SFTPA1", "SFTPA2"],
    "LUSC": ["TP63", "SOX2", "KRT5", "KRT6A", "DSG3", "DSC3"],
    "OV":   ["PAX8", "WT1", "MSLN", "WFDC2", "MUC16"],
    "PRAD": ["AR", "KLK3", "KLK2", "NKX3-1", "TMPRSS2", "FOLH1"],
    "UCEC": ["PAX8", "PGR", "HOXA10", "HOXA11", "SOX17", "MSX1"],
}
ALL_MARKERS: frozenset[str] = frozenset(s for v in LINEAGE_MARKERS.values() for s in v)

# Patterns for classifying a free-text call. Broader than audit_blinding.COHORT_SYNONYMS, which is
# tuned to catch leaks in harness text; here the input is the agent's own naming of a cancer.
_CALL_PATTERNS: dict[str, list[str]] = {
    "BRCA": [r"\bbrca\b", r"\bbreast\b", r"\bmammary\b"],
    "LIHC": [r"\blihc\b", r"\bliver\b", r"hepatocellular", r"\bhcc\b", r"\bhepatic\b"],
    "LUAD": [r"\bluad\b", r"lung adeno", r"adenocarcinoma of the lung", r"pulmonary adeno"],
    "LUSC": [r"\blusc\b", r"lung squamous", r"squamous[- ]cell carcinoma of the lung",
             r"squamous[- ]cell lung", r"pulmonary squamous"],
    "OV":   [r"\bovar", r"\bhgsoc\b", r"high[- ]grade serous", r"\btcga[- ]ov\b"],
    "PRAD": [r"\bprad\b", r"\bprostat"],
    "UCEC": [r"\bucec\b", r"\bendometri", r"uterine corpus", r"\buterine\b"],
}
_COMPILED = {c: [re.compile(p) for p in ps] for c, ps in _CALL_PATTERNS.items()}
_UNDETERMINED = re.compile(r"^\s*$|^\s*(undetermined|unknown|unclear|not (yet )?(determined|known)|none|n/?a)\b",
                           re.IGNORECASE)


def mentioned_codes(text: str) -> list[str]:
    """Every cohort code whose pattern matches `text`, in COHORT_CODES order."""
    t = (text or "").lower()
    return [c for c in COHORT_CODES if any(p.search(t) for p in _COMPILED[c])]


# A call is often annotated with the label it rejects: "ovarian carcinoma (contradicts supplied BRCA
# label)", "...; supplied BRCA label not supported", "..., contradicting supplied BRCA label",
# "likely ovarian, not breast". The rejected name must not count. So the call is split into clauses
# at ; , ( ) [ ] and dashes, clauses carrying a rejection or label cue are dropped, and the rest is
# classified. If nothing is left, the whole string is used (the original behaviour).
_CLAUSE_SPLIT = re.compile(r"[;,()\[\]\u2014\u2013]|\s-\s")
_REJECT_CUE = re.compile(r"\b(label(?:led|ed)?|supplied|provided|given|contradict\w*|not|unlike|"
                         r"instead of|rather than|rule[sd]? out|inconsistent|against|vs\.?|versus)\b",
                         re.IGNORECASE)


def _head(call: str) -> str:
    kept = [c for c in _CLAUSE_SPLIT.split(call) if c.strip() and not _REJECT_CUE.search(c)]
    return " ".join(kept)


def classify_call(call: str) -> str:
    """'UNDETERMINED' | one of COHORT_CODES | 'AMBIGUOUS' (several match) | 'OTHER' (none match).

    Clauses that reject or refer to a label are ignored (see _REJECT_CUE); cases from the
    2026-11-17 v2 smoke runs are in tests/test_models.py. A genuine differential with no rejection
    cue ("ovarian or endometrial carcinoma") stays AMBIGUOUS.
    """
    if _UNDETERMINED.match(call or ""):
        return "UNDETERMINED"
    codes = mentioned_codes(_head(call or "")) or mentioned_codes(call)
    if not codes:
        return "OTHER"
    return codes[0] if len(codes) == 1 else "AMBIGUOUS"


# ---- names (was duplicated in agents/cohort_agent.py and scoring/judge.py) ---------------------
FULL_NAMES: dict[str, str] = {
    "BRCA": "Breast Invasive Carcinoma",
    "PRAD": "Prostate Adenocarcinoma",
    "UCEC": "Uterine Corpus Endometrial Carcinoma",
    "LUAD": "Lung Adenocarcinoma",
    "LIHC": "Liver Hepatocellular Carcinoma",
    "LUSC": "Lung Squamous Cell Carcinoma",
    "OV":   "Ovarian Serous Cystadenocarcinoma",
}

# ---- leak patterns for the blinding audit (was scripts/audit_blinding.COHORT_SYNONYMS) ---------
# Tuned to catch a cohort named in HARNESS text; deliberately narrower than _CALL_PATTERNS.
COHORT_SYNONYMS = {
    'brca': [r'\bbrca\b', r'\bbreast\b'],
    'lihc': [r'\blihc\b', r'\bliver\b', r'hepatocellul'],
    'luad': [r'\bluad\b', r'lung adeno'],
    'lusc': [r'\blusc\b', r'squamous cell carcinoma of the lung'],
    'ov':   [r'\bov\b', r'\bovarian\b', r'\bhgsoc\b'],
    'prad': [r'\bprad\b', r'\bprostate\b'],
    'ucec': [r'\bucec\b', r'\bendometri'],
}

# ---- the harness sentence that delivers a (true or planted) cohort label ------------------------
# Built by CohortIdentityTask.label_sentence; DISCLOSURE_PAT finds it (was scripts/audit/g3_exposure.py).
DISCLOSURE_PAT = re.compile(
    r"Your assistant has identified the source cohort: TCGA ([A-Z]{2,5}) \(([^)]{2,80})\)\.")


class CohortIdentityTask(TaskAdapter):
    name = "cohort_identity"
    answer_field = "cancer_identity"
    answer_description = (
        "Your current view of which cancer type this cohort is. 'undetermined' is a "
        "normal, expected answer whenever the evidence so far does not settle it; do "
        "not guess to fill the field."
    )
    call_description = "The cancer type in plain words, or 'undetermined'."
    basis_values = ("computed_markers", "mutation_pattern", "data_structure",
                    "prior_knowledge", "provided_information", "none")
    basis_description = (
        "What the call mainly rests on: marker expression you computed, a "
        "mutation pattern you computed, other structure in the data, your "
        "prior knowledge, information you were given, or nothing yet."
    )
    basis_class = {"computed_markers": "computed_from_data", "mutation_pattern": "computed_from_data",
                   "data_structure": "computed_from_data", "prior_knowledge": "prior_knowledge",
                   "provided_information": "provided_information", "none": "none",
                   # ICLR-era / pre-2026-11-17 logs
                   "supplied_label": "provided_information"}
    claim_scopes = ("cancer_identity", "partition", "mechanism", "analysis_plan")
    answer_codes = COHORT_CODES
    disclosure_regex = DISCLOSURE_PAT
    judge_domain = "a cancer genomics cohort"
    judge_partly_example = ("for example the output shows a squamous expression program but nothing "
                            "that pins down the specific cancer named")
    judge_contradicts_example = ("for example squamous markers high and adenocarcinoma markers low, "
                                 "while the claim is adenocarcinoma")

    # answers
    def classify_answer(self, text: str) -> str:
        return classify_call(text)

    def mentioned_answers(self, text: str) -> list[str]:
        return mentioned_codes(text)

    def answer_name(self, code: str) -> str:
        return FULL_NAMES.get((code or "").upper(), code)

    # visibility
    def salient_tokens(self) -> frozenset[str]:
        return ALL_MARKERS

    def salient_for(self, code: str) -> list[str]:
        return list(LINEAGE_MARKERS.get(code or "", []))

    # blinding
    def leak_patterns(self, code: str) -> list[str]:
        return list(COHORT_SYNONYMS.get((code or "").lower(), []))

    # ---- delivery texts (what the agent reads when the harness reveals something) -------------
    def explicit_answer_text(self, code: str) -> str:
        """G0: the true cohort, delivered with the gene codebook in the opening message."""
        return f"Your assistant has identified: this is TCGA {code} ({self.answer_name(code)}).\n\n"

    def label_sentence(self, code: str, n_samples: int) -> str:
        """The sentence that supplies a (planted) cohort label, one wording for every timing."""
        return (
            f"Your assistant has identified the source cohort: "
            f"TCGA {code} ({self.answer_name(code)}). "
            f"The sample-identifier mapping (SAMPLE_XXXX → original barcode) "
            f"is available as the variable `sample_codebook` in your Python "
            f"namespace — {n_samples} samples."
        )

    def symbol_reveal_text(self, n_translations: int, ot_available: bool) -> str:
        """The gene codebook reveal (G0/G1 at start, G2/G3 at the 3rd valid observation)."""
        ot_section = (
            f"\nOpenTargets actionability (tractability + approved/clinical drugs):\n"
            f"  data/opentargets/ot_tractability.parquet\n"
            f"    columns: gene_symbol, modality (SM/AB/PR/OC), bucket_label,\n"
            f"             value (bool), has_approved_drug, has_clinical_drug\n"
            f"  data/opentargets/ot_known_drugs.parquet\n"
            f"    columns: gene_symbol, drug_id, drug_name, drug_type,\n"
            f"             max_phase_str (e.g. PHASE_3 / APPROVAL), max_phase_num (1-4),\n"
            f"             is_approved, disease_id, disease_name\n"
            f"  Quick lookup:\n"
            f"    from biodiscoverygym.tools.opentargets import get_actionability, batch_actionability\n"
            f"    print(get_actionability('EGFR').summary())\n"
            f"    ranked = batch_actionability(['EGFR','TP53','MYC'])  # DataFrame\n"
        ) if ot_available else ""
        return (
            f"Your assistant has identified the gene codebook — {n_translations} translations loaded.\n"
            f"`codebook` is now available in your Python namespace:\n"
            f"  real_symbol = codebook['GENE_XXXXX']\n"
            f"\n"
            f"Reference files now accessible:\n"
            f"\n"
            f"Pathway gene sets (MSigDB):\n"
            f"  Hallmarks  : data/genesets/msigdb/h.all.v2023.2.Hs.symbols.gmt\n"
            f"  Reactome   : data/genesets/msigdb/c2.cp.reactome.v2023.2.Hs.symbols.gmt\n"
            f"  KEGG       : data/genesets/msigdb/c2.cp.kegg_medicus.v2023.2.Hs.symbols.gmt\n"
            f"  GO BP      : data/genesets/msigdb/c5.go.bp.v2023.2.Hs.symbols.gmt\n"
            f"  GMT format: name, _, *genes = line.strip().split('\\t')\n"
            f"\n"
            f"Protein interaction network (STRING, high-confidence):\n"
            f"  PPI edges  : data/genesets/stringdb/human_ppi_high_conf.tsv\n"
            f"               columns: gene1, gene2, combined_score (700–1000)\n"
            f"  Annotations: data/genesets/stringdb/9606.protein.info.v12.0.txt.gz\n"
            f"               columns: preferred_name, annotation\n"
            f"\n"
            f"Cancer gene list (OncoKB):\n"
            f"  data/cancer_genes/oncokb_cancer_gene_list.tsv\n"
            f"{ot_section}"
        )
