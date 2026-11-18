"""Protocol enforcement: one set of rules, applied live by the agent loop and offline by the scorer.

Tool schemas alone are advisory: in the 2026-11-17 v2 smoke run, Sonnet 5.5 omitted the required
`confidence` / `next_experiment` from 2 of 3 submissions, and nothing stopped it. This module is the
harness side of the contract. Plain functions, no service, provider-neutral.

FORM, NOT STRATEGY. Every rule here is about whether a call is well-formed and whether the episode
followed the protocol's bookkeeping. None of them prescribes what analysis to run or when to name a
cancer; the benchmark measures that, so the harness must not dictate it. Rules are identical in every
arm.

Rules
-----
V   validate_input     required fields present, right type / enum, required text non-empty.
R1  min_observations   submit_discovery needs >= MIN_OBS_BEFORE_SUBMIT valid observations.
R2  evidence_steps     every cited step is an earlier run_code call.
R3  gate_counting      only validated observations count toward the reveal gates. Enforced by the
                       agent loop (a rejected observation never increments the counter); checked
                       offline from events.jsonl by `check_events`.

Live, a violating call is REJECTED: it is not recorded, the agent gets the error and is asked to call
again, and a `tool_rejected` event is logged. Two exceptions keep an episode from being lost, and both
log `rule_violation_accepted`: a submission is accepted anyway when <= SUBMIT_GRACE_CALLS calls remain
or after MAX_SUBMIT_REJECTIONS rejected submissions, and the post-budget forced submission is always
accepted.
"""
from __future__ import annotations

from typing import Any, Iterable

# Bump when a rule changes. Stamped into events.jsonl (episode_start.config.protocol); an event log
# without it was recorded before live enforcement and cannot be certified.
PROTOCOL_VERSION = "2026-11-17.1"
MIN_OBS_BEFORE_SUBMIT = 3
SUBMIT_GRACE_CALLS = 2
MAX_SUBMIT_REJECTIONS = 3

# Fields that must be non-empty lists (beyond plain presence).
_NONEMPTY_LISTS = {"submit_discovery": ("top_genes", "pathway_evidence")}
# The parent of record_observation's evidence_steps is the task's answer block; None = resolved at
# call time from the task adapter (cohort_identity: "cancer_identity").
_STEP_FIELDS = {
    "record_observation": (None, "evidence_steps"),
    "record_milestone": ("", "evidence_steps"),     # "" = top level
}


# --------------------------------------------------------------------------- V: schema check
def _as_int(v: Any) -> int | None:
    """Accept ints and integral floats (Gemini returns JSON numbers as floats)."""
    if isinstance(v, bool):
        return None
    if isinstance(v, int):
        return v
    if isinstance(v, float) and v.is_integer():
        return int(v)
    return None


def _check(value: Any, schema: dict, path: str, errors: list[str]) -> Any:
    """Validate `value` against a JSON-schema subset; return it with integral floats normalized."""
    t = schema.get("type")
    if t == "object":
        if not isinstance(value, dict):
            errors.append(f"{path}: must be an object")
            return value
        props = schema.get("properties", {})
        for req in schema.get("required", []):
            if req not in value or value[req] is None:
                errors.append(f"{path + '.' if path else ''}{req}: missing (required)")
        out = dict(value)
        for k, sub in props.items():
            if k in value and value[k] is not None:
                out[k] = _check(value[k], sub, f"{path + '.' if path else ''}{k}", errors)
        return out
    if t == "array":
        if not isinstance(value, list):
            errors.append(f"{path}: must be a list")
            return value
        item = schema.get("items")
        return [_check(v, item, f"{path}[{i}]", errors) for i, v in enumerate(value)] if item else value
    if t == "integer":
        iv = _as_int(value)
        if iv is None:
            errors.append(f"{path}: must be an integer, got {value!r}")
            return value
        return iv
    if t == "string":
        if not isinstance(value, str):
            errors.append(f"{path}: must be a string")
            return value
        if "enum" in schema and value not in schema["enum"]:
            errors.append(f"{path}: must be one of {schema['enum']}, got {value!r}")
        return value
    return value


def _answer_field(answer_field: str | None) -> str:
    if answer_field:
        return answer_field
    from biodiscoverygym.tasks import get_task
    return get_task().answer_field


def validate_input(tool: str, inp: dict, schema: dict,
                   answer_field: str | None = None) -> tuple[dict, list[str]]:
    """V. Returns (normalized input, errors). Required string fields must also be non-empty."""
    errors: list[str] = []
    norm = _check(inp if isinstance(inp, dict) else {}, schema, "", errors)
    if isinstance(norm, dict):
        props = schema.get("properties", {})
        for req in schema.get("required", []):
            v = norm.get(req)
            if props.get(req, {}).get("type") == "string" and isinstance(v, str) and not v.strip():
                errors.append(f"{req}: must not be empty")
        for f in _NONEMPTY_LISTS.get(tool, ()):
            if isinstance(norm.get(f), list) and not norm[f]:
                errors.append(f"{f}: must not be empty")
        af = _answer_field(answer_field)
        ci = norm.get(af)
        if isinstance(ci, dict) and isinstance(ci.get("call"), str) and not ci["call"].strip():
            errors.append(f"{af}.call: must not be empty (use 'undetermined')")
    return norm, errors


# --------------------------------------------------------------------------- R1, R2
def rule_min_observations(n_valid_obs: int) -> list[str]:
    """R1."""
    if n_valid_obs < MIN_OBS_BEFORE_SUBMIT:
        return [f"R1: at least {MIN_OBS_BEFORE_SUBMIT} record_observation checkpoints are required "
                f"before submit_discovery (valid so far: {n_valid_obs})"]
    return []


