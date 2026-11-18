"""Compatibility shim: the cohort vocabulary now lives in the cohort_identity task adapter.

Import from biodiscoverygym.tasks (get_task) in new code. Kept so older scripts and tests run.
"""
from biodiscoverygym.tasks.cohort_identity import (  # noqa: F401
    ALL_MARKERS, COHORT_CODES, LINEAGE_MARKERS, classify_call, mentioned_codes,
)
