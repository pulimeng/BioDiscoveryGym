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
    max_output_cap = 8192

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
        config = t.GenerateContentConfig(
            system_instruction=system,
            tools=self._tools(tools),
            max_output_tokens=min(max_tokens, self.max_output_cap),
            automatic_function_calling=t.AutomaticFunctionCallingConfig(disable=True),
        )
        resp = self._client.models.generate_content(
            model=model, contents=self._contents(messages), config=config)

        cand = resp.candidates[0]
        content, saw_call = [], False
        for part in (cand.content.parts or []):
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
