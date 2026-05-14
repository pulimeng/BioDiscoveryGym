"""Prompt loader — reads prompt templates from the prompts/ directory."""
from __future__ import annotations

from pathlib import Path

# Project root is two levels above this file (biodiscoverygym/utils/prompts.py)
_PROMPTS_DIR = Path(__file__).parent.parent.parent / "prompts"


def load(name: str) -> str:
    """Load a prompt template by relative path under prompts/.

    Examples:
        load("agent_anon_system.txt")
        load("phases/commit_phase_generic.txt")
    """
    path = _PROMPTS_DIR / name
    if not path.exists():
        raise FileNotFoundError(f"Prompt file not found: {path}")
    return path.read_text()
