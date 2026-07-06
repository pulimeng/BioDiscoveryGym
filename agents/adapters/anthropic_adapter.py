"""Anthropic adapter — serves both Sonnet and Opus (differ only by model id).

Near pass-through: the neutral dialect IS Anthropic-shaped, so translation is trivial.
"""
from __future__ import annotations

from types import SimpleNamespace

from .base import Adapter, Block, Response, iter_blocks


class AnthropicAdapter(Adapter):
    provider = "anthropic"
    max_output_cap = 64000

    def __init__(self, api_key: str | None = None, **kw):
        super().__init__(api_key=api_key, **kw)
        import anthropic, httpx
        self._client = anthropic.Anthropic(
            timeout=httpx.Timeout(connect=30, read=600, write=30, pool=30),
            **({"api_key": api_key} if api_key else {}))

    def _to_messages(self, messages: list[dict]) -> list[dict]:
        out = []
        for msg in messages:
            content = msg["content"]
            if isinstance(content, str):
                out.append({"role": msg["role"], "content": content})
                continue
            blocks = []
            for kind, obj in iter_blocks(content):
                if kind == "text":
                    blocks.append({"type": "text", "text": obj.text or ""})
                elif kind == "tool_use":
                    blocks.append({"type": "tool_use", "id": obj.id,
                                   "name": obj.name, "input": obj.input or {}})
                elif kind == "tool_result":
                    blocks.append(obj)  # already {"type":"tool_result","tool_use_id",...}
                # thinking blocks are dropped (thinking standardized off for the ladder)
            out.append({"role": msg["role"], "content": blocks})
        return out

    def create(self, *, model, system, messages, tools, max_tokens, thinking=None) -> Response:
        kwargs = dict(model=model, system=system, tools=tools,
                      max_tokens=min(max_tokens, self.max_output_cap),
                      messages=self._to_messages(messages))
        if thinking:
            kwargs["thinking"] = thinking
        with self._client.messages.stream(**kwargs) as stream:
            msg = stream.get_final_message()

        content = []
        for b in msg.content:
            t = getattr(b, "type", None)
            if t == "text":
                content.append(Block(type="text", text=b.text))
            elif t == "tool_use":
                content.append(Block(type="tool_use", id=b.id, name=b.name, input=dict(b.input)))
            elif t in ("thinking", "redacted_thinking"):
                content.append(Block(type="thinking", thinking=getattr(b, "thinking", None)))
        u = getattr(msg, "usage", None)
        usage = SimpleNamespace(
            input_tokens=getattr(u, "input_tokens", None),
            output_tokens=getattr(u, "output_tokens", None))
        return Response(content=content, stop_reason=msg.stop_reason, usage=usage)
