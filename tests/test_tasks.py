"""Task adapter split: the cohort adapter is consistent, and a SECOND (toy) adapter runs through core
(trace, protocol, claims) with no change to core. No API, no data."""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
from biodiscoverygym import protocol as P  # noqa: E402
from biodiscoverygym.claims import extract_claims  # noqa: E402
from biodiscoverygym.tasks import TaskAdapter, get_task, register  # noqa: E402
from biodiscoverygym.trace import EpisodeTrace  # noqa: E402


def test_cohort_adapter_consistent():
    t = get_task("cohort_identity")
    assert t.answer_field == "cancer_identity"
    assert t.basis_is_computed("mutation_pattern") and not t.basis_is_computed("provided_information")
    assert t.classify_answer("lung squamous cell carcinoma (not LUAD)") == "LUSC"
    import agents.cohort_agent as ca
    assert ca._RECORD_OBSERVATION_TOOL["input_schema"]["properties"]["cancer_identity"] == t.answer_schema()
    assert ca._RECORD_MILESTONE_TOOL["input_schema"]["properties"]["scope"]["enum"] == list(t.claim_scopes)


class OrganismTask(TaskAdapter):
    """Toy: identify the organism from anonymized sequences. Nothing to do with cancer."""
    name = "toy_organism"
    answer_field = "organism"
    answer_description = "Which organism the reads come from, or 'undetermined'."
    call_description = "Organism name or 'undetermined'."
    basis_values = ("computed_kmers", "prior_knowledge", "provided_information", "none")
    basis_description = "What the call rests on."
    basis_class = {"computed_kmers": "computed_from_data", "prior_knowledge": "prior_knowledge",
                   "provided_information": "provided_information", "none": "none"}
    claim_scopes = ("organism", "contamination")
    answer_codes = ("ECOLI", "YEAST")

    def classify_answer(self, text):
        t = (text or "").lower()
        if not t.strip() or t.startswith("undetermined"):
            return "UNDETERMINED"
        hits = [c for c, k in (("ECOLI", "coli"), ("YEAST", "cerevisiae")) if k in t]
        return hits[0] if len(hits) == 1 else ("AMBIGUOUS" if hits else "OTHER")

    def mentioned_answers(self, text):
        t = (text or "").lower()
        return [c for c, k in (("ECOLI", "coli"), ("YEAST", "cerevisiae")) if k in t]

    def salient_tokens(self):
        return frozenset({"lacZ", "GAL4"})

    def salient_for(self, code):
        return {"ECOLI": ["lacZ"], "YEAST": ["GAL4"]}.get(code, [])


@pytest.fixture(scope="module")
def toy():
    register(OrganismTask)
    return get_task("toy_organism")


def test_toy_adapter_through_core(toy, tmp_path):
    d = tmp_path / "g2_toy_s1"
    d.mkdir()
    tr = EpisodeTrace(d / "events.jsonl", {"GENE_00001": "lacZ"}, true_cohort="ECOLI", task=toy,
                      config={"protocol": P.PROTOCOL_VERSION})
    tr.run_code(1, "print(x)", "GENE_00001 high", {"is_error": False})       # salient token, anon form
    schema = {"type": "object", "properties": {toy.answer_field: toy.answer_schema()},
              "required": [toy.answer_field]}
    obs = {"organism": {"call": "Escherichia coli", "confidence": "high", "basis": "computed_kmers",
                        "evidence_steps": [1]}}
    norm, errs = P.live_check("record_observation", obs, schema, step=2, run_code_steps={1},
                              n_valid_obs=0, answer_field=toy.answer_field)
    assert errs == []
    _, errs = P.live_check("record_observation", {"organism": {**obs["organism"], "evidence_steps": [7]}},
                           schema, step=2, run_code_steps={1}, n_valid_obs=0, answer_field=toy.answer_field)
    assert errs and errs[0].startswith("R2") and "organism.evidence_steps" in errs[0]
    tr.observation(2, norm)
    tr.close(3)
    ev = [json.loads(l) for l in (d / "events.jsonl").read_text().splitlines()]
    assert ev[0]["config"]["task"] == "toy_organism"
    rc = next(e for e in ev if e["kind"] == "run_code")
    assert rc["new_markers"] == [{"marker": "lacZ", "form": "anon"}]
    piv = next(e for e in ev if e["kind"] == "pivot" and e["pivot"] == "identity_first_named")
    assert piv["code"] == "ECOLI"
    assert P.check_events(ev)["violations"] == []
    # claims: the toy task's computed basis is recognised through the core basis classes
    ep = {"model": "fake", "messages": [
        {"role": "assistant", "content": [{"type": "tool_use", "id": "a", "name": "run_code",
                                           "input": {"code": "print(x)"}}]},
        {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "a",
                                      "content": "[call 1]\nGENE_00001 high"}]}]}
    (d / "g2_toy_s1.json").write_text(json.dumps(ep))
    units = extract_claims(d)
    assert len(units) == 1 and units[0]["claim"] == "Escherichia coli" and units[0]["cited"] == [1]
