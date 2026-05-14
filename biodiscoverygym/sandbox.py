"""
Network sandbox for agent episodes.

Monkey-patches requests.Session.send to block all outbound HTTP(S) calls
except to an explicit allowlist. Enabled automatically by Evaluator.run().

Blocks subprocess-based bypasses are out of scope — this is designed for
trusted LLM agents (our own baselines), not untrusted third-party code.
"""

from __future__ import annotations

from requests import Session

# Hosts agents are allowed to reach during an episode.
# Add new LLM providers here as needed.
ALLOWED_HOSTS: frozenset[str] = frozenset({
    "api.anthropic.com",       # Claude
    "api.openai.com",          # GPT baselines
    "generativelanguage.googleapis.com",  # Gemini
})

_original_send = Session.send
_active = False


def enable() -> None:
    global _active
    if _active:
        return
    Session.send = _sandboxed_send
    _active = True


def disable() -> None:
    global _active
    if not _active:
        return
    Session.send = _original_send
    _active = False


def is_active() -> bool:
    return _active


def _sandboxed_send(self: Session, request, **kwargs):
    from urllib.parse import urlparse
    host = urlparse(request.url).hostname or ""
    if host not in ALLOWED_HOSTS:
        raise NetworkAccessDenied(
            f"Agent attempted blocked network access: {request.method} {request.url}\n"
            f"Allowed hosts: {sorted(ALLOWED_HOSTS)}"
        )
    return _original_send(self, request, **kwargs)


class NetworkAccessDenied(PermissionError):
    """Raised when an agent tries to reach a non-allowlisted host."""
