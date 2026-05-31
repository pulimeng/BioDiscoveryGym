"""Generic Examination prompts — used for all cohorts without a cohort-specific module."""
from biodiscoverygym.utils.prompts import load as _load_prompt

DATA_LOCK_PROMPT: str = _load_prompt("examination/data_lock.txt")
Q1_Q3_PROMPT: str = _load_prompt("examination/questions_q1_q3.txt")
Q4_PROMPT: str = _load_prompt("examination/questions_q4.txt")

QUESTIONS: list[dict] = [
    {"id": "Q1", "title": "Survival and Clinical Associations"},
    {"id": "Q2", "title": "Mutation Landscape by Subtype"},
    {"id": "Q3", "title": "Cross-Modal and Within-Subtype Heterogeneity"},
    {"id": "Q4", "title": "Mechanistic Follow-up Experiment"},
]


def format_data_lock_prompt() -> str:
    return DATA_LOCK_PROMPT


def format_q1_q3_prompt() -> str:
    return Q1_Q3_PROMPT


def format_q4_prompt() -> str:
    return Q4_PROMPT


def format_examination_prompt() -> str:
    """Legacy: full Q1-Q4 in one block. Prefer format_q1_q3_prompt + format_q4_prompt."""
    return _load_prompt("examination/questions_generic.txt")
