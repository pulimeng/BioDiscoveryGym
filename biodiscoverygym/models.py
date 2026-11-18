"""Model roster for v2 runs: the one place that names agent models and their defaults.

Model ids were scattered as string literals (agent, CLI, launcher, evaluator), so the default stayed
`claude-sonnet-4-6` for months after every real run passed `--model claude-opus-5` / `claude-sonnet-5`.
Change ids here.

`verified` means the id was checked against the provider's own catalogue or docs on `verified_on`.
An unverified entry is a placeholder: confirm it with `python scripts/tools/list_models.py --provider <p>`
before launching, because a wrong id fails only at the first API call of the first episode.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AgentModel:
    stem: str          # short name used in run dirs, e.g. results/v2/<tag>/<stem>/
    model_id: str      # exact id passed to the provider
    label: str         # display name
    provider: str      # anthropic | openai | gemini (must match agents/adapters routing)
    verified: bool
    verified_on: str | None = None
    note: str = ""


ROSTER: list[AgentModel] = [
    AgentModel("opus55", "claude-opus-5-5", "Claude Opus 5.5", "anthropic", True, "2026-11-17",
               "default effort is medium on this model; the harness sets it explicitly (DEFAULT_EFFORT)"),
    AgentModel("sonnet55", "claude-sonnet-5-5", "Claude Sonnet 5.5", "anthropic", True, "2026-11-17"),
    AgentModel("haiku55", "claude-haiku-5-5", "Claude Haiku 5.5", "anthropic", True, "2026-11-17",
               "cheap pipeline checks only; not a benchmark arm"),
    # Non-Anthropic entries are the ids of the ICLR ladder, kept until the current ones are
    # confirmed from the provider catalogue (2026-11-17 web search was inconclusive for both).
    AgentModel("gpt55", "gpt-5.5", "GPT-5.5", "openai", False, None,
               "ICLR-era id; check list_models.py for the current flagship"),
    AgentModel("gemini25pro", "gemini-2.5-pro", "Gemini 2.5 Pro", "gemini", False, None,
               "ICLR-era id; check list_models.py for the current Pro model"),
]

BY_ID = {m.model_id: m for m in ROSTER}
BY_STEM = {m.stem: m for m in ROSTER}

# Development default: Sonnet for dev, Opus for final runs (project cost rule).
DEFAULT_AGENT_MODEL = "claude-sonnet-5-5"

# Anthropic `output_config.effort`, sent on every Claude request. Explicit because the default
# moved: Claude Opus 5 and Sonnet 5 defaulted to "high", Claude Opus 5.5 defaults to "medium".
# Leaving it unset would silently give one model less reasoning than another.
DEFAULT_EFFORT = "high"
EFFORT_LEVELS = ("low", "medium", "high", "xhigh", "max")
