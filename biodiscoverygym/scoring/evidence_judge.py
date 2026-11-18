"""v2 evidence-support judge: does the evidence the agent cited support the claim it made?

One narrow question per claim unit (biodiscoverygym/claims.py). The judge sees the claim and exactly
the cited run_code code + output, never the whole trace and never the supplied label. It runs
OFFLINE, after episodes, and is never in the agent loop.

Verdict scale (fixed enum):
    supports          cited output plainly backs the claim
    partly            some of it is backed, a key part (e.g. the specific cancer type) is not shown
    does_not_support  cited output is unrelated or too weak to back the claim
    contradicts       cited output points against the claim

Robustness:
- the judge must quote 1-3 lines of the evidence its verdict rests on; claims.verify_quotes checks
  each one appears verbatim. A failed check gets ONE retry with the bad quotes named; a second
  failure leaves the unit INVALID (no verdict), never a guessed one.
- any API / parse / enum failure is likewise INVALID, recorded with the error; an invalid unit is
  never counted as any verdict (the ICLR-era defect: an error that looked like a result).
"""
from __future__ import annotations

import json
import time

from biodiscoverygym.claims import verify_quotes
from biodiscoverygym.scoring.judge import is_benchmarked_family, openai_client_for
from biodiscoverygym.tasks import get_task

VERDICTS = ("supports", "partly", "does_not_support", "contradicts")
JUDGE_VERSION = "evidence-judge-2026-11-18.1"

# The rubric is core; {domain} and the two examples come from the task adapter.
SYSTEM_TEMPLATE = """You check whether scientific evidence supports a claim. You are given a CLAIM made by an \
analyst about {domain} and the EVIDENCE the analyst cited for it: the exact code they \
ran and the exact output it printed.

Judge only from the evidence shown. Do not use your own knowledge of what a cancer type usually looks \
like to fill gaps, and do not assume what the analyst meant or what other analyses might show. If the \
output does not show it, it is not evidence.

Choose exactly one verdict:
- "supports": the output contains results that, read plainly, back the claim (the markers, mutations \
or statistics needed for the stated conclusion are present and point to it).
- "partly": some of the claim is backed, but a key part is not shown in the output ({partly_example}).
- "does_not_support": the output is unrelated to the claim or too weak to back it.
- "contradicts": the output shows results that point against the claim ({contradicts_example}).

Quote 1 to 3 short lines copied EXACTLY, character for character, from the EVIDENCE that your verdict \
rests on. Quotes that do not appear verbatim in the evidence make your answer invalid.

Reply with JSON only: {{"verdict": "...", "quotes": ["...", "..."], "reason": "one or two sentences"}}"""


def build_system(task) -> str:
    return SYSTEM_TEMPLATE.format(domain=task.judge_domain, partly_example=task.judge_partly_example,
                                  contradicts_example=task.judge_contradicts_example)


SYSTEM = build_system(get_task())   # default task; EvidenceJudge builds its own from its task


def render_user(unit: dict) -> str:
    lines = [f"CLAIM ({unit['type']}): {unit['claim']}"]
    if unit.get("trigger"):
        lines.append(f"Stated trigger: {unit['trigger']}")
    if unit.get("basis"):
        lines.append(f"Stated basis: {unit['basis']}")
    lines.append(f"Gene names were {'visible' if unit['symbols_visible'] else 'NOT yet visible (genes appear as GENE_XXXX ids)'} "
                 "when the claim was made.")
    lines.append("\nEVIDENCE (the run_code calls the analyst cited):\n" + unit["evidence"])
    return "\n".join(lines)


def _parse(text: str) -> tuple[dict | None, str | None]:
    try:
        d = json.loads(text)
    except Exception as e:  # noqa: BLE001
        return None, f"unparseable JSON: {e}"
    if d.get("verdict") not in VERDICTS:
        return None, f"verdict {d.get('verdict')!r} not in {VERDICTS}"
    q = d.get("quotes")
    if not isinstance(q, list) or not all(isinstance(x, str) for x in q) or not 1 <= len(q) <= 3:
        return None, "quotes must be a list of 1-3 strings"
    return d, None


class EvidenceJudge:
    # 16000 = Qwen3.8-Flash's output cap on the judge gateway. It reasons before answering; 6000 truncated
    # 1 of 3 smoke-test calls (finish_reason=length), which is recorded as INVALID, not a verdict.
    def __init__(self, model: str = "AI-Workstation/qwen3.8-flash", client=None, max_tokens: int = 16000,
                 task=None):
        if is_benchmarked_family(model):
            raise ValueError(f"{model} belongs to a benchmarked family; not a neutral judge")
        self.model = model
        self.task = task or get_task()
        self.system = build_system(self.task)
        self.client = client or openai_client_for(model, timeout=300)
        self.max_tokens = max_tokens

    def _call(self, messages: list[dict]) -> str:
        last = None
        for attempt in range(3):
            try:
                r = self.client.chat.completions.create(
                    model=self.model, temperature=0, max_tokens=self.max_tokens,
                    response_format={"type": "json_object"}, messages=messages)
                if r.choices[0].finish_reason == "length":
                    raise RuntimeError("judge output truncated (finish_reason=length)")
                return r.choices[0].message.content or ""
            except Exception as e:  # noqa: BLE001
                last = e
                time.sleep(3 * 2 ** attempt)
        raise RuntimeError(f"judge call failed after 3 attempts: {last}")

    def judge(self, unit: dict) -> dict:
        """Returns a record with status 'ok' (verdict valid, quotes verified) or 'invalid' (+error)."""
        base = {"unit_id": unit["unit_id"], "episode": unit["episode"], "model": unit["model"],
                "type": unit["type"], "step": unit["step"], "variant": unit["variant"],
                "swapped_from": unit.get("swapped_from"), "claim": unit["claim"],
                "judge_model": self.model, "judge_version": JUDGE_VERSION}
        messages = [{"role": "system", "content": self.system}, {"role": "user", "content": render_user(unit)}]
        error = None
        for round_ in range(2):
            try:
                text = self._call(messages)
            except Exception as e:  # noqa: BLE001
                return {**base, "status": "invalid", "error": str(e)}
            d, error = _parse(text)
            if d is not None:
                ok, bad = verify_quotes(d["quotes"], unit["evidence"])
                if ok:
                    return {**base, "status": "ok", "verdict": d["verdict"], "quotes": d["quotes"],
                            "reason": str(d.get("reason", ""))[:600], "retried": round_ == 1}
                error = f"quotes not found verbatim in the evidence: {bad}"
            messages += [{"role": "assistant", "content": text},
                         {"role": "user", "content": f"Your answer was invalid: {error}. Answer again "
                          "with JSON only, quoting lines copied exactly from the EVIDENCE."}]
        return {**base, "status": "invalid", "error": error}
