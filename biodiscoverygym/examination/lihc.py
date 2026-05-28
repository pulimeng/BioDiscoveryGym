"""LIHC examination module — evaluator-side canonical expectations."""
from biodiscoverygym.examination.generic import (
    DATA_LOCK_PROMPT,
    QUESTIONS,
    format_data_lock_prompt,
    format_examination_prompt,
)

CANONICAL_EXPECTATIONS: list[dict] = [
    {
        "id": "tp53_proliferative",
        "claim": "TP53 mutations are enriched in the proliferative / poorly-differentiated subtype.",
        "sources": "Boyault 2007; TCGA LIHC 2017",
    },
    {
        "id": "ctnnb1_hepatocyte",
        "claim": "CTNNB1 mutations are enriched in the hepatocyte-like / well-differentiated subtype.",
        "sources": "Zucman-Rossi 2015; TCGA LIHC 2017",
    },
    {
        "id": "tp53_ctnnb1_exclusive",
        "claim": "TP53 and CTNNB1 mutations are largely mutually exclusive across HCC tumors.",
        "sources": "Zucman-Rossi 2015",
    },
    {
        "id": "hepatocyte_better_survival",
        "claim": "The hepatocyte-like / well-differentiated subtype has significantly better overall survival.",
        "sources": "Boyault 2007; TCGA LIHC 2017",
    },
    {
        "id": "progenitor_poor_prognosis",
        "claim": "EpCAM+ / KRT19+ / AFP+ progenitor marker expression is associated with poor, not good, prognosis.",
        "sources": "Hoshida 2009; multiple HCC studies",
    },
]
