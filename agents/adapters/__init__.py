"""Provider adapters for the cohort agent — one agent, many providers.

`get_adapter(model)` routes a model id to its provider (claude* -> Anthropic [Sonnet & Opus],
gpt*|o1|o3|o4 -> OpenAI, gemini* -> Google). Each adapter translates the neutral
(Anthropic-shaped) dialect to/from its SDK so the agent loop is identical across models.
"""
from .base import Adapter, Block, Response, get_adapter

__all__ = ["Adapter", "Block", "Response", "get_adapter"]
