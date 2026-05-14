"""Generic Phase 2 questions — used for cohorts without a cohort-specific phases module."""
from biodiscoverygym.utils.prompts import load as _load_prompt

COMMIT_PHASE_PROMPT: str = _load_prompt("phases/commit_phase_generic.txt")

QUESTIONS: list[dict] = [
    {"id": "Q1", "title": "Survival and Clinical Associations"},
    {"id": "Q2", "title": "Mutation Landscape by Subtype"},
    {"id": "Q3", "title": "Cross-Modal and Within-Subtype Heterogeneity"},
    {"id": "Q4", "title": "Mechanistic Follow-up Experiment"},
]


def format_commit_phase_prompt() -> str:
    return COMMIT_PHASE_PROMPT


def format_phase2_prompt() -> str:
    return _load_prompt("phases/phase2_generic.txt")
