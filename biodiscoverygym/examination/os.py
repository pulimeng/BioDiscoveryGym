"""OS (osteosarcoma) examination module — evaluator-side canonical expectations."""
from biodiscoverygym.examination.generic import (
    DATA_LOCK_PROMPT,
    Q1_Q3_PROMPT,
    Q4_PROMPT,
    QUESTIONS,
    format_data_lock_prompt,
    format_q1_q3_prompt,
    format_q4_prompt,
    format_examination_prompt,
)

CANONICAL_EXPECTATIONS: list[dict] = [
    {
        "id": "s_hrd_brca2_platinum",
        "claim": "S-HRD subtype is defined by BRCA2 deletion and homologous recombination deficiency (~80% HRD+); platinum/PARPi sensitivity is the therapeutic implication.",
        "sources": "Jia et al. 2022 Nat Commun",
    },
    {
        "id": "s_md_myc_chemo_resistant",
        "claim": "S-MD subtype is driven by MYC amplification, characterized by OXPHOS and proliferative gene programs, immune-cold, and worst prognosis with chemo-resistance.",
        "sources": "Jia et al. 2022 Nat Commun",
    },
    {
        "id": "s_ia_immune_activated_best",
        "claim": "S-IA subtype is immune-activated with high CD8 T-cell infiltration, VEGFA overexpression, and IFN-γ/α signaling — best prognosis and ICI candidate.",
        "sources": "Jia et al. 2022 Nat Commun",
    },
    {
        "id": "s_is_tgfb_exhausted",
        "claim": "S-IS subtype is immune-suppressed/exhausted driven by TGF-β, with depleted TCR repertoire (CDR3-low) — poor prognosis despite immune infiltration signatures.",
        "sources": "Jia et al. 2022 Nat Commun",
    },
    {
        "id": "pathology_weak_surrogate",
        "claim": "Histological pathology subtype (Osteoblastic/Fibroblastic/Chondroblastic) is only weakly associated with molecular subtypes — multi-omic integration is required for therapeutic stratification.",
        "sources": "Jia et al. 2022 Nat Commun; benchmark Cramer's V=0.29",
    },
    {
        "id": "mrna_only_misses_hrd_md",
        "claim": "mRNA expression alone cannot fully resolve S-HRD (requires CNA for BRCA2 del) or S-MD (requires CNA for MYC amp); pure transcriptomic clustering conflates these subtypes.",
        "sources": "Jia et al. 2022 Nat Commun",
    },
]
