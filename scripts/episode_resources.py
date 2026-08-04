#!/usr/bin/env python3
"""Per-episode tokens and wall-clock for one or more run directories.

Answers the two operational questions this project keeps re-deriving by hand:
  "what did this run cost"   -> tokens in/out per episode, and the totals
  "where did the time go"    -> API vs code-exec vs unaccounted, per episode

Reads the `resources` rollup written by run_episode.py, and falls back to summing the raw
run_log for episodes recorded before that field existed. Episodes whose provider never reported
usage are counted SEPARATELY rather than averaged in as zeros -- a run where half the episodes
silently reported nothing must not render as a cheap run.

No prices: see biodiscoverygym/resources.py for why. For dollars, scripts/gen_cost_report.py.

Usage:
  python scripts/episode_resources.py results/tcga/clean/gpt55
  python scripts/episode_resources.py results/tcga/clean/*        # several runs
  python scripts/episode_resources.py --by-arm results/tcga/clean/*
  python scripts/episode_resources.py --csv out.csv results/tcga/clean/*
"""
from __future__ import annotations

import argparse
import csv
import glob
import json
import os
import re
import statistics as st
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from biodiscoverygym.resources import summarize

EPISODE_RE = re.compile(r'g\d[ab]?_[a-z]+(_mislead_[a-z]+)?_s\d+')


def episode_logs(run: str) -> list[str]:
    """Episode JSONs only — <label>/<label>.json. Excludes scorer and judge sidecars."""
    out = []
    for p in glob.glob(os.path.join(run, '**', '*.json'), recursive=True):
        stem = os.path.basename(p)[:-5]
        if EPISODE_RE.fullmatch(stem) and os.path.basename(os.path.dirname(p)) == stem:
            out.append(p)
    return sorted(out)


def load(p: str) -> dict | None:
    try:
        d = json.load(open(p))
    except Exception:
        return None
    res = d.get('resources') or summarize(d.get('run_log', {}), d.get('wall_time_s'))
    stem = os.path.basename(p)[:-5]
    res['label'] = stem
    res['arm'] = stem.split('_')[0]
    res['model'] = d.get('model', '?')
    return res


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('runs', nargs='+')
    ap.add_argument('--by-arm', action='store_true', help='aggregate by arm instead of listing episodes')
    ap.add_argument('--csv', help='also write per-episode rows to this path')
    a = ap.parse_args()

    rows: list[dict] = []
    for run in a.runs:
        if not os.path.isdir(run):
            continue
        for p in episode_logs(run):
            r = load(p)
            if r:
                r['run'] = run.rstrip('/')
                rows.append(r)

    if not rows:
        print("No episode logs found. Looked for <run>/<label>/<label>.json", file=sys.stderr)
        return 1

    tok = [r for r in rows if r.get('tokens_reported')]
    missing = len(rows) - len(tok)

    if a.by_arm:
        print(f"{'run':28} {'arm':5} {'n':>3} {'in/ep':>11} {'out/ep':>9} {'wall/ep':>9}")
        print('-' * 70)
        keys = sorted({(r['run'], r['arm']) for r in tok})
        for run, arm in keys:
            g = [r for r in tok if r['run'] == run and r['arm'] == arm]
            print(f"{os.path.basename(run):28} {arm:5} {len(g):>3} "
                  f"{st.mean(x['input_tokens'] for x in g):>11,.0f} "
                  f"{st.mean(x['output_tokens'] for x in g):>9,.0f} "
                  f"{st.mean(x.get('wall_time_s', 0) for x in g):>8.0f}s")
    else:
        print(f"{'episode':38} {'in':>11} {'out':>8} {'turns':>6} {'wall':>8} {'API':>6} {'exec':>6}")
        print('-' * 88)
        for r in rows:
            if not r.get('tokens_reported'):
                print(f"{r['label']:38} {'— no usage reported by provider —':>48}")
                continue
            api = f"{r['pct_api']:.0f}%" if r.get('api_time_measured') else '  n/a'
            print(f"{r['label']:38} {r['input_tokens']:>11,} {r['output_tokens']:>8,} "
                  f"{r['n_turns']:>6} {r.get('wall_time_s', 0):>7.0f}s {api:>6} "
                  f"{r.get('pct_exec', 0):>5.0f}%")

    print('-' * 88)
    print(f"episodes: {len(rows)}   with token data: {len(tok)}"
          + (f"   WITHOUT (excluded from means): {missing}" if missing else ""))
    if tok:
        ti = sum(r['input_tokens'] for r in tok)
        to = sum(r['output_tokens'] for r in tok)
        wall = sum(r.get('wall_time_s', 0) for r in tok)
        print(f"total tokens : {ti:,} in / {to:,} out   ({ti/1e6:.1f}M / {to/1e6:.2f}M)")
        print(f"per episode  : {ti/len(tok):,.0f} in / {to/len(tok):,.0f} out   "
              f"ratio {ti/max(to,1):.0f}:1 input-heavy")
        print(f"wall-clock   : {wall/3600:.1f}h total, {wall/len(tok)/60:.1f} min/episode")
        rt = sum(r.get('api_retries', 0) for r in tok)
        to_ = sum(r.get('n_exec_timeouts', 0) for r in tok)
        if rt or to_:
            print(f"anomalies    : {rt} API retries, {to_} run_code timeouts")

    if a.csv:
        cols = ['run', 'label', 'arm', 'model', 'input_tokens', 'output_tokens', 'n_turns',
                'wall_time_s', 'api_s', 'exec_s', 'unaccounted_s', 'api_retries',
                'n_exec_timeouts', 'tokens_reported', 'api_time_measured']
        with open(a.csv, 'w', newline='') as f:
            w = csv.DictWriter(f, fieldnames=cols, extrasaction='ignore')
            w.writeheader()
            w.writerows(rows)
        print(f"\nwrote {a.csv}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
