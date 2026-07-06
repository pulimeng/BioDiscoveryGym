"""OpenAI adapter (Chat Completions tool-calling) — GPT and o-series.

Translates the neutral (Anthropic-shaped) history into OpenAI messages:
  - assistant text+tool_use  -> assistant {content, tool_calls:[function]}
  - a user turn's tool_result -> separate {role:"tool", tool_call_id, content} messages
  - Anthropic tool schema     -> {"type":"function","function":{...,"parameters":schema}}
and maps finish_reason back to the neutral stop_reason.
"""
from __future__ import annotations

import json
from types import SimpleNamespace

from .base import Adapter, Block, Response, iter_blocks

_FINISH = {"tool_calls": "tool_use", "stop": "end_turn", "length": "max_tokens",
           "content_filter": "end_turn"}


class OpenAIAdapter(Adapter):
    provider = "openai"
    max_output_cap = 16384

    def __init__(self, api_key: str | None = None, **kw):
        super().__init__(api_key=api_key, **kw)
        import openai
        self._client = openai.OpenAI(**({"api_key": api_key} if api_key else {}))

    @staticmethod
    def _tools(tools: list[dict]) -> list[dict]:
        return [{"type": "function", "function": {
            "name": t["name"], "description": t.get("description", ""),
            "parameters": t.get("input_schema", {"type": "object", "properties": {}})}}
            for t in tools]

    def _messages(self, system: str, messages: list[dict]) -> list[dict]:
        out = [{"role": "system", "content": system}]
        for msg in messages:
            role, content = msg["role"], msg["content"]
            if role == "assistant":
                text_parts, tool_calls = [], []
                for kind, obj in iter_blocks(content):
                    if kind == "text" and obj.text:
                        text_parts.append(obj.text)
                    elif kind == "tool_use":
                        tool_calls.append({"id": obj.id, "type": "function",
                            "function": {"name": obj.name,
                                         "arguments": json.dumps(obj.input or {})}})
                m = {"role": "assistant", "content": "\n".join(text_parts) or None}
                if tool_calls:
                    m["tool_calls"] = tool_calls
                out.append(m)
            else:  # user turn: may hold tool_results and/or text
                pending_text = []
                for kind, obj in iter_blocks(content):
                    if kind == "tool_result":
                        c = obj.get("content", "")
                        if isinstance(c, list):  # anthropic can nest; flatten to text
                            c = "".join(p.get("text", "") if isinstance(p, dict) else str(p) for p in c)
                        out.append({"role": "tool", "tool_call_id": obj.get("tool_use_id"),
                                    "content": str(c)})
                    elif kind == "text" and obj.text:
                        pending_text.append(obj.text)
                if pending_text:
                    out.append({"role": "user", "content": "\n".join(pending_text)})
        return out

    def create(self, *, model, system, messages, tools, max_tokens, thinking=None) -> Response:
        resp = self._client.chat.completions.create(
            model=model, messages=self._messages(system, messages),
            tools=self._tools(tools), tool_choice="auto",
            max_completion_tokens=min(max_tokens, self.max_output_cap))
        choice = resp.choices[0]
        m = choice.message
        content = []
        if getattr(m, "content", None):
            content.append(Block(type="text", text=m.content))
        for tc in (getattr(m, "tool_calls", None) or []):
            try:
                args = json.loads(tc.function.arguments or "{}")
            except (json.JSONDecodeError, TypeError):
                args = {}
            content.append(Block(type="tool_use", id=tc.id, name=tc.function.name, input=args))
        stop = _FINISH.get(choice.finish_reason, "end_turn")
        if any(b.type == "tool_use" for b in content):
            stop = "tool_use"   # tool calls always take precedence
        u = getattr(resp, "usage", None)
        usage = SimpleNamespace(
            input_tokens=getattr(u, "prompt_tokens", None),
            output_tokens=getattr(u, "completion_tokens", None))
        return Response(content=content, stop_reason=stop, usage=usage)
