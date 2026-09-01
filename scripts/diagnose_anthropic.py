#!/usr/bin/env python3
"""Tell apart the three unrelated faults that all report "credit balance is too low".

Anthropic returns that ONE string for at least three different conditions, so the message cannot
be taken at face value (anthropics/claude-code-action#1224):

  1. balance depletion      — the account really is out of credit
  2. model tier restriction — the model needs a higher usage tier than the account holds
  3. orphaned / stale key   — key authenticates, account is funded, requests still refused;
                              rejected at preflight in <200ms with ZERO tokens billed

They are distinguishable by EXPERIMENT even though the message is identical:

  * every model fails  -> (1) or (3): the account or the key, not the model
  * cheap models pass, Opus fails -> (2): tier gating on that specific model
  * the model is missing from models.list -> (2) as well: the key cannot see it at all

Usage:  source load_keys.sh <keys.txt>
        python scripts/diagnose_anthropic.py
"""
from __future__ import annotations

import os
import sys
import time

LADDER = ["claude-haiku-4-5-20251001", "claude-sonnet-5", "claude-opus-5"]


def main() -> int:
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not key:
        print("ANTHROPIC_API_KEY not set — run: source load_keys.sh <keys.txt>")
        return 1
    print(f"key ...{key[-4:]}  (len {len(key)})")
    print(f"ANTHROPIC_BASE_URL: {os.environ.get('ANTHROPIC_BASE_URL', '<not set — direct>')}\n")

    try:
        import anthropic
    except ImportError:
        print("anthropic SDK missing — conda activate biodiscoverygym")
        return 1
    c = anthropic.Anthropic(api_key=key)

    # What can this key even SEE? A model absent here is tier/permission gated, not a billing fault.
    print("=== models visible to this key ===")
    try:
        visible = [m.id for m in c.models.list(limit=100)]
        for mid in LADDER:
            print(f"  {mid:30} {'visible' if mid in visible else 'NOT VISIBLE  <- tier/permission'}")
    except Exception as e:
        visible = []
        print(f"  models.list failed: {type(e).__name__}: {str(e)[:140]}")

    # One cheap call per model. Cost is a rounding error; the PATTERN is the diagnosis.
    print("\n=== 1-token live call per model ===")
    results = {}
    for mid in LADDER:
        t0 = time.time()
        try:
            c.messages.create(model=mid, max_tokens=4,
                              messages=[{"role": "user", "content": "ok"}])
            results[mid] = "OK"
            print(f"  {mid:30} OK            ({time.time()-t0:.2f}s)")
        except Exception as e:
            msg = str(e)
            kind = ("BALANCE-STRING" if "credit balance" in msg.lower()
                    else type(e).__name__)
            results[mid] = kind
            print(f"  {mid:30} {kind:14} ({time.time()-t0:.2f}s)  {msg[:110]}")

    # WHICH ORG does this key bill to? models.list succeeds even when billing is refused, so its
    # response headers are a working channel to the account identity. Comparing this id against the
    # org shown in the console is the only way to prove "the balance you are looking at is not the
    # balance this key spends" — otherwise it stays a hypothesis and you rotate keys forever.
    print("\n=== which account does this key belong to? ===")
    try:
        raw = c.models.with_raw_response.list(limit=1)
        h = raw.headers
        interesting = [k for k in h.keys()
                       if any(t in k.lower() for t in ("organization", "org", "request-id", "ratelimit-tier"))]
        if interesting:
            for k in sorted(interesting):
                print(f"  {k}: {h.get(k)}")
        else:
            print("  no org/tier headers exposed; headers seen:", ", ".join(sorted(h.keys()))[:300])
    except Exception as e:
        print(f"  could not read headers: {type(e).__name__}: {str(e)[:140]}")

    ok = [m for m, r in results.items() if r == "OK"]
    bad = [m for m, r in results.items() if r != "OK"]
    print("\n=== verdict ===")
    if not bad:
        print("  All models work. The account and key are fine — the earlier failure was transient.")
    elif not ok:
        print("  EVERY model failed -> cause (1) balance or (3) stale key, NOT the model.")
        print("  Even the cheapest model is refused, so nothing about model choice is involved.")
        print()
        print("  IF YOU HAVE MULTIPLE ORGS/WORKSPACES: the console balance you are looking at may")
        print("  belong to a different one than this key. Match the key's last-4 under Settings ->")
        print("  API keys in each org, and create the key in the org that holds the credit.")
        print()
        print("  IF YOU HAVE ONE ORG AND ONE WORKSPACE (rotating keys will NOT help — a new key")
        print("  inherits the same account), the account is funded but not permitted to spend:")
        print("    * Billing -> SPEND LIMIT. Separate from balance. A cap that has been reached")
        print("      refuses every request while the balance still displays in full. This is the")
        print("      best fit for 'it worked yesterday and the balance looks fine'.")
        print("    * Billing history -> did the credit purchase SETTLE? Pending or declined credit")
        print("      can display as balance while being unspendable.")
        print("    * Auto-reload with a failed payment method shows the same way.")
        print("  If all three are clean this is the overloaded-error bug; contact support and quote")
        print("  a request_id from above so they can look up the exact rejection server-side.")
    else:
        print(f"  Cheaper models work ({', '.join(ok)}) but these fail: {', '.join(bad)}")
        print("  -> cause (2) MODEL TIER RESTRICTION. The account is funded and the key is valid;")
        print("     it simply is not entitled to that model. Raise the usage tier (deposit) or run")
        print("     the benchmark on a model the account can reach.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
