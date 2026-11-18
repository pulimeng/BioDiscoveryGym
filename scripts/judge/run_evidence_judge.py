#!/usr/bin/env python3
"""Run the v2 evidence-support judge over v2 run dirs (biodiscoverygym/scoring/evidence_judge.py).

    python scripts/judge/run_evidence_judge.py results/v2/pilot_nolabelcheck/sonnet55 [more dirs] \
        [--model AI-Workstation/qwen3.8-flash] [--swap] [--limit N]

Writes <run_dir>/_judging/evidence_<judge>.jsonl, one record per claim unit, resume-safe (units
already judged OK are skipped; invalid ones are retried). --swap also judges each claim against
unrelated earlier evidence (the sensitivity test). Network: the judge gateway needs the internal
network. Invalid records are reported and never counted as verdicts.
"""
from __future__ import annotations

import argparse
import collections
import glob
import json
import os
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

_ROOT = next(p for p in Path(__file__).resolve().parents if (p / "setup.py").exists())
sys.path.insert(0, str(_ROOT))
from biodiscoverygym.claims import extract_claims, swap_evidence  # noqa: E402
from biodiscoverygym.scoring.evidence_judge import VERDICTS, EvidenceJudge  # noqa: E402


def episode_dirs(run_dir: str) -> list[Path]:
    return sorted(Path(d) for d in glob.glob(os.path.join(run_dir, "g[0-3]*_s*"))
                  if (Path(d) / "events.jsonl").exists())


def summarize(records: list[dict]) -> str:
    out = []
    ok = [r for r in records if r["status"] == "ok"]
    out.append(f"{len(records)} records: {len(ok)} ok, {len(records) - len(ok)} invalid "
               f"({sum(r.get('retried', False) for r in ok)} needed the quote retry)")
    tab = collections.defaultdict(collections.Counter)
    for r in ok:
        tab[(r["model"], r["variant"])][r["verdict"]] += 1
    out.append(f"\n{'agent model':20} {'variant':8} " + " ".join(f"{v:>16}" for v in VERDICTS))
    for (m, v), c in sorted(tab.items()):
        out.append(f"{m:20} {v:8} " + " ".join(f"{c[x]:>16}" for x in VERDICTS))
    by_id = {r["unit_id"]: r for r in ok}
    pairs = [(by_id[r["swapped_from"]], r) for r in ok if r["variant"] == "swapped" and r["swapped_from"] in by_id]
    if pairs:
        pos = [(a, b) for a, b in pairs if a["verdict"] in ("supports", "partly")]
        dropped = sum(b["verdict"] in ("does_not_support", "contradicts") for _, b in pos)
        out.append(f"\nSWAP TEST: of {len(pos)} claims judged supports/partly on their cited evidence, "
                   f"{dropped} ({100 * dropped / max(1, len(pos)):.0f}%) drop to does_not_support/contradicts "
                   f"on unrelated evidence; {sum(b['verdict'] == 'supports' for _, b in pos)} stay 'supports' "
                   f"(false support).")
    bad = [r for r in records if r["status"] != "ok"]
    for r in bad[:10]:
        out.append(f"  INVALID {r['episode']} step {r['step']} {r['variant']}: {r['error'][:160]}")
    return "\n".join(out)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("dirs", nargs="+")
    ap.add_argument("--model", default="AI-Workstation/qwen3.8-flash")
    ap.add_argument("--swap", action="store_true", help="also judge swapped-evidence variants")
    ap.add_argument("--limit", type=int, default=0, help="judge at most N new units (smoke test)")
    ap.add_argument("--workers", type=int, default=4, help="parallel judge calls (gateway is shared)")
    a = ap.parse_args()
    judge = EvidenceJudge(a.model)
    tag = a.model.split("/")[-1]
    all_records, n_new = [], 0
    for run_dir in a.dirs:
        out_path = Path(run_dir) / "_judging" / f"evidence_{tag}.jsonl"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        prev = {}
        if out_path.exists():
            for l in out_path.read_text().splitlines():
                r = json.loads(l)
                prev[r["unit_id"]] = r
        units = []
        for d in episode_dirs(run_dir):
            for u in extract_claims(d):
                units.append(u)
                if a.swap:
                    s = swap_evidence(u, d)
                    if s:
                        units.append(s)
        todo = [u for u in units if prev.get(u["unit_id"], {}).get("status") != "ok"]
        if a.limit:
            todo = todo[:max(0, a.limit - n_new)]
        lock = threading.Lock()

        def one(u):
            rec = judge.judge(u)
            with lock:
                prev[u["unit_id"]] = rec
                print(f"  {rec['status']:7} {rec.get('verdict', '-'):17} {u['episode']} step {u['step']} "
                      f"{u['variant']}", flush=True)
                out_path.write_text("".join(json.dumps(r) + "\n" for r in prev.values()))

        with ThreadPoolExecutor(max_workers=a.workers) as ex:
            list(ex.map(one, todo))
        n_new += len(todo)
        all_records += [prev[u["unit_id"]] for u in units if u["unit_id"] in prev]
    print("\n" + summarize(all_records))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