def rule_evidence_steps(steps: Iterable[Any], run_code_steps: set[int], step: int,
                        field: str = "evidence_steps") -> list[str]:
    """R2. Each cited step must be a run_code call made before `step`."""
    bad = [s for s in steps if _as_int(s) is None or _as_int(s) not in run_code_steps
           or _as_int(s) >= step]
    if bad:
        return [f"R2: {field} {bad} are not earlier run_code call numbers "
                f"(each run_code result starts with '[call N]')"]
    return []


def cited_steps(tool: str, inp: dict, answer_field: str | None = None) -> tuple[str, list]:
    parent, key = _STEP_FIELDS.get(tool, (None, None))
    if key is None:
        return "", []
    if parent is None:
        parent = _answer_field(answer_field)
    src = inp.get(parent) if parent else inp
    steps = (src or {}).get(key) if isinstance(src, dict) else None
    return (f"{parent}.{key}" if parent else key), (steps if isinstance(steps, list) else [])


def live_check(tool: str, inp: dict, schema: dict, *, step: int, run_code_steps: set[int],
               n_valid_obs: int, answer_field: str | None = None) -> tuple[dict, list[str]]:
    """Everything the agent loop enforces for one call: V + R2 (+ R1 for submissions)."""
    norm, errors = validate_input(tool, inp, schema, answer_field)
    field, steps = cited_steps(tool, norm if isinstance(norm, dict) else {}, answer_field)
    if steps:
        errors += rule_evidence_steps(steps, run_code_steps, step, field)
    if tool == "submit_discovery":
        errors += rule_min_observations(n_valid_obs)
    return norm, errors


def rejection_message(tool: str, errors: list[str]) -> str:
    what = {"record_observation": "This observation was NOT recorded and does not count as a "
                                  "checkpoint.",
            "submit_discovery": "The submission was NOT accepted.",
            "record_milestone": "The milestone was NOT recorded."}.get(tool, "The call was rejected.")
    return (f"{tool} rejected. {what} Fix the following and call {tool} again:\n- "
            + "\n- ".join(errors))


# --------------------------------------------------------------------------- offline check
def check_events(events: list[dict]) -> dict:
    """Re-apply R1-R3 to a recorded events.jsonl. Same rule functions as the live path.

    Returns {status: "pass"|"fail"|"incomplete", violations: [...], accepted_violations: [...],
             n_valid_obs, n_rejected}. `accepted_violations` are the logged grace/forced cases:
    reported, not counted as failures.
    """
    if not events:
        return {"status": "incomplete", "violations": ["no events"], "accepted_violations": [],
                "n_valid_obs": 0, "n_rejected": 0}
    cfg = (events[0].get("config") or {}) if events[0].get("kind") == "episode_start" else {}
    from biodiscoverygym.tasks import get_task
    af = get_task(cfg.get("task")).answer_field
    run_code_steps: set[int] = set()
    obs_steps: list[int] = []
    violations: list[str] = []
    accepted = [e for e in events if e["kind"] == "rule_violation_accepted"]
    accepted_steps = {e["step"] for e in accepted}
    for e in events:
        k = e["kind"]
        if k == "run_code":
            run_code_steps.add(e["step"])
        elif k == "observation":
            obs_steps.append(e["step"])
            steps = ((e.get("identity") or {}).get("evidence_steps")) or []
            violations += [f"step {e['step']}: {v}" for v in
                           rule_evidence_steps(steps, run_code_steps, e["step"],
                                               f"{af}.evidence_steps")]
            if e.get("identity_missing"):
                violations.append(f"step {e['step']}: observation recorded without {af}")
        elif k == "milestone_declared":
            violations += [f"step {e['step']}: {v}" for v in
                           rule_evidence_steps(e.get("evidence_steps") or [], run_code_steps,
                                               e["step"])]
        elif k == "submit_discovery" and e["step"] not in accepted_steps:
            violations += [f"step {e['step']}: {v}" for v in rule_min_observations(len(obs_steps))]
    # R3: a reveal on a record_observation must land on the Nth VALID observation.
    gates = []
    if (cfg.get("codebook_gate") or 0) > 0:
        gates.append(("symbols_revealed", cfg["codebook_gate"]))
    if cfg.get("mislead_cohort") and (cfg.get("sample_codebook_ro_gate") or 0) > 0:
        gates.append(("label_delivered", cfg["sample_codebook_ro_gate"]))
    for kind, n in gates:
        hits = [e for e in events if e["kind"] == kind and e.get("channel") == "record_observation"]
        for e in hits:
            want = obs_steps[n - 1] if len(obs_steps) >= n else None
            if e["step"] != want:
                violations.append(f"R3: {kind} at step {e['step']}, but the {n}th valid "
                                  f"observation is at step {want}")
    complete = events[-1].get("kind") == "episode_end"
    status = "incomplete" if not complete else ("fail" if violations else "pass")
    if status == "pass" and not cfg.get("protocol"):
        # Recorded before live validation: submission fields were never checked, so a clean
        # offline result is not a pass.
        status = "pre_protocol"
    return {"status": status, "protocol": cfg.get("protocol"), "violations": violations,
            "accepted_violations": [{"step": e["step"], "rule": e.get("rule"),
                                     "detail": e.get("detail")} for e in accepted],
            "n_valid_obs": len(obs_steps),
            "n_rejected": sum(1 for e in events if e["kind"] == "tool_rejected")}
