"""End-to-end check of the v2 trace + protocol on a REAL staged episode with a SCRIPTED fake model.

No API calls. The real OV cohort is anonymized and staged exactly as in a run; the model is replaced
by an adapter that plays a fixed G3b script (false label BRCA at the 3rd VALID observation) and
deliberately sends four calls the protocol must reject: an observation without cancer_identity (V),
a submission before 3 valid observations (R1), an observation citing a non-existent step (R2), and a
submission missing next_experiment (V). See ScriptedAdapter.script for the call-by-call plan.

Skipped when data/ is absent (it is git-ignored).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

pytestmark = pytest.mark.skipif(not (ROOT / "data").exists(), reason="data/ not present")


def _ro(call, conf, basis, steps, hyp="working model"):
    return {"current_hypothesis": hyp, "evidence_for": ["x"], "evidence_against": [],
            "alternatives_considered": [], "confidence": "medium", "next_action": "continue",
            "cancer_identity": {"call": call, "confidence": conf, "basis": basis,
                                "evidence_steps": steps}}


class ScriptedAdapter:
    provider = "fake"

    def __init__(self, anon):
        from agents.adapters.base import Block, Response
        self.B, self.R = Block, Response
        a = anon  # symbol -> GENE id
        no_ident = _ro("x", "low", "none", [])
        no_ident.pop("cancer_identity")
        submit = {"proposed_grouping": "grouping.json", "top_genes": ["PAX8"],
                  "pathway_evidence": ["HALLMARK_X p=1"], "confidence": "low",
                  "mechanism_hypothesis": "m", "next_experiment": "e"}
        short_submit = {k: v for k, v in submit.items() if k != "next_experiment"}
        self.script = [
            # call: tool, input                                      expected harness response
            ("run_code", {"code": "# WHY: orient\n# EXPECTS: lineage\n# CURRENT_HYPOTHESIS: unknown\n"
                                  f"print(expression.shape); print('{a['PAX8']} {a['WT1']} high')"}),  # 1
            ("record_observation", no_ident),                                  # 2 REJECTED (V)
            ("record_observation", _ro("undetermined", "low", "none", [])),    # 3 valid #1
            ("run_code", {"code": "# WHY: x\n# EXPECTS: y\n# CURRENT_HYPOTHESIS: serous\nprint('ok')"}),  # 4
            ("submit_discovery", submit),                                      # 5 REJECTED (R1)
            ("record_observation", _ro("high-grade serous ovarian carcinoma", "medium",
                                       "computed_markers", [1])),              # 6 valid #2
            ("record_observation", _ro("high-grade serous ovarian carcinoma", "high",
                                       "computed_markers", [99])),             # 7 REJECTED (R2)
            ("record_observation", _ro("high-grade serous ovarian carcinoma", "high",
                                       "computed_markers", [1, 4])),           # 8 valid #3 -> reveals
            ("record_milestone", {"scope": "cancer_identity", "belief": "ovarian, not breast",
                                  "confidence": "high", "trigger": "PAX8/WT1 high",
                                  "evidence_steps": [4]}),                     # 9
            ("run_code", {"code": "# WHY: g\n# EXPECTS: g\n# CURRENT_HYPOTHESIS: g\nimport json\n"
                                  "ids = list(metadata.index)\n"
                                  "json.dump({s: i % 2 for i, s in enumerate(ids)}, "
                                  "open(f'{output_dir}/grouping.json', 'w'))\nprint('PAX8 KRT5 ESR1')"}),  # 10
            ("record_observation", _ro("breast carcinoma", "medium", "provided_information", [10])),  # 11 valid #4
            ("submit_discovery", short_submit),                                # 12 REJECTED (V)
            ("submit_discovery", submit),                                      # 13 accepted
        ]
        self.i = 0

    def create(self, *, messages, **kw):
        assert "effort" in kw  # the agent always sends it for Claude models
        name, inp = self.script[self.i]
        self.i += 1
        blk = self.B(type="tool_use", id=f"t{self.i}", name=name, input=inp)
        txt = self.B(type="text", text="Thinking about ovarian vs other gynecologic origin.")
        return self.R(content=[txt, blk], stop_reason="tool_use",
                      usage=NS(input_tokens=10, output_tokens=5))


def test_trace_g3b_script(tmp_path, monkeypatch):
    import agents.cohort_agent as ca
    from biodiscoverygym.episode import Episode

    ep = Episode.from_cohort(cohort="OV", seed=42, data_dir="data", anonymize_genes=True,
                             rename_clinical=True)
    anon = {v: k for k, v in ep._gene_map.items()}
    monkeypatch.setattr(ca, "get_adapter", lambda model, **kw: ScriptedAdapter(anon))
    agent = ca.CohortAgent(model="claude-sonnet-5-5", max_tool_calls=30, data_dir="data",
                           verbose=False, gene_map=ep._gene_map, codebook_gate=3,
                           mislead_cohort="BRCA", sample_codebook_ro_gate=3,
                           clinical_codebook=ep.dataset.get("clinical_codebook", {}),
                           no_examination=True, cohort="OV", action_based_gate=True)
    result = ep.run(agent, results_base=tmp_path, subdir="g3b_ov_mislead_brca_s42")

    out = next(tmp_path.rglob("events.jsonl"))
    ev = [json.loads(l) for l in out.read_text().splitlines()]
    kinds = [e["kind"] for e in ev]
    by = lambda k: [e for e in ev if e["kind"] == k]

    # rejections: not recorded, reasons logged
    rej = {e["step"]: (e["tool"], e["errors"]) for e in by("tool_rejected")}
    assert sorted(rej) == [2, 5, 7, 12], rej
    assert "cancer_identity" in rej[2][1][0]
    assert rej[5][0] == "submit_discovery" and rej[5][1][0].startswith("R1")
    assert rej[7][1][0].startswith("R2")
    assert "next_experiment" in rej[12][1][0]
    # R3: only valid observations recorded and counted; reveals on the 3rd VALID one (call 8)
    obs = by("observation")
    assert [o["step"] for o in obs] == [3, 6, 8, 11]
    rev, lab = by("symbols_revealed")[0], by("label_delivered")[0]
    assert rev["step"] == 8 and lab["step"] == 8 and lab["truth"] == "false"
    assert obs[2]["vis"]["symbols_visible"] is False and obs[3]["vis"]["label"]["cohort"] == "BRCA"
    assert [o["identity"]["code"] for o in obs] == ["UNDETERMINED", "OV", "OV", "BRCA"]
    # markers first seen anonymized, then by name
    rc = by("run_code")
    assert {m["marker"] for m in rc[0]["new_markers"]} >= {"PAX8", "WT1"}
    assert all(m["form"] == "anon" for m in rc[0]["new_markers"])
    # harness pivots
    piv = {(p["pivot"], p.get("code") or p.get("to_code")) for p in by("pivot") if p["source"] == "harness"}
    assert ("identity_first_named", "OV") in piv and ("identity_changed", "BRCA") in piv
    md = by("milestone_declared")[0]
    assert md["check"]["valid"] is True and md["scope"] == "cancer_identity"
    # the harness supplies the prior belief from the last valid observation (call 8: OV)
    assert md["prior_identity_code"] == "OV" and md["prior_hypothesis"]
    # exactly one accepted submission, at call 13
    assert [e["step"] for e in by("submit_discovery")] == [13]
    assert kinds[-1] == "episode_end"

    # the same rules, offline, on the recorded log
    from biodiscoverygym.protocol import check_events, PROTOCOL_VERSION
    rep = check_events(ev)
    assert rep["status"] == "pass" and rep["n_rejected"] == 4 and rep["n_valid_obs"] == 4, rep
    assert rep["protocol"] == PROTOCOL_VERSION

    tr = [b for m in result.messages if m["role"] == "user" and isinstance(m["content"], list)
          for b in m["content"] if isinstance(b, dict) and b.get("type") == "tool_result"]
    assert str(tr[0]["content"]).startswith("[call 1]\n")
    assert "NOT recorded" in str(tr[1]["content"])
    assert len(result.run_log["rejected_calls"]) == 4
    assert result.discovery.get("next_experiment") == "e"
    assert result.run_log["trace"]["n_rejected"] == 4
