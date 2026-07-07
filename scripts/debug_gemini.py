#!/usr/bin/env python3
"""Isolate the Gemini function-calling problem. Calls the SDK directly (not through the
agent) with escalating complexity and prints the RAW response — finish_reason, parts,
function_calls, prompt_feedback — which the adapter otherwise swallows.

Usage:  python scripts/debug_gemini.py            # gemini-2.5-flash
        GEMINI_MODEL=gemini-2.5-pro python scripts/debug_gemini.py
Needs GEMINI_API_KEY / GOOGLE_API_KEY in the env (source load_keys.sh first).
"""
import os, sys
from google import genai
from google.genai import types as t

MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
client = genai.Client()


def dump(label, resp):
    print(f"\n===== {label} =====")
    pf = getattr(resp, "prompt_feedback", None)
    print("prompt_feedback:", pf)
    cands = getattr(resp, "candidates", None) or []
    if not cands:
        print("NO CANDIDATES. full resp:", str(resp)[:500]); return
    c = cands[0]
    print("finish_reason:", getattr(c, "finish_reason", None))
    print("finish_message:", getattr(c, "finish_message", None))
    content = getattr(c, "content", None)
    print("content is None:", content is None)
    parts = (getattr(content, "parts", None) or []) if content else []
    print("n parts:", len(parts))
    for i, p in enumerate(parts):
        print(f"  part[{i}] text={getattr(p,'text',None)!r} function_call={getattr(p,'function_call',None)}")
    um = getattr(resp, "usage_metadata", None)
    print("usage:", um)


TOOL_SIMPLE = t.Tool(function_declarations=[t.FunctionDeclaration(
    name="run_code", description="Execute python code.",
    parameters={"type": "object", "properties": {"code": {"type": "string"}}, "required": ["code"]})])

base = dict(max_output_tokens=2048)
think = {}
if hasattr(t, "ThinkingConfig"):
    think = dict(thinking_config=t.ThinkingConfig(thinking_budget=0))

# 1) bare model, no tools — does the model + key + thinking-off even work?
try:
    r = client.models.generate_content(model=MODEL, contents="Say hello in 3 words.",
        config=t.GenerateContentConfig(**base, **think))
    dump("1. bare model, no tools", r)
except Exception as e:
    print("\n1. bare model FAILED:", type(e).__name__, str(e)[:300])

# 2) one simple tool, AUTO
try:
    r = client.models.generate_content(model=MODEL,
        contents="Inspect the data: call run_code with print('hi').",
        config=t.GenerateContentConfig(**base, **think, tools=[TOOL_SIMPLE],
            automatic_function_calling=t.AutomaticFunctionCallingConfig(disable=True)))
    dump("2. one tool, AUTO mode", r)
except Exception as e:
    print("\n2. one tool AUTO FAILED:", type(e).__name__, str(e)[:300])

# 3) one simple tool, ANY (forced)
try:
    r = client.models.generate_content(model=MODEL,
        contents="Inspect the data.",
        config=t.GenerateContentConfig(**base, **think, tools=[TOOL_SIMPLE],
            automatic_function_calling=t.AutomaticFunctionCallingConfig(disable=True),
            tool_config=t.ToolConfig(function_calling_config=t.FunctionCallingConfig(mode="ANY"))))
    dump("3. one tool, ANY mode", r)
except Exception as e:
    print("\n3. one tool ANY FAILED:", type(e).__name__, str(e)[:300])

# 4) the AGENT's REAL tool set (_TOOLS includes run_code + submit_discovery) — and bisect
sys.path.insert(0, ".")
from agents.adapters.gemini_adapter import GeminiAdapter
import agents.cohort_agent as ca
ad = GeminiAdapter()
real_tools = list(ca._TOOLS) + [ca._RECORD_OBSERVATION_TOOL]
print(f"\n(real agent tool set: {[d['name'] for d in real_tools]})")


def try_tools(label, tool_dicts):
    try:
        gtools = ad._tools(tool_dicts)
        r = client.models.generate_content(model=MODEL, contents="Begin. Inspect the dataset.",
            config=t.GenerateContentConfig(**base, **think, tools=gtools,
                automatic_function_calling=t.AutomaticFunctionCallingConfig(disable=True),
                tool_config=t.ToolConfig(function_calling_config=t.FunctionCallingConfig(mode="ANY"))))
        dump(label, r)
    except Exception as e:
        import traceback
        print(f"\n{label} RAISED:", type(e).__name__, str(e)[:400])
        traceback.print_exc()


try_tools("4. FULL real tool set, ANY", real_tools)
# bisect: each tool alone (empty parts here = that schema breaks Gemini)
for td in real_tools:
    try_tools(f"5. ONLY {td['name']}", [td])

# 6) through the ADAPTER's create() — exercises _contents + full config (the real path)
import os.path
def adapter_call(label, system, max_tokens):
    try:
        resp = ad.create(model=MODEL, system=system,
            messages=[{"role": "user",
                       "content": "Begin. Work through each stage in order and show your reasoning."}],
            tools=real_tools, max_tokens=max_tokens)
        print(f"\n===== {label} =====")
        print(f"  stop_reason={resp.stop_reason}  n_blocks={len(resp.content)}")
        for b in resp.content:
            print("   block:", b.type, "|", (b.name or (b.text or '')[:70]))
    except Exception as e:
        import traceback
        print(f"\n{label} RAISED:", type(e).__name__, str(e)[:300]); traceback.print_exc()

sysp = ""
for p in ("prompts/agent_system_tcga.txt", "prompts/agent_system.txt"):
    if os.path.exists(p):
        sysp = open(p).read(); print(f"\n(loaded {p}: {len(sysp)} chars)"); break
adapter_call("6a. adapter.create + real system prompt, max_tokens=32000", sysp, 32000)
adapter_call("6b. adapter.create + NO system prompt,   max_tokens=32000", "", 32000)
adapter_call("6c. adapter.create + real system prompt, max_tokens=2048", sysp, 2048)

# 7) WHY is 6a empty? raw dump at descending max_output to find the finish_reason + threshold
gtools = ad._tools(real_tools)
def raw_sys(label, max_out):
    cfg = dict(system_instruction=sysp, tools=gtools, max_output_tokens=max_out,
        automatic_function_calling=t.AutomaticFunctionCallingConfig(disable=True),
        tool_config=t.ToolConfig(function_calling_config=t.FunctionCallingConfig(mode="ANY")))
    if hasattr(t, "ThinkingConfig"):
        cfg["thinking_config"] = t.ThinkingConfig(thinking_budget=0)
    try:
        r = client.models.generate_content(model=MODEL,
            contents="Begin. Work through each stage in order and show your reasoning.",
            config=t.GenerateContentConfig(**cfg))
        dump(label, r)
    except Exception as e:
        print(f"\n{label} RAISED:", type(e).__name__, str(e)[:300])
for mo in (32000, 16000, 8192):
    raw_sys(f"7. RAW real-prompt config, max_output={mo}", mo)
