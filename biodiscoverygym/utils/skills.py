"""Skill loader — progressive disclosure via an explicit ``consult_skill`` tool.

A "skill" is a directory ``skills/<name>/SKILL.md`` (the Anthropic Agent Skills
canonical layout) whose YAML frontmatter carries ``name`` + ``description`` and whose
body holds a reasoning discipline.

Surfacing model (chosen for benchmark measurement):
  Level 1 (always): the agent's system prompt carries only the skill's name +
    description (the pitch).
  Level 2 (on demand): if — and only if — the agent judges the skill relevant, it
    calls the ``consult_skill`` tool, which returns the SKILL.md body. The body
    enters context only then.

Unlike the spec's filesystem-read mechanism, loading goes through a dedicated tool.
This is a deliberate trade-off: a tool call yields an authoritative, confound-free
signal of whether the agent chose to consult the skill (``_skill_consulted``), which a
filesystem read cannot. The agent still decides; nothing is forced into context.
"""
from __future__ import annotations

from pathlib import Path

import yaml

# Project root is two levels above this file (biodiscoverygym/utils/skills.py)
_ROOT = Path(__file__).parent.parent.parent
_SKILLS_DIR = _ROOT / "skills"

# Tool offered to the agent when a skill is configured. Calling it is the agent's own
# decision; the body is returned on demand, never forced into context. The call itself
# is the measurement signal for "did the agent consult the methodology?".
CONSULT_SKILL_TOOL: dict = {
    "name": "consult_skill",
    "description": (
        "Load the full text of an available reasoning skill (see the 'Available skill' "
        "section of your instructions). Optional — call only if you judge the skill "
        "relevant to this task. Returns the skill's methodology as a string."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "Name of the skill to load (as listed in 'Available skill').",
            }
        },
        "required": ["name"],
    },
}


def resolve(name_or_path: str) -> Path:
    """Resolve a skill reference to its SKILL.md path.

    Accepts an explicit (absolute/relative) path or a bare skill name. Bare names
    resolve to the canonical ``skills/<name>/SKILL.md`` layout, with fallbacks to the
    older flat ``skills/<name>.skill.md`` / ``skills/<name>.md`` forms.
    """
    p = Path(name_or_path)
    if p.is_file():
        return p
    if p.is_dir() and (p / "SKILL.md").is_file():
        return p / "SKILL.md"
    candidates = [
        _SKILLS_DIR / name_or_path / "SKILL.md",   # canonical: skills/<name>/SKILL.md
        _SKILLS_DIR / name_or_path,
        _SKILLS_DIR / f"{name_or_path}.skill.md",   # legacy flat forms
        _SKILLS_DIR / f"{name_or_path}.md",
    ]
    for c in candidates:
        if c.is_file():
            return c
    raise FileNotFoundError(
        f"Skill not found: {name_or_path!r} (looked for an explicit path and under "
        f"{_SKILLS_DIR}/<name>/SKILL.md)"
    )


def _split_frontmatter(text: str) -> tuple[dict, str]:
    """Return (frontmatter_dict, body). Frontmatter is the leading ``---`` block."""
    lines = text.splitlines()
    if lines and lines[0].strip() == "---":
        for i in range(1, len(lines)):
            if lines[i].strip() == "---":
                fm = yaml.safe_load("\n".join(lines[1:i])) or {}
                body = "\n".join(lines[i + 1:]).lstrip("\n")
                return (fm if isinstance(fm, dict) else {}), body
    return {}, text


def load_meta(name_or_path: str) -> dict:
    """Load a skill's frontmatter metadata (name, description, ...)."""
    path = resolve(name_or_path)
    fm, _ = _split_frontmatter(path.read_text())
    if not fm.get("name"):
        # canonical layout → parent dir name; flat layout → stem sans .skill
        fm["name"] = path.parent.name if path.name == "SKILL.md" else path.stem.replace(".skill", "")
    return fm


def load_body(name_or_path: str) -> str:
    """Load a skill's body (frontmatter stripped) — what ``consult_skill`` returns."""
    _, body = _split_frontmatter(resolve(name_or_path).read_text())
    return body.strip()


def skill_pitch(name_or_path: str) -> str:
    """Render the Level-1 pitch: name + description + how to load it.

    This is all the agent sees up front. It must decide on its own whether to call
    ``consult_skill`` to read the full methodology.
    """
    meta = load_meta(name_or_path)
    name = meta.get("name", "")
    desc = " ".join((meta.get("description") or "").split())
    return (
        "\n\n---\n\n"
        "# Available skill\n\n"
        "A reasoning skill is available for this task. You are not required to use it — "
        "read this pitch and decide for yourself whether it would help. If it would, "
        f"call `consult_skill(name=\"{name}\")` to load the full methodology; otherwise "
        "proceed without it.\n\n"
        f"- **{name}** — {desc}\n"
    )
