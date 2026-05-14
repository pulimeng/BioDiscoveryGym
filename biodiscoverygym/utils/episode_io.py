"""Helpers for reading and parsing episode log JSON files."""
from __future__ import annotations

import json
from pathlib import Path


def load_episode(path: str | Path) -> dict:
    with open(path) as f:
        return json.load(f)


def extract_commit_phase_report(episode: dict) -> str:
    report = episode.get("discovery", {}).get("commit_phase_report", "")
    if not report:
        raise ValueError("No commit_phase_report found in episode. Was --phase2-commit-phase used?")
    return report


def extract_phase2_answer(episode: dict) -> str:
    """Return the last assistant message that looks like a Phase 2 answer."""
    for m in reversed(episode.get("messages", [])):
        if m.get("role") != "assistant":
            continue
        content = m.get("content", "")
        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    txt = block["text"]
                    if ("Q1" in txt or "Q2" in txt) and len(txt) > 300:
                        return txt
        elif isinstance(content, str) and ("Q1" in content or "Q2" in content) and len(content) > 300:
            return content
    raise ValueError("No Phase 2 answer found in episode messages.")


def parse_judge_json(raw: str) -> dict:
    """Strip markdown code fences and parse JSON from an LLM judge response."""
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    return json.loads(raw)
