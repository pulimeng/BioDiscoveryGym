#!/usr/bin/env python3
"""List the model ids each provider will actually serve, from the provider's own catalogue.

WHY THIS EXISTS. Model ids in this project have twice been chosen by pattern-matching a name that
looked right. `gemini-3.5-pro` reads as the obvious sibling of `gemini-3.5-flash` and does not
exist — the 3.5 generation is Flash-only, and the id 404s. A wrong id is cheap to catch here and
expensive to catch at episode 60 of 95.

Dated notes in docs/ go stale. This asks the provider.

Usage:
    source load_keys.sh <keys.txt>
    python scripts/list_models.py              # every provider whose key is set
    python scripts/list_models.py --pro        # only ids that look like a top-tier/Pro model
    python scripts/list_models.py --provider gemini
"""
from __future__ import annotations

import argparse
import os
import sys


def gemini(pro_only: bool) -> list[str]:
    key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not key:
        return ["  (GEMINI_API_KEY/GOOGLE_API_KEY not set — run: source load_keys.sh)"]
    try:
        from google import genai
    except ImportError:
        return ["  (google-genai not installed in this interpreter — conda activate biodiscoverygym)"]
    out = []
    client = genai.Client(api_key=key)
    for m in client.models.list():
        name = (m.name or "").replace("models/", "")
        actions = getattr(m, "supported_actions", None) or []
        # A model that cannot generateContent is useless for an episode, so say so rather than
        # listing it as if it were a candidate.
        usable = (not actions) or ("generateContent" in actions)
        if pro_only and "pro" not in name.lower():
            continue
        out.append(f"  {name:44} {'' if usable else '(no generateContent)'}")
    return sorted(out) or ["  (no models returned)"]


def anthropic(pro_only: bool) -> list[str]:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return ["  (ANTHROPIC_API_KEY not set)"]
    try:
        import anthropic
    except ImportError:
        return ["  (anthropic not installed in this interpreter)"]
    out = []
    for m in anthropic.Anthropic().models.list(limit=100):
        if pro_only and not any(t in m.id for t in ("opus", "fable")):
            continue
        out.append(f"  {m.id:44} {getattr(m, 'display_name', '')}")
    return sorted(out) or ["  (no models returned)"]


def openai_(pro_only: bool) -> list[str]:
    if not os.environ.get("OPENAI_API_KEY"):
        return ["  (OPENAI_API_KEY not set)"]
    try:
        import openai
    except ImportError:
        return ["  (openai not installed in this interpreter)"]
    ids = [m.id for m in openai.OpenAI().models.list()]
    if pro_only:
        ids = [i for i in ids if i.startswith(("gpt-5", "o")) and "mini" not in i]
    return sorted(f"  {i}" for i in ids) or ["  (no models returned)"]


PROVIDERS = {"gemini": gemini, "anthropic": anthropic, "openai": openai_}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--provider", choices=sorted(PROVIDERS), action="append",
                    help="restrict to one provider (repeatable); default = all")
    ap.add_argument("--pro", action="store_true",
                    help="only top-tier ids (Gemini *pro*, Anthropic opus/fable, GPT-5/o-series)")
    a = ap.parse_args()
    for name in (a.provider or sorted(PROVIDERS)):
        print(f"\n=== {name} ===")
        try:
            for line in PROVIDERS[name](a.pro):
                print(line)
        except Exception as e:
            # Never let one dead provider hide the others.
            print(f"  ERROR: {type(e).__name__}: {str(e)[:160]}")
    print("\nThe id you pass to --model is the bare id, e.g. 'gemini-2.5-pro'.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
