"""Harness-side episode trace: an event log with a visibility snapshot on every line.

The earlier harness kept only the conversation, so provenance had to be read back out of the
agent's prose. That is unreliable by construction: whether an identity was derived or recalled
cannot be settled from the agent's account of itself. The harness, though, KNOWS what the agent
could see at every step. This module records it as it happens.

Written by the harness, never shown to the agent. One JSON object per line in `events.jsonl`:

    {"seq": 12, "t": 431.2, "step": 9, "kind": "run_code", ..., "vis": {...}}

`step` is the agent's tool-call index (the same number as `call_num` on observations); harness
events that happen before the first call have step 0. `vis` is what the agent could see at that
moment:

    symbols_visible         gene symbols revealed (codebook) yet?
    symbols_step            step at which they were revealed
    label                   None, or {cohort, truth: "true"|"false", step, channel}
    clinical_codebook       clinical codebook injected yet?
    n_real_symbols_seen     distinct real gene symbols that have appeared in tool outputs so far
    markers_seen            {marker symbol: "symbol"|"anon"} lineage markers that have appeared in
                            tool outputs, and in which form they first appeared (anon = as GENE_XXXX,
                            i.e. computed but not yet nameable)

Pivots detected by the harness (no agent cooperation) are `kind: "pivot"` lines with
`source: "harness"`; pivots the agent declares through `record_milestone` are
`kind: "milestone_declared"`: scope, belief, confidence, trigger, cited steps (with a
validity check), plus the prior belief taken from the last observation by the harness.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
import time
from pathlib import Path
from typing import Any

from biodiscoverygym.tasks import TaskAdapter, get_task

_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.\-]*")
_HEADER = re.compile(r"^\s*#\s*CURRENT_HYPOTHESIS:\s*(.+)$", re.MULTILINE)
_CONF_RANK = {"low": 0, "medium": 1, "high": 2}
_SAMPLE_CAP = 25


def _tokens(text: str) -> set[str]:
    return {t.rstrip(".-") for t in _TOKEN.findall(text or "")}


class EpisodeTrace:
    def __init__(self, path: str | Path | None, gene_map: dict[str, str] | None,
                 true_cohort: str | None, planted_cohort: str | None = None,
                 config: dict[str, Any] | None = None, task: TaskAdapter | None = None):
        # Domain knowledge (salient tokens, answer classifier, answer field) comes from the task
        # adapter; the trace itself is task-agnostic. `true_cohort` / `planted_cohort` are the true
        # and delivered answers in the adapter's codes (names kept for log compatibility).
        self.task = task or get_task()
        self.path = Path(path) if path else None
        self._fh = open(self.path, "w") if self.path else None
        self._t0 = time.time()
        self.seq = 0
        self.true_cohort = (true_cohort or "").upper() or None
        self.planted_cohort = (planted_cohort or "").upper() or None

        gene_map = gene_map or {}
        self._symbols = set(gene_map.values())
        sym2anon = {v: k for k, v in gene_map.items()}
        # token -> (marker symbol, form). Markers absent from this cohort's matrix have no anon id.
        self._marker_tokens: dict[str, tuple[str, str]] = {}
        for s in self.task.salient_tokens():
            self._marker_tokens[s] = (s, "symbol")
            if s in sym2anon:
                self._marker_tokens[sym2anon[s]] = (s, "anon")

        self.vis: dict[str, Any] = {
            "symbols_visible": False, "symbols_step": None, "label": None,
            "clinical_codebook": False,
        }
        self.real_symbols_seen: set[str] = set()
        self.markers_seen: dict[str, dict] = {}          # symbol -> {"step", "form"}
        self.run_code_steps: set[int] = set()
        self.milestones: list[dict] = []                 # harness pivots + declared milestones
        self._prev_identity: dict | None = None
        self._text_codes_seen: set[str] = set()
        self.n_observations = 0
        self.n_rejected = 0
        self._last_hypothesis: str | None = None

        self.emit("episode_start", 0, true_cohort=self.true_cohort,
                  planted_cohort=self.planted_cohort,
                  config={**(config or {}), "task": self.task.name})

    # ------------------------------------------------------------------ core
    def snapshot(self) -> dict:
        v = copy.deepcopy(self.vis)
        v["n_real_symbols_seen"] = len(self.real_symbols_seen)
        v["markers_seen"] = {s: d["form"] for s, d in sorted(self.markers_seen.items())}
        return v

    def emit(self, kind: str, step: int, **data) -> dict:
        self.seq += 1
        rec = {"seq": self.seq, "t": round(time.time() - self._t0, 2), "step": step,
               "kind": kind, **data, "vis": self.snapshot()}
        if self._fh:
            self._fh.write(json.dumps(rec, default=str) + "\n")
            self._fh.flush()
        return rec

    # ------------------------------------------------------- what the agent is shown
    def symbols_revealed(self, step: int, channel: str) -> None:
        if not self.vis["symbols_visible"]:
            self.vis["symbols_visible"], self.vis["symbols_step"] = True, step
        self.emit("symbols_revealed", step, channel=channel)

    def label_delivered(self, step: int, cohort: str, channel: str) -> None:
        cohort = (cohort or "").upper()
        truth = "true" if cohort == self.true_cohort else "false"
        self.vis["label"] = {"cohort": cohort, "truth": truth, "step": step, "channel": channel}
        self.emit("label_delivered", step, cohort=cohort, truth=truth, channel=channel)

    def clinical_codebook_injected(self, step: int) -> None:
        self.vis["clinical_codebook"] = True
        self.emit("clinical_codebook_injected", step)

    # ------------------------------------------------------------- agent actions
    def model_turn(self, step: int, *, stop_reason, input_tokens, output_tokens, api_s,
                   retries, refusals, refusal_category, text: str, tool_calls: list[str]) -> None:
        # Cancer names in the agent's visible text, first mention per code. Lower trust than the
        # structured call: a mention can be a hypothesis being ruled out.
        codes = self.task.mentioned_answers(text)
        new = [c for c in codes if c not in self._text_codes_seen]
        self._text_codes_seen.update(new)
        self.emit("model_turn", step, stop_reason=stop_reason, input_tokens=input_tokens,
                  output_tokens=output_tokens, api_s=api_s, retries=retries, refusals=refusals,
                  refusal_category=refusal_category, text_chars=len(text or ""),
                  tool_calls=tool_calls, text_codes=codes)
        for c in new:
            self._pivot(step, "text_mention", source="text", code=c)

    def run_code(self, step: int, code: str, output: str, timing: dict | None) -> None:
        self.run_code_steps.add(step)
        toks = _tokens(output)
        new_syms = sorted((toks & self._symbols) - self.real_symbols_seen)
        self.real_symbols_seen.update(new_syms)
        new_markers = []
        for tok in toks:
            hit = self._marker_tokens.get(tok)
            if hit and hit[0] not in self.markers_seen:
                self.markers_seen[hit[0]] = {"step": step, "form": hit[1]}
                new_markers.append({"marker": hit[0], "form": hit[1]})
        hyp = _HEADER.search(code or "")
        t = timing or {}
        self.emit("run_code", step,
                  code_chars=len(code or ""),
                  code_sha1=hashlib.sha1((code or "").encode()).hexdigest()[:12],
                  current_hypothesis_header=hyp.group(1).strip()[:300] if hyp else None,
                  output_chars=len(output or ""), is_error=t.get("is_error"),
                  timed_out=t.get("timed_out"), exec_s=t.get("exec_time_s"),
                  new_markers=sorted(new_markers, key=lambda m: m["marker"]),
                  n_new_real_symbols=len(new_syms), new_real_symbols_sample=new_syms[:_SAMPLE_CAP])

    def observation(self, step: int, obs: dict) -> dict:
        """Log an observation and return the visibility stamp to attach to it."""
        self.n_observations += 1
        self._last_hypothesis = str(obs.get("current_hypothesis", ""))[:500]
        af = self.task.answer_field
        ident = obs.get(af) if isinstance(obs.get(af), dict) else {}
        call = str(ident.get("call", "") or "")
        cur = {"call": call, "code": self.task.classify_answer(call) if ident else None,
               "confidence": ident.get("confidence"), "basis": ident.get("basis"),
               "evidence_steps": list(ident.get("evidence_steps") or [])}
        stamp = self.snapshot()
        self.emit("observation", step, ordinal=self.n_observations,
                  hypothesis=str(obs.get("current_hypothesis", ""))[:500],
                  confidence=obs.get("confidence"), identity=cur,
                  identity_missing=not ident)
        self._detect_pivots(step, cur)
        return stamp

    def milestone_declared(self, step: int, payload: dict) -> dict:
        cited = [s for s in (payload.get("evidence_steps") or []) if isinstance(s, int)]
        bad = [s for s in cited if s not in self.run_code_steps or s >= step]
        check = {"n_cited": len(cited), "invalid_steps": bad,
                 "valid": bool(cited) and not bad}
        # The prior belief is supplied by the harness, not asked of the agent: the identity call
        # and working hypothesis of the last valid observation before this milestone.
        rec = self.emit("milestone_declared", step,
                        **{k: payload.get(k) for k in
                           ("scope", "belief", "confidence", "trigger", "evidence_steps")},
                        prior_identity=(self._prev_identity or {}).get("call"),
                        prior_identity_code=(self._prev_identity or {}).get("code"),
                        prior_hypothesis=self._last_hypothesis,
                        check=check)
        self.milestones.append({"source": "agent", **rec})
        return check

    def tool_rejected(self, step: int, tool: str, errors: list[str]) -> None:
        """A call that failed validation or a protocol rule (biodiscoverygym/protocol.py). It was
        not recorded; the agent was told why and asked to call again."""
        self.n_rejected += 1
        self.emit("tool_rejected", step, tool=tool, errors=errors)

    def rule_violation_accepted(self, step: int, tool: str, errors: list[str], reason: str) -> None:
        """A violating call accepted anyway so the episode is not lost (grace / forced submit)."""
        self.emit("rule_violation_accepted", step, tool=tool, rule=",".join(
            sorted({e.split(":")[0] for e in errors})), detail=errors, reason=reason)

    def harness_event(self, kind: str, step: int, **data) -> None:
        """Budget warning, forced submit, exam start, submission, exec timeout, ..."""
        self.emit(kind, step, **data)

    # ------------------------------------------------------------------ pivots
    def _pivot(self, step: int, pivot: str, source: str = "harness", **data) -> None:
        rec = self.emit("pivot", step, pivot=pivot, source=source, **data)
        self.milestones.append({"source": source, **rec})

    def _detect_pivots(self, step: int, cur: dict) -> None:
        prev = self._prev_identity
        named = cur["code"] not in (None, "UNDETERMINED")
        prev_named = prev is not None and prev["code"] not in (None, "UNDETERMINED")
        if named and not prev_named and not any(
                m.get("pivot") == "identity_first_named" for m in self.milestones):
            self._pivot(step, "identity_first_named", call=cur["call"], code=cur["code"],
                        confidence=cur["confidence"], basis=cur["basis"])
        elif named and prev_named and cur["code"] != prev["code"]:
            self._pivot(step, "identity_changed", from_code=prev["code"], to_code=cur["code"],
                        from_call=prev["call"], to_call=cur["call"], basis=cur["basis"])
        # Confidence moves only count on an unchanged, named call; a first naming or a change of
        # call is already its own pivot.
        if named and prev_named and cur["code"] == prev["code"] \
                and cur["confidence"] != prev["confidence"] \
                and cur["confidence"] in _CONF_RANK and prev["confidence"] in _CONF_RANK:
            self._pivot(step, "identity_confidence_changed", from_conf=prev["confidence"],
                        to_conf=cur["confidence"], code=cur["code"])
        self._prev_identity = cur

    # ------------------------------------------------------------------- close
    def summary(self) -> dict:
        firsts = {m["pivot"]: m for m in self.milestones if m.get("kind") == "pivot"}
        first_named = firsts.get("identity_first_named")
        return {
            "events_file": self.path.name if self.path else None,
            "n_events": self.seq,
            "n_rejected": self.n_rejected,
            "final_vis": self.snapshot(),
            "identity_first_named": None if not first_named else {
                k: first_named.get(k) for k in ("step", "code", "call", "basis", "confidence")}
                | {"symbols_visible_then": first_named["vis"]["symbols_visible"],
                   "label_then": first_named["vis"]["label"],
                   "markers_seen_then": first_named["vis"]["markers_seen"]},
            "milestones": [{k: m.get(k) for k in ("source", "step", "kind", "pivot",
                                                   "scope", "belief", "confidence", "code",
                                                   "from_code", "to_code", "check")}
                           for m in self.milestones],
        }

    def close(self, step: int, **data) -> dict:
        self.emit("episode_end", step, **data)
        s = self.summary()
        if self._fh:
            self._fh.close()
            self._fh = None
        return s
