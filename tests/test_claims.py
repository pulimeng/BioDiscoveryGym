"""Claim extraction, evidence packs, swap variants, quote verification (biodiscoverygym/claims.py)."""
import glob
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
from biodiscoverygym.claims import (evidence_pack, extract_claims, run_code_steps,  # noqa: E402
                                    swap_evidence, verify_quotes)

EV = "=== run_code call 3 ===\n--- output ---\nTP63   5.05  1.95\nSOX2 mean=4.95 vs 1.91\n"


def test_verify_quotes():
    assert verify_quotes(["SOX2 mean=4.95 vs 1.91"], EV) == (True, [])
    assert verify_quotes(["  tp63   5.05 1.95 "], EV)[0]              # whitespace/case-normalized
    assert verify_quotes(["NKX2-1 high in all samples"], EV)[0] is False  # invented
    assert verify_quotes([], EV)[0] is False                           # must cite something
    assert verify_quotes(["TP63"], EV)[0] is False                     # too short to be evidence


def test_evidence_pack_and_steps():
    ep = {"messages": [
        {"role": "assistant", "content": [{"type": "tool_use", "id": "a", "name": "run_code",
                                           "input": {"code": "print(1)"}}]},
        {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "a", "content": "[call 4]\n1"}]}]}
    rc = run_code_steps(ep)
    assert rc == {4: {"code": "print(1)", "output": "1"}}
    text, found = evidence_pack([4, 9], rc)
    assert found == [4] and "run_code call 4" in text and "call 9" not in text


DIRS = sorted(d for d in glob.glob(str(ROOT / "results/v2/pilot_*/*/g*_s*")) if not d.endswith(".json"))


@pytest.mark.skipif(not DIRS, reason="no v2 episodes on disk")
def test_real_episodes():
    units = [u for d in DIRS for u in extract_claims(d)]
    assert units
    assert len({u["unit_id"] for u in units}) == len(units), "claim unit ids collide"
    assert all(u["claim"].strip() for u in units if u["type"] == "milestone"), "empty milestone claim"
    for u in units:
        assert set(u["cited"]) == set(u["evidence_steps_found"]), u["unit_id"]
        assert u["variant"] == "cited" and u["evidence"]
    u = units[0]
    d = next(d for d in DIRS if Path(d).name == u["episode"])
    s = swap_evidence(u, d)
    if s:
        assert s["variant"] == "swapped" and not (set(s["cited"]) & set(u["cited"]))
        assert all(x < u["step"] for x in s["cited"])
