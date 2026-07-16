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
                        p = t.Part(function_call=t.FunctionCall(
                            name=obj.name, args=obj.input or {}))
                        # echo back the thought_signature Gemini requires (default thinking)
                        if getattr(obj, "signature", None) is not None:
                            try:
                                p.thought_signature = obj.signature
                            except Exception:
                                pass
                        parts.append(p)
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

        # Retry loop handles BOTH: (a) ~1/3 MALFORMED_FUNCTION_CALL -> retry immediately
        # (resampling clears it); (b) transient 503/429 overload -> exponential backoff.
        #
        # Both paths MUST log. They used to swallow the error silently, which made a stalled
        # episode indistinguishable from a slow one: a run parked in the backoff slept 9+ min
        # at 0% CPU while printing nothing, and could only be diagnosed by sampling the
        # process stack. Silence here also hid *which* failure was recurring, so there was
        # nothing to act on.
        #
        # Backoff is capped well below the old 5,10,20,40,80,90,90 (=335s/call): at the
        # ladder's 100 calls/episode that worst case was ~9h for a single episode. Episodes
        # are resume-safe, so failing fast and retrying the episode later beats sleeping
        # through the budget. Override via env if a run needs to ride out a real outage.
        import os
        import sys
        import time
        max_attempts = int(os.environ.get("GEMINI_MAX_ATTEMPTS", "6"))
        cap_s = int(os.environ.get("GEMINI_BACKOFF_CAP_S", "30"))   # 5,10,20,30,30 -> <=95s/call
        cand, parts = None, []
        for attempt in range(max_attempts):
            try:
                resp = self._client.models.generate_content(
                    model=model, contents=contents, config=config)
            except Exception as e:
                msg = str(e)
                transient = any(s in msg for s in (
                    "503", "UNAVAILABLE", "429", "RESOURCE_EXHAUSTED", "overloaded", "high demand"))
                if transient and attempt < max_attempts - 1:
                    delay = min(5 * 2 ** attempt, cap_s)
                    print(f"[gemini] transient error, attempt {attempt + 1}/{max_attempts}, "
                          f"backing off {delay}s: {msg[:200]}", file=sys.stderr, flush=True)
                    time.sleep(delay)
                    continue
                print(f"[gemini] giving up after {attempt + 1} attempt(s) "
                      f"(transient={transient}): {msg[:300]}", file=sys.stderr, flush=True)
                raise
            cand = resp.candidates[0]
            parts = (cand.content.parts if getattr(cand, "content", None) else None) or []
            if parts:
                break
            # Empty parts = MALFORMED_FUNCTION_CALL, a safety block, or a truncated candidate.
            # Resampling usually clears it, so retry immediately — but surface finish_reason,
            # which is the only thing that distinguishes these causes.
            print(f"[gemini] empty response, attempt {attempt + 1}/{max_attempts}, "
                  f"finish_reason={getattr(cand, 'finish_reason', None)} — resampling",
                  file=sys.stderr, flush=True)
        else:
            # All attempts returned empty parts. Previously this fell through silently and the
            # agent received a contentless turn, which reads downstream as the model declining
            # to act rather than as an adapter failure.
            if not parts:
                raise RuntimeError(
                    f"gemini returned no usable parts after {max_attempts} attempts "
                    f"(last finish_reason={getattr(cand, 'finish_reason', None)})")

        content, saw_call = [], False
        for part in parts:
            if getattr(part, "thought", False):
                continue   # reasoning trace (default thinking) — not replayed as content
            if getattr(part, "text", None):
                content.append(Block(type="text", text=part.text))
            fc = getattr(part, "function_call", None)
            if fc is not None:
                saw_call = True
                # id == name so the response round-trips by name; carry the thought_signature
                # so we can echo it back next turn (Gemini requires it at default thinking).
                content.append(Block(type="tool_use", id=fc.name, name=fc.name,
                                     input=dict(fc.args or {}),
                                     signature=getattr(part, "thought_signature", None)))
        fr = str(getattr(cand, "finish_reason", "") or "")
        stop = "tool_use" if saw_call else ("max_tokens" if "MAX_TOKENS" in fr else "end_turn")
        um = getattr(resp, "usage_metadata", None)
        usage = SimpleNamespace(
            input_tokens=getattr(um, "prompt_token_count", None),
            output_tokens=getattr(um, "candidates_token_count", None))
        return Response(content=content, stop_reason=stop, usage=usage)
