"""Claim units and evidence packs for the v2 evidence-support judge. Deterministic, no API.

The v2 judge answers ONE narrow question per claim: does the evidence the agent itself cited
support the claim it made? It never reads the whole trace (where ICLR-era judges disagreed).

A claim unit is
    identity   an answer (task adapter's answer block; cohort_identity: cancer_identity) whose
               basis is in the core class computed_from_data and which cites run_code steps
    milestone  a record_milestone belief + trigger, with its cited steps

Its evidence pack is exactly the cited run_code calls (code + output, from the episode messages)
plus one harness fact the judge needs to read the output correctly: whether gene symbols were
visible (before that, genes appear as GENE_XXXX). The supplied label is deliberately NOT given to
the judge: the question is evidence vs claim, and the label would only invite judging the label.

`verify_quotes` is the hallucination guard: the judge must quote the evidence lines its verdict
rests on, and a quote that does not appear verbatim in the pack voids the verdict.
`swap_evidence` builds the sensitivity test: the same claim with its cited steps replaced by other
run_code steps from the same episode, which should NOT support it.
"""
from __future__ import annotations

import hashlib
import json
import random
import re
from pathlib import Path

from biodiscoverygym.tasks import get_task

MAX_STEP_CHARS = 12000          # per cited step (executor output is already capped)
MAX_PACK_CHARS = 40000          # per claim
_CALL_PREFIX = re.compile(r"^\[call (\d+)\]\n")


def _text(c) -> str:
    if isinstance(c, str):
        return c
    if isinstance(c, list):
        return "\n".join(_text(x.get("text", x.get("content", ""))) if isinstance(x, dict) else str(x)
                         for x in c)
    return str(c or "")


def run_code_steps(ep: dict) -> dict[int, dict]:
    """{step: {"code", "output"}} for every run_code call, keyed by the harness's [call N] number."""
    code_by_id, out = {}, {}
    for m in ep.get("messages", []):
        c = m.get("content")
        if not isinstance(c, list):
            continue
        for b in c:
            if not isinstance(b, dict):
                continue
            if m.get("role") == "assistant" and b.get("type") == "tool_use" and b.get("name") == "run_code":
                code_by_id[b.get("id")] = (b.get("input") or {}).get("code", "")
            elif b.get("type") == "tool_result" and b.get("tool_use_id") in code_by_id:
                t = _text(b.get("content"))
                mm = _CALL_PREFIX.match(t)
                if mm:
                    out[int(mm.group(1))] = {"code": code_by_id[b["tool_use_id"]], "output": t[mm.end():]}
    return out


def _clip(s: str, n: int) -> str:
    return s if len(s) <= n else s[:n] + f"\n... [clipped: {len(s)} chars total]"


def evidence_pack(steps: list[int], rc: dict[int, dict]) -> tuple[str, list[int]]:
    """Render the cited steps; returns (text, steps actually found)."""
    parts, found, total = [], [], 0
    for s in steps:
        if s not in rc:
            continue
        block = (f"=== run_code call {s} ===\n--- code ---\n{_clip(rc[s]['code'], 4000)}\n"
                 f"--- output ---\n{_clip(rc[s]['output'], MAX_STEP_CHARS)}\n")
        if total + len(block) > MAX_PACK_CHARS:
            parts.append(f"=== run_code call {s} === [omitted: pack size limit]\n")
            continue
        parts.append(block)
        found.append(s)
        total += len(block)
    return "".join(parts), found


def extract_claims(episode_dir: str | Path) -> list[dict]:
    """All judgeable claim units in one v2 episode."""
    d = Path(episode_dir)
    label = d.name
    ep = json.load(open(d / f"{label}.json"))
    events = [json.loads(l) for l in (d / "events.jsonl").read_text().splitlines() if l.strip()]
    rc = run_code_steps(ep)
    cfg = (events[0].get("config") or {}) if events and events[0]["kind"] == "episode_start" else {}
    task = get_task(cfg.get("task"))          # logs from before the split carry no task: default
    units = []
    for e in events:
        if e["kind"] == "observation":
            ident = e.get("identity") or {}
            if not task.basis_is_computed(ident.get("basis")) or not ident.get("evidence_steps"):
                continue
            claim = {"type": "identity", "claim": ident.get("call", ""), "basis": ident.get("basis"),
                     "confidence": ident.get("confidence"), "cited": list(ident["evidence_steps"])}
        elif e["kind"] == "milestone_declared":
            if not e.get("evidence_steps"):
                continue
            # Pre-2026-11-18 logs (milestone schema before the 5-field version) carry to_state /
            # what / milestone_kind instead of belief / scope.
            claim = {"type": "milestone",
                     "claim": e.get("belief") or e.get("to_state") or e.get("what") or "",
                     "trigger": e.get("trigger", ""),
                     "scope": e.get("scope") or e.get("milestone_kind"), "confidence": e.get("confidence"),
                     "cited": list(e["evidence_steps"])}
        else:
            continue
        pack, found = evidence_pack(claim["cited"], rc)
        claim.update(episode=label, model=ep.get("model"), step=e["step"],
                     symbols_visible=e["vis"]["symbols_visible"], evidence=pack, evidence_steps_found=found,
                     variant="cited")
        # The agent model is part of the id: the same episode label exists in every model's run
        # (g3b_ov_mislead_brca_s123 collided across Sonnet 5 and 5.5 before this).
        claim["unit_id"] = hashlib.sha1(
            f"{ep.get('model')}|{label}|{claim['type']}|{e['step']}|cited".encode()).hexdigest()[:12]
        units.append(claim)
    return units


def swap_evidence(unit: dict, episode_dir: str | Path, seed: int = 0) -> dict | None:
    """Same claim, cited steps replaced by the same number of OTHER run_code steps (not cited, not
    within 1 of a cited step) made before the claim. None if the episode has too few such steps."""
    d = Path(episode_dir)
    ep = json.load(open(d / f"{d.name}.json"))
    rc = run_code_steps(ep)
    near = {s + k for s in unit["cited"] for k in (-1, 0, 1)}
    pool = sorted(s for s in rc if s < unit["step"] and s not in near)
    n = max(1, len(unit["evidence_steps_found"]))
    if len(pool) < n:
        return None
    rnd = random.Random(f"{unit['unit_id']}|{seed}")
    steps = sorted(rnd.sample(pool, n))
    pack, found = evidence_pack(steps, rc)
    return {**unit, "cited": steps, "evidence": pack, "evidence_steps_found": found, "variant": "swapped",
            "unit_id": hashlib.sha1(f"{unit['unit_id']}|swap|{seed}".encode()).hexdigest()[:12],
            "swapped_from": unit["unit_id"]}


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip().lower()


def verify_quotes(quotes: list[str], evidence: str, min_len: int = 8) -> tuple[bool, list[str]]:
    """Every quote must appear verbatim (whitespace- and case-normalized) in the evidence.
    Returns (all_ok, bad_quotes). An empty quote list is NOT ok: a verdict must cite something."""
    ev = _norm(evidence)
    bad = [q for q in quotes if len(_norm(q)) < min_len or _norm(q) not in ev]
    return (bool(quotes) and not bad), bad
