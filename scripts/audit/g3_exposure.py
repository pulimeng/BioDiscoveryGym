"""Was the G3 false label actually delivered to this episode?

WHY THIS MODULE EXISTS. `agents/cohort_agent.py` injects the planted cohort label on a counter of
the agent's own recorded observations:

    if not _sample_codebook_injected and _ro_count >= self.sample_codebook_ro_gate ...

g3b gates on the 3rd observation (v2 g3a delivers it in the first message), and there is NO
call-count fallback. An episode
that submits before its Nth observation never receives a false label at all. The outcome scorer
then records `cohort_identity_verdict != mislead_cohort` — which every report read as "resisted".

Lean episodes log a median of 4 observations against a gate of 5, so on the late-reveal arm only
3/48 lean episodes were ever exposed. Reporting `fooled / n_g3` made a prompt that ENDS EPISODES
EARLIER look like a prompt that RESISTS FALSE PREMISES, at p=6.0e-08. See
`manuscript/EXPLORE_EXPLOIT_PAPER.md` R4/R5 and `paper/analysis/reveal_mechanism.py`.

**A fooled-rate whose denominator is the arm rather than the exposed set is not a rate.** Use
`exposed_g3()` for the denominator in anything that reports one.

Detection reads the trace for the harness's own cohort-naming text, so it reflects what the agent
was actually shown rather than what the arm label implies.
"""
from __future__ import annotations

import os
import re

# The tool_result text the harness emits when it hands over a (real or planted) cohort identity.
# Distinct from the GENE codebook, which names no cohort — conflating the two mis-times everything.
COHORT_REVEAL_PAT = re.compile(
    r"(?:identified the source cohort|sample-identifier mapping|"
    r"sample_codebook[`'\"]*\s+in your Python namespace)", re.I)

_cache: dict[str, bool] = {}


def was_exposed(episode_json_path: str) -> bool:
    """True if the harness named a cohort to the agent during this episode."""
    p = os.path.abspath(episode_json_path)
    if p in _cache:
        return _cache[p]
    try:
        with open(p, encoding='utf-8', errors='ignore') as fh:
            hit = bool(COHORT_REVEAL_PAT.search(fh.read()))
    except OSError:
        hit = False
    _cache[p] = hit
    return hit


def exposed_g3(run_dir: str, labels) -> set[str]:
    """Subset of `labels` (G3 episode ids) whose episode actually received a cohort label."""
    out = set()
    for lab in labels:
        if was_exposed(os.path.join(run_dir, lab, f"{lab}.json")):
            out.add(lab)
    return out


# ---- exact disclosure locator ------------------------------------------------------------------
# `was_exposed` above greps the whole episode file, which also holds the agent's own text, and it
# does not say WHICH cohort was disclosed or WHEN. Both matter: a g3b episode whose label arrived
# at the start would silently be a g3a episode. This locator reads only the
# harness-authored places the sentence can appear and returns where it appeared.
#
# The sentence is agents/cohort_agent._sample_codebook_narrative; keep the two in sync.
# The delivery sentence and its pattern are owned by the task adapter (label_sentence /
# DISCLOSURE_PAT in biodiscoverygym/tasks/cohort_identity.py).
import sys as _sys  # noqa: E402
from pathlib import Path as _Path  # noqa: E402
_ROOT = next(p for p in _Path(__file__).resolve().parents if (p / "setup.py").exists())
_sys.path.insert(0, str(_ROOT))
from biodiscoverygym.tasks.cohort_identity import DISCLOSURE_PAT  # noqa: E402
# gate expected for each arm: 0 = first user message, N = tool_result of the Nth record_observation
# v2 (2026-11-17): g3a moved from RO #3 to the start. ICLR episodes (g3a at RO #3, rebuttal cells
# g3s/g0a/g0s) must be audited with the ICLR-era code, not with this map.
ARM_GATE = {'g3a': 0, 'g3b': 3}


def _text(c):
    if isinstance(c, str):
        return c
    if isinstance(c, list):
        return ' '.join(_text(x.get('text', x.get('content', ''))) if isinstance(x, dict) else str(x)
                        for x in c)
    return str(c or '')


# The harness's rejection reply (biodiscoverygym/protocol.rejection_message). ICLR-era episodes
# never contain it, so their counting is unchanged.
_REJECTED_PREFIX = 'record_observation rejected.'


