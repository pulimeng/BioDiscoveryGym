"""Gemini adapter (google-genai function calling).

Translates the neutral (Anthropic-shaped) history into Gemini `contents`:
  - assistant text+tool_use  -> Content(role="model", parts=[text | function_call])
  - a user turn's tool_result -> Content(role="user", parts=[function_response])
  - Anthropic tool schema     -> FunctionDeclaration(parameters=schema)

Note vs the others: Gemini matches a function_response to its call by NAME, not by an id
(there is no tool_call_id). We therefore carry the tool name as the neutral Block id, so the
round-trip matches on name. Parallel same-name calls in one turn would be ambiguous (rare
here). This adapter is the one to smoke-test first on a live episode.
"""
from __future__ import annotations

from types import SimpleNamespace

from .base import Adapter, Block, Response, iter_blocks


class GeminiAdapter(Adapter):
    provider = "gemini"
    max_output_cap = 65536   # gemini-2.5 max output; agent requests 32k -> uniform across the ladder

    def __init__(self, api_key: str | None = None, **kw):
        super().__init__(api_key=api_key, **kw)
        from google import genai
        self._genai = genai
        from google.genai import types as gtypes
        self._t = gtypes
        self._client = genai.Client(**({"api_key": api_key} if api_key else {}))

    def _tools(self, tools: list[dict]):
        t = self._t
        decls = []
        for tool in tools:
            schema = tool.get("input_schema") or {}
            params = schema if schema.get("properties") else None
            decls.append(t.FunctionDeclaration(
                name=tool["name"], description=tool.get("description", ""),
                parameters=params))
        return [t.Tool(function_declarations=decls)]

    def _contents(self, messages: list[dict]):
        t = self._t
        contents = []
        for msg in messages:
            role, content = msg["role"], msg["content"]
            if role == "assistant":
                parts = []
                for kind, obj in iter_blocks(content):
                    if kind == "text" and obj.text:
                        parts.append(t.Part(text=obj.text))
                    elif kind == "tool_use":
                        parts.append(t.Part(function_call=t.FunctionCall(
                            name=obj.name, args=obj.input or {})))
                if parts:
                    contents.append(t.Content(role="model", parts=parts))
            else:
                parts = []
                for kind, obj in iter_blocks(content):
                    if kind == "tool_result":
                        c = obj.get("content", "")
                        if isinstance(c, list):
                            c = "".join(p.get("text", "") if isinstance(p, dict) else str(p) for p in c)
                        # match by NAME: the neutral id carries the tool name (see module note)
                        parts.append(t.Part.from_function_response(
                            name=obj.get("tool_use_id"), response={"result": str(c)}))
                    elif kind == "text" and obj.text:
                        parts.append(t.Part(text=obj.text))
                if parts:
                    contents.append(t.Content(role="user", parts=parts))
        return contents

    def create(self, *, model, system, messages, tools, max_tokens, thinking=None) -> Response:
        t = self._t
        cfg = dict(
            tools=self._tools(tools),
            max_output_tokens=min(max_tokens, self.max_output_cap),
            automatic_function_calling=t.AutomaticFunctionCallingConfig(disable=True),
            # ANY forces a structured call; AUTO makes 2.5 emit the call as plain 'tool_code'
            # text and measured 0/3 reliable here.
            tool_config=t.ToolConfig(
                function_calling_config=t.FunctionCallingConfig(mode="ANY")),
        )
        # Reasoning policy = DEFAULT / as-deployed (reviewer-proof): don't touch thinking —
        # let the model use its own default adaptive thinking. Only set a budget if one is
        # explicitly requested (thinking != None).
        if thinking and hasattr(t, "ThinkingConfig"):
            cfg["thinking_config"] = t.ThinkingConfig(
                thinking_budget=int(thinking.get("budget_tokens", 0)))
        config = t.GenerateContentConfig(**cfg)

        # Deliver the system prompt as the first USER turn, NOT system_instruction: a long
        # system_instruction reliably triggers MALFORMED_FUNCTION_CALL on Gemini (measured
        # 1/3 vs 2/3 as a user turn). Same prompt text — provider-appropriate delivery only.
        contents = self._contents(messages)
        if system:
            sys_part = t.Part(text=system.rstrip() + "\n\n")
            if contents and contents[0].role == "user":
                contents[0] = t.Content(role="user", parts=[sys_part] + list(contents[0].parts))
            else:
                contents.insert(0, t.Content(role="user", parts=[sys_part]))

        # Even the best config is ~1/3 MALFORMED_FUNCTION_CALL — retry the same request;
        # sampling variation clears it (6 tries -> ~99.9% per turn).
        cand, parts = None, []
        for _ in range(6):
            resp = self._client.models.generate_content(
                model=model, contents=contents, config=config)
            cand = resp.candidates[0]
            parts = (cand.content.parts if getattr(cand, "content", None) else None) or []
            if parts:
                break

        content, saw_call = [], False
        for part in parts:
            if getattr(part, "text", None):
                content.append(Block(type="text", text=part.text))
            fc = getattr(part, "function_call", None)
            if fc is not None:
                saw_call = True
                # id == name so the response round-trips by name
                content.append(Block(type="tool_use", id=fc.name, name=fc.name,
                                     input=dict(fc.args or {})))
        fr = str(getattr(cand, "finish_reason", "") or "")
        stop = "tool_use" if saw_call else ("max_tokens" if "MAX_TOKENS" in fr else "end_turn")
        um = getattr(resp, "usage_metadata", None)
        usage = SimpleNamespace(
            input_tokens=getattr(um, "prompt_token_count", None),
            output_tokens=getattr(um, "candidates_token_count", None))
        return Response(content=content, stop_reason=stop, usage=usage)
