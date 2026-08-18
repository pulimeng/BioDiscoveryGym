#!/usr/bin/env python3
"""Panel coverage: how many episodes each judge has judged, per artifact.

The completeness gate for the regeneration. A panel that is 97% complete is not a panel — the
missing 3% are not random, they are the episodes whose traces break a judge, and analysing
around them silently changes the denominator. Print the shortfall, per judge and per artifact,
so "done" is a number rather than an impression.

Usage:  BDG_RUNS=clean python scripts/panel_status.py [--json]
"""
from __future__ import annotations

import glob
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import judges_config as J
import runs_config

BAD = ("scores", "trace", "summary", "codebook", "gene_map", "grouping")


def episodes() -> list[str]:
    out = []
    for d in runs_config.flat():
        for f in sorted(glob.glob(os.path.join(d, '*', 'g[0-3]*_s*.json'))):
            b = os.path.basename(f)
            if all(x not in b for x in BAD) and os.path.basename(os.path.dirname(f)) == b[:-5]:
                out.append(f)
    return out


def main() -> int:
    eps = episodes()
    n = len(eps)
    rows, complete = {}, True
    for kind in ('cot', 'support', 'outcome'):
        rows[kind] = {}
        for tag in [None] + J.tags():
            suf = J.suffix(kind, tag)
            have = sum(1 for e in eps if os.path.exists(e[:-5] + suf))
            rows[kind][tag or J.LEGACY_TAG] = have
            if tag is not None and have != n:
                complete = False

    if '--json' in sys.argv:
        print(json.dumps({'n_episodes': n, 'coverage': rows, 'complete': complete}, indent=2))
        return 0 if complete else 1

    print(f"  episodes: {n}   source: {runs_config.SOURCE}")
    hdr = [J.LEGACY_TAG] + J.tags()
    print(f"  {'artifact':10} " + "".join(f"{h:>13}" for h in hdr))
    for kind, r in rows.items():
        cells = []
        for h in hdr:
            v = r.get(h, 0)
            mark = '' if (h == J.LEGACY_TAG or v == n) else f" (-{n - v})"
            cells.append(f"{str(v) + mark:>13}")
        print(f"  {kind:10} " + "".join(cells))
    print(f"\n  panel complete (all 3 judges x 3 artifacts x {n}): {'YES' if complete else 'NO'}")
    if not complete:
        print("  -> stale files must NOT be removed until this reads YES.", file=sys.stderr)
    return 0 if complete else 1


if __name__ == '__main__':
    sys.exit(main())
