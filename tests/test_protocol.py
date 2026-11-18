"""Protocol rules (biodiscoverygym/protocol.py): validator, R1-R3, offline check. No API, no data."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from agents.cohort_agent import _RECORD_OBSERVATION_TOOL, _SUBMIT_SCHEMA  # noqa: E402
from biodiscoverygym import protocol as P  # noqa: E402

OBS = _RECORD_OBSERVATION_TOOL["input_schema"]


def _obs(**ident):
    base = {"current_hypothesis": "h", "evidence_for": [], "evidence_against": [],
            "alternatives_considered": [], "confidence": "low", "next_action": "n",
            "cancer_identity": {"call": "undetermined", "confidence": "low", "basis": "none",
                                "evidence_steps": []}}
    base["cancer_identity"].update(ident)
    return base


def test_validator():
    _, e = P.live_check("record_observation", _obs(), OBS, step=3, run_code_steps={1}, n_valid_obs=0)
    assert e == []
    # Gemini-style integral floats are accepted and normalized
    norm, e = P.live_check("record_observation", _obs(evidence_steps=[1.0]), OBS, step=3,
                           run_code_steps={1}, n_valid_obs=0)
    assert e == [] and norm["cancer_identity"]["evidence_steps"] == [1]
    _, e = P.live_check("record_observation", _obs(basis="vibes"), OBS, step=3, run_code_steps={1}, n_valid_obs=0)
    assert any("basis" in x and "one of" in x for x in e)
    _, e = P.live_check("record_observation", _obs(call="  "), OBS, step=3, run_code_steps={1}, n_valid_obs=0)
    assert any("undetermined" in x for x in e)
    _, e = P.live_check("record_observation", _obs(evidence_steps=[2]), OBS, step=3,
                        run_code_steps={1}, n_valid_obs=0)          # 2 is not a run_code call
    assert e and e[0].startswith("R2")
    _, e = P.live_check("record_observation", _obs(evidence_steps=[5]), OBS, step=3,
                        run_code_steps={1, 5}, n_valid_obs=0)       # cites the future
    assert e and e[0].startswith("R2")
    sub = {"proposed_grouping": "g.json", "top_genes": [], "pathway_evidence": ["p"],
           "mechanism_hypothesis": "m", "confidence": "low", "next_experiment": "e"}
    _, e = P.live_check("submit_discovery", sub, _SUBMIT_SCHEMA, step=9, run_code_steps=set(), n_valid_obs=3)
    assert e == ["top_genes: must not be empty"]
    sub["top_genes"] = ["A"]
    _, e = P.live_check("submit_discovery", sub, _SUBMIT_SCHEMA, step=9, run_code_steps=set(), n_valid_obs=2)
    assert len(e) == 1 and e[0].startswith("R1")
    assert "NOT accepted" in P.rejection_message("submit_discovery", e)


def _ev(seq, step, kind, **kw):
    return {"seq": seq, "step": step, "kind": kind, **kw}


def test_check_events():
    cfg = {"codebook_gate": 3, "mislead_cohort": "BRCA", "sample_codebook_ro_gate": 3,
           "protocol": P.PROTOCOL_VERSION}
    good = [_ev(1, 0, "episode_start", config=cfg), _ev(2, 1, "run_code"),
            _ev(3, 2, "observation", identity={"evidence_steps": [1]}),
            _ev(4, 3, "observation", identity={"evidence_steps": []}),
            _ev(5, 4, "observation", identity={"evidence_steps": [1]}),
            _ev(6, 4, "symbols_revealed", channel="record_observation"),
            _ev(7, 4, "label_delivered", channel="record_observation"),
            _ev(8, 5, "submit_discovery"), _ev(9, 5, "episode_end")]
    assert P.check_events(good)["status"] == "pass"
    # R3: reveal fired on the 2nd valid observation
    bad = [dict(e) for e in good]
    bad[5]["step"] = 3
    r = P.check_events(bad)
    assert r["status"] == "fail" and any(v.startswith("R3") for v in r["violations"])
    # R1 offline: submission after 2 observations, not accepted as a grace case
    r1 = good[:3] + good[3:4] + [_ev(8, 5, "submit_discovery"), _ev(9, 5, "episode_end")]
    assert any("R1" in v for v in P.check_events(r1)["violations"])
    # ... but a logged grace acceptance is reported, not failed
    graced = r1[:-1] + [_ev(10, 5, "rule_violation_accepted", rule="R1", detail=["R1: ..."]), r1[-1]]
    g = P.check_events(graced)
    assert g["status"] == "pass" and g["accepted_violations"]
    # no episode_end -> incomplete; no protocol stamp -> pre_protocol
    assert P.check_events(good[:-1])["status"] == "incomplete"
    old = [dict(good[0], config={k: v for k, v in cfg.items() if k != "protocol"})] + good[1:]
    assert P.check_events(old)["status"] == "pre_protocol"
