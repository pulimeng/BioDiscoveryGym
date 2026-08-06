#!/usr/bin/env python3
"""Assert the CoT judge sees the SAME KIND of reasoning channel for every model.

WHY THIS IS A GATE, NOT A REPORT
--------------------------------
The derived-vs-recalled labels are the paper's instrument, and they come from an LLM judging a
rendered trace. If that trace contains a reasoning channel for one model and not another, the
judge is reading more of one arm than another and every cross-model derivation comparison is
confounded — silently, because the labels still look like labels.

Today the traces are symmetric for a specific reason: extended thinking is OFF
(`--thinking-budget` defaults to 0 and no runner passes it), so Anthropic persists thinking
blocks with empty text, OpenAI persists none, and Gemini keeps reasoning server-side. The judge's
actual reasoning channel is `record_observation`, which every model fills identically.

That is a property of the current configuration, not a law. Enable thinking on one provider and
the symmetry breaks. This script fails loudly if that happens.

Usage:
  python scripts/check_judge_symmetry.py results/tcga/clean/*
  python scripts/check_judge_symmetry.py --max-share 0.02 results/tcga/clean/*
Exit 1 if any run carries thinking TEXT, or if the observation channel is missing from an arm.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import sys

EP = re.compile(r'g\d[ab]?_[a-z]+(_mislead_[a-z]+)?_s\d+')


def episode_jsons(run: str) -> list[str]:
    return sorted(p for p in glob.glob(os.path.join(run, '**', '*.json'), recursive=True)
                  if EP.fullmatch(os.path.basename(p)[:-5])
                  and os.path.basename(os.path.dirname(p)) == os.path.basename(p)[:-5])


def survey(run: str) -> dict:
    n = blocks = with_text = chars = obs_calls = eps_with_obs = 0
    for p in episode_jsons(run):
        try:
            d = json.load(open(p))
        except Exception:
            continue
        n += 1
        ep_obs = 0
        for m in d.get('messages') or []:
            c = m.get('content')
            if not isinstance(c, list):
                continue
            for b in c:
                t = b.get('type')
                if t in ('thinking', 'reasoning'):
                    blocks += 1
                    txt = (b.get('thinking') or b.get('reasoning') or b.get('text') or '')
                    if txt.strip():
                        with_text += 1
                        chars += len(txt)
                elif t == 'tool_use' and b.get('name') == 'record_observation':
                    ep_obs += 1
        obs_calls += ep_obs
        eps_with_obs += bool(ep_obs)
    return dict(run=run, n=n, blocks=blocks, with_text=with_text, chars=chars,
                obs_calls=obs_calls, eps_with_obs=eps_with_obs)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('runs', nargs='+')
    ap.add_argument('--max-share', type=float, default=0.0,
                    help='tolerated fraction of episodes carrying thinking TEXT (default 0)')
    a = ap.parse_args()

    rows = [survey(r) for r in a.runs if os.path.isdir(r)]
    rows = [r for r in rows if r['n']]
    if not rows:
        print("No episodes found — refusing to pass vacuously.", file=sys.stderr)
        return 1

    print(f"  {'run':34} {'eps':>4} {'think blks':>11} {'WITH TEXT':>10} "
          f"{'obs/ep':>7} {'eps w/ obs':>11}")
    print("  " + "-" * 82)
    bad = []
    for r in rows:
        share = r['with_text'] / max(r['n'], 1)
        flag = ''
        if share > a.max_share:
            flag = '  <-- THINKING TEXT PRESENT'
            bad.append(r)
        if r['eps_with_obs'] < r['n']:
            flag += f"  <-- {r['n'] - r['eps_with_obs']} ep(s) with NO record_observation"
            bad.append(r)
        print(f"  {os.path.basename(r['run']):34} {r['n']:>4} {r['blocks']:>11} "
              f"{r['with_text']:>10} {r['obs_calls']/max(r['n'],1):>7.1f} "
              f"{r['eps_with_obs']:>11}{flag}")

    print()
    if bad:
        print("  FAIL — the judge does NOT see a symmetric reasoning channel across these runs.")
        print("  Cross-model derivation comparisons are confounded until this is resolved.")
        print("  If thinking was enabled deliberately, it must be enabled for EVERY arm, or")
        print("  excluded from the rendered judge input in scripts/extract_cot.py.")
        return 1
    print("  PASS — no thinking text in any arm; record_observation present in every episode.")
    print("  The judge reads the same kind of channel for every model.")
    return 0


if __name__ == '__main__':
    sys.exit(main())
