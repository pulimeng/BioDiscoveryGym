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

# 4) the AGENT's real tools + real system prompt, ANY — the actual failing config
try:
    sys.path.insert(0, ".")
    from agents.adapters.gemini_adapter import GeminiAdapter
    import agents.cohort_agent as ca
    # gather the module-level tool dicts the agent uses
    tool_dicts = [v for v in vars(ca).values() if isinstance(v, dict) and "input_schema" in v]
    print(f"\n(agent has {len(tool_dicts)} module-level tool dicts: {[d['name'] for d in tool_dicts]})")
    ad = GeminiAdapter()
    gtools = ad._tools(tool_dicts)
    r = client.models.generate_content(model=MODEL, contents="Begin. Inspect the dataset.",
        config=t.GenerateContentConfig(**base, **think, tools=gtools,
            automatic_function_calling=t.AutomaticFunctionCallingConfig(disable=True),
            tool_config=t.ToolConfig(function_calling_config=t.FunctionCallingConfig(mode="ANY"))))
    dump("4. AGENT tools, ANY mode (the real config)", r)
except Exception as e:
    import traceback
    print("\n4. AGENT tools FAILED:", type(e).__name__, str(e)[:400])
    traceback.print_exc()