def _rejected_ro_ids(ep: dict) -> set:
    out = set()
    for m in ep.get('messages', []):
        if m.get('role') != 'user' or not isinstance(m.get('content'), list):
            continue
        for b in m['content']:
            if isinstance(b, dict) and b.get('type') == 'tool_result' \
                    and _text(b.get('content')).startswith(_REJECTED_PREFIX):
                out.add(b.get('tool_use_id'))
    return out


def locate_disclosure(ep: dict) -> list[dict]:
    """Every occurrence of the disclosure sentence in harness-authored text, in order.

    Each item: {code, where: 'start'|'tool_result'|'other_user_text', ro: ordinal of the
    record_observation whose result carried it (None if not an RO result), tool: tool name,
    msg: index into ep['messages']}.
    Assistant turns are never read, so an agent quoting the sentence back is not counted.
    """
    out, names, ro_ord, ro_n = [], {}, {}, 0
    rejected = _rejected_ro_ids(ep)
    for i, m in enumerate(ep.get('messages', [])):
        c, role = m.get('content'), m.get('role')
        if role == 'assistant':
            for b in (c if isinstance(c, list) else []):
                if isinstance(b, dict) and b.get('type') == 'tool_use':
                    names[b.get('id')] = b.get('name')
                    # v2 protocol R3: a rejected observation is not a checkpoint and does not
                    # count toward any gate, so it must not count here either.
                    if b.get('name') == 'record_observation' and b.get('id') not in rejected:
                        ro_n += 1
                        ro_ord[b.get('id')] = ro_n
            continue
        if isinstance(c, str):
            for h in DISCLOSURE_PAT.finditer(c):
                out.append(dict(code=h.group(1), where='start' if i == 0 else 'other_user_text',
                                ro=None, tool=None, msg=i))
            continue
        for b in (c if isinstance(c, list) else []):
            if not isinstance(b, dict):
                continue
            if b.get('type') == 'tool_result':
                tid = b.get('tool_use_id')
                for h in DISCLOSURE_PAT.finditer(_text(b.get('content'))):
                    out.append(dict(code=h.group(1), where='tool_result', ro=ro_ord.get(tid),
                                    tool=names.get(tid), msg=i))
            elif b.get('type') == 'text':
                for h in DISCLOSURE_PAT.finditer(b.get('text', '')):
                    out.append(dict(code=h.group(1), where='start' if i == 0 else 'other_user_text',
                                    ro=None, tool=None, msg=i))
    return out


def check_disclosure(ep: dict, arm: str, expected_code: str) -> tuple[str, list[dict]]:
    """('exposed' | 'unexposed' | 'protocol_error: <why>', occurrences) for a gated arm.

    exposed    exactly one disclosure, naming `expected_code`, at the arm's gate.
    unexposed  no disclosure, and (for RO gates) the episode logged fewer observations than the
               gate, so it ended before the label was due. That is the known lean-prompt
               shortfall, counted, not an error.
    anything else is a protocol error: wrong cohort, wrong moment, repeated, or missing although
    the gate was reached.
    """
    gate = ARM_GATE[arm]
    occ = locate_disclosure(ep)
    if not occ:
        rejected = _rejected_ro_ids(ep)
        n_ro = sum(1 for m in ep.get('messages', []) if m.get('role') == 'assistant'
                   for b in (m.get('content') if isinstance(m.get('content'), list) else [])
                   if isinstance(b, dict) and b.get('type') == 'tool_use'
                   and b.get('name') == 'record_observation' and b.get('id') not in rejected)
        if gate > 0 and n_ro < gate:
            return 'unexposed', occ
        return f'protocol_error: no disclosure although gate {gate} was reached ({n_ro} RO)', occ
    if len(occ) > 1:
        return f'protocol_error: disclosed {len(occ)} times', occ
    o = occ[0]
    if o['code'] != expected_code.upper():
        return f"protocol_error: disclosed {o['code']}, expected {expected_code.upper()}", occ
    if gate == 0 and o['where'] != 'start':
        return f"protocol_error: expected in the first message, found in {o['where']}", occ
    if gate > 0 and not (o['where'] == 'tool_result' and o['tool'] == 'record_observation'
                         and o['ro'] == gate):
        return (f"protocol_error: expected on record_observation #{gate}, found "
                f"{o['where']} / {o['tool']} #{o['ro']}"), occ
    return 'exposed', occ
