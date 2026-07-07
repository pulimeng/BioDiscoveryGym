"""Provider-adapter base for the cohort agent.

ONE agent, many providers. The agent speaks a single neutral dialect (Anthropic-shaped
Block objects); each adapter translates that dialect <-> its provider's API. This keeps the
benchmark fair: the prompt, tools, loop, and codebook-reveal timing are identical across
models — only the API glue differs.

Neutral dialect (what the agent holds in `messages`):
  message   = {"role": "user"|"assistant", "content": <str | list of items>}
  item       = Block (assistant turns, from a Response) | tool_result dict | text dict
  Block      = one content block: type in {"text","tool_use","thinking"}
  tool_result dict = {"type":"tool_result","tool_use_id":..., "content": str}

Tools are Anthropic-format dicts: {"name","description","input_schema": {...json schema...}}.
Each adapter converts these to its provider's function/tool schema.

An adapter implements: create(*, model, system, messages, tools, max_tokens, thinking=None)
-> Response, mapping the provider's stop reason to {"end_turn","max_tokens","tool_use"}.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any


@dataclass
class Block:
    """A neutral content block, shaped like an Anthropic content block so the agent loop
    can use `block.type / .name / .id / .input / .text` unchanged across providers."""
    type: str                      # "text" | "tool_use" | "thinking"
    text: str | None = None        # for type == "text"
    id: str | None = None          # for type == "tool_use"
    name: str | None = None        # for type == "tool_use"
    input: dict | None = None      # for type == "tool_use"
    thinking: str | None = None     # for type == "thinking"

    def model_dump(self) -> dict:
        """Anthropic-shaped dict — lets run_episode._serialize_messages persist blocks as
        proper {"type": "tool_use"/"text"/...} dicts (so the trace scorers can read them)."""
        if self.type == "tool_use":
            return {"type": "tool_use", "id": self.id, "name": self.name,
                    "input": self.input or {}}
        if self.type == "thinking":
            return {"type": "thinking", "thinking": self.thinking or ""}
        return {"type": "text", "text": self.text or ""}


@dataclass
class Response:
    content: list[Block]
    stop_reason: str               # normalized: "end_turn" | "max_tokens" | "tool_use"
    usage: SimpleNamespace = field(default_factory=lambda: SimpleNamespace(
        input_tokens=None, output_tokens=None))


class Adapter:
    """Provider adapter interface. Subclasses translate the neutral dialect to/from a
    provider SDK and normalize the response."""

    provider: str = "base"
    max_output_cap: int = 32000    # provider output-token ceiling; create() clamps to this

    def __init__(self, api_key: str | None = None, **kw):
        self.api_key = api_key

    def create(self, *, model: str, system: str, messages: list[dict],
               tools: list[dict], max_tokens: int, thinking: dict | None = None) -> Response:
        raise NotImplementedError


# ---- helpers shared by adapters -------------------------------------------------------

def iter_blocks(content: Any):
    """Yield normalized (kind, obj) for each item in a neutral message `content`.
    kind in {"text","tool_use","tool_result"}; obj is a Block or dict."""
    if isinstance(content, str):
        yield ("text", Block(type="text", text=content))
        return
    for item in content:
        if isinstance(item, Block):
            yield (item.type, item)
        elif isinstance(item, dict):
            t = item.get("type")
            if t == "tool_result":
                yield ("tool_result", item)
            elif t == "tool_use":
                yield ("tool_use", Block(type="tool_use", id=item.get("id"),
                                         name=item.get("name"), input=item.get("input") or {}))
            elif t == "text":
                yield ("text", Block(type="text", text=item.get("text", "")))
            # ignore "thinking" on the way back out
        # unknown items ignored


def get_adapter(model: str, api_key: str | None = None, **kw) -> Adapter:
    """Route a model id to its provider adapter. Claude -> Anthropic (Sonnet & Opus),
    gpt/o-series -> OpenAI, gemini -> Google."""
    m = (model or "").lower()
    is_o_series = len(m) >= 2 and m[0] == "o" and m[1].isdigit()   # o1/o3/o4/o5/… (any)
    if m.startswith("claude") or "claude" in m:
        from .anthropic_adapter import AnthropicAdapter
        return AnthropicAdapter(api_key=api_key, **kw)
    if m.startswith(("gpt", "chatgpt")) or "gpt" in m or is_o_series:
        from .openai_adapter import OpenAIAdapter
        return OpenAIAdapter(api_key=api_key, **kw)
    if m.startswith("gemini") or "gemini" in m:
        from .gemini_adapter import GeminiAdapter
        return GeminiAdapter(api_key=api_key, **kw)
    raise ValueError(f"no provider adapter matches model id {model!r} "
                     "(expected claude* / gpt*|o<n> / gemini*)")
