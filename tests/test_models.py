"""Model roster + Anthropic request shape (no API calls: the SDK client is faked)."""
import sys, types, inspect
sys.path.insert(0, str(__import__('pathlib').Path(__file__).parent.parent))
from types import SimpleNamespace as NS
from agents.adapters.anthropic_adapter import AnthropicAdapter
from agents.adapters.openai_adapter import OpenAIAdapter
from agents.adapters.gemini_adapter import GeminiAdapter
from biodiscoverygym.models import ROSTER, DEFAULT_AGENT_MODEL, DEFAULT_EFFORT, BY_ID
from agents.adapters.base import get_adapter

def test_models_and_request_shape():
    sent = {}
    class FakeStream:
        def __init__(self, msg): self.msg = msg
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def get_final_message(self): return self.msg
    def make(msg):
        a = AnthropicAdapter.__new__(AnthropicAdapter)
        a._client = NS(messages=NS(stream=lambda **kw: (sent.update(kw), FakeStream(msg))[1]))
        return a

    ok = NS(content=[NS(type="text", text="hi")], stop_reason="end_turn", usage=NS(input_tokens=1, output_tokens=1), stop_details=None)
    r = make(ok).create(model="claude-opus-5-5", system="s", messages=[{"role":"user","content":"x"}], tools=[], max_tokens=32000, effort="high")
    assert sent["output_config"] == {"effort": "high"}, sent
    assert "thinking" not in sent and "fallbacks" not in sent and "tool_choice" not in sent
    assert r.refusal_category is None
    ref = NS(content=[], stop_reason="refusal", usage=NS(input_tokens=1, output_tokens=0), stop_details=NS(category="reasoning_extraction", explanation=""))
    assert make(ref).create(model="claude-opus-5-5", system="s", messages=[], tools=[], max_tokens=10).refusal_category == "reasoning_extraction"
    sent.clear(); make(ok).create(model="claude-sonnet-5-5", system="s", messages=[], tools=[], max_tokens=10)
    assert "output_config" not in sent  # effort=None -> nothing sent

    for cls in (OpenAIAdapter, GeminiAdapter):
        assert "effort" in inspect.signature(cls.create).parameters, cls
    for m in ROSTER:
        assert get_adapter.__code__  # routing below
        prov = type(get_adapter(m.model_id, api_key="x")).__name__.replace("Adapter","").lower()
        assert prov == m.provider, (m.model_id, prov)
    assert DEFAULT_AGENT_MODEL in BY_ID and BY_ID[DEFAULT_AGENT_MODEL].verified

    import agents.cohort_agent as ca
    sig = inspect.signature(ca.CohortAgent.__init__).parameters
    assert sig["model"].default == DEFAULT_AGENT_MODEL and sig["effort"].default == DEFAULT_EFFORT
    assert "thinking_budget" not in sig



def test_classify_call():
    from biodiscoverygym.cohorts import classify_call
    cases = {
        "high-grade serous ovarian carcinoma (contradicts supplied BRCA label)": "OV",
        "breast cancer (supplied label)": "BRCA",
        "undetermined": "UNDETERMINED",
        "lung squamous cell carcinoma": "LUSC",
        "ovarian vs endometrial carcinoma": "AMBIGUOUS",
        "melanoma": "OTHER",
        "(BRCA?)": "BRCA",
        # verbatim from the v2 smoke runs
        "High-grade serous ovarian carcinoma (TCGA-OV-like), contradicting supplied BRCA label": "OV",
        "high-grade serous ovarian carcinoma (TCGA-OV-like); supplied BRCA label not supported": "OV",
        "possibly high-grade serous ovarian carcinoma": "OV",
        "breast invasive carcinoma": "BRCA",
        "likely ovarian, not breast": "OV",
        "ovarian or endometrial carcinoma": "AMBIGUOUS",
    }
    for call, want in cases.items():
        assert classify_call(call) == want, (call, classify_call(call))
