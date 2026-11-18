"""Task adapters. Core code gets the active adapter with get_task(name)."""
from __future__ import annotations

from biodiscoverygym.tasks.base import AMBIGUOUS, OTHER, SENTINELS, UNDETERMINED, TaskAdapter

DEFAULT_TASK = "cohort_identity"
_REGISTRY: dict[str, type[TaskAdapter]] = {}


def register(cls: type[TaskAdapter]) -> type[TaskAdapter]:
    _REGISTRY[cls.name] = cls
    return cls


def get_task(name: str | None = None) -> TaskAdapter:
    name = name or DEFAULT_TASK
    if name not in _REGISTRY:
        raise KeyError(f"unknown task {name!r}; registered: {sorted(_REGISTRY)}")
    t = _REGISTRY[name]()
    t.check()
    return t


from biodiscoverygym.tasks.cohort_identity import CohortIdentityTask  # noqa: E402

register(CohortIdentityTask)

__all__ = ["TaskAdapter", "get_task", "register", "DEFAULT_TASK", "UNDETERMINED", "AMBIGUOUS",
           "OTHER", "SENTINELS"]
