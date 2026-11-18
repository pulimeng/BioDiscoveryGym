"""Evidence judge validation logic with a fake client (no API)."""
import json
import sys
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
from biodiscoverygym.scoring.evidence_judge import EvidenceJudge  # noqa: E402

UNIT = {"unit_id": "u1", "episode": "g3a_x_s1", "model": "m", "type": "identity", "step": 9,
        "variant": "cited", "claim": "lung squamous cell carcinoma", "basis": "computed_markers",
        "symbols_visible": True,
        "evidence": "=== run_code call 3 ===\n--- output ---\nTP63 major=5.05 minor=1.95\nNKX2-1 major=1.2 minor=4.5\n"}


class Fake:
    def __init__(self, replies):
        self.replies, self.calls = list(replies), 0
        self.chat = NS(completions=NS(create=self.create))

    def create(self, **kw):
        self.calls += 1
        r = self.replies.pop(0)
        if isinstance(r, Exception):
            raise r
        return NS(choices=[NS(finish_reason="stop", message=NS(content=json.dumps(r)))])


def J(replies):
    j = EvidenceJudge("AI-Workstation/qwen3.8-flash", client=Fake(replies))
    return j


def test_ok():
    r = J([{"verdict": "supports", "quotes": ["TP63 major=5.05 minor=1.95"], "reason": "x"}]).judge(UNIT)
    assert r["status"] == "ok" and r["verdict"] == "supports" and not r["retried"]


def test_invented_quote_then_fixed():
    r = J([{"verdict": "supports", "quotes": ["TP63 high in every sample"], "reason": "x"},
           {"verdict": "supports", "quotes": ["NKX2-1 major=1.2 minor=4.5"], "reason": "x"}]).judge(UNIT)
    assert r["status"] == "ok" and r["retried"]


def test_invented_quote_twice_is_invalid():
    bad = {"verdict": "contradicts", "quotes": ["SOX2 is 99"], "reason": "x"}
    r = J([bad, bad]).judge(UNIT)
    assert r["status"] == "invalid" and "verdict" not in r and "not found verbatim" in r["error"]


def test_bad_enum_and_api_error(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda *_: None)
    r = J([{"verdict": "maybe", "quotes": ["TP63 major=5.05 minor=1.95"]},
           {"verdict": "maybe", "quotes": ["TP63 major=5.05 minor=1.95"]}]).judge(UNIT)
    assert r["status"] == "invalid" and "not in" in r["error"]
    r = J([RuntimeError("503")] * 3).judge(UNIT)
    assert r["status"] == "invalid" and "503" in r["error"] and "verdict" not in r


def test_refuses_benchmarked_judge():
    with pytest.raises(ValueError):
        EvidenceJudge("AI-Workstation/gpt-oss-120b", client=Fake([]))
