#!/usr/bin/env python3
"""Prototype: explore-vs-exploit metrics from the record_observation belief trail.

Reads completed episode JSONs (no API), extracts each episode's belief trail, and
computes candidate process metrics, grouped by arm (g0/g1/g2). Purpose: check whether
the trail separates exploitation (G0/G1, recall-enabled) from exploration (G2, blinded)
BEFORE committing to a scoring rework. See docs/EXPLORE_EXPLOIT_SCORING.md.

Usage:
    python scripts/proto_belief_metrics.py results/tcga/run1+2   # merged run1+run2
"""
import json, glob, os, difflib, statistics as st, sys
from collections import defaultdict

CMAP = {"low": 0.0, "medium": 0.5, "high": 1.0}


def metrics(obs: list[dict]) -> dict | None:
    if not obs:
        return None
    confs = [CMAP.get((o.get("confidence") or "").lower(), 0.5) for o in obs]
    hyps = [o.get("current_hypothesis") or "" for o in obs]
    alts = [len(o.get("alternatives_considered") or []) for o in obs]
    against = [len(o.get("evidence_against") or []) for o in obs]
    # hypothesis revision: 1 - text similarity between consecutive hypotheses (higher = more revision)
    rev = [1 - difflib.SequenceMatcher(None, hyps[i], hyps[i + 1]).ratio()
           for i in range(len(hyps) - 1)] or [0.0]
    # time-to-commit: normalized index of first 'high' confidence (1.0 = only at end / never)
    hi = [i for i, c in enumerate(confs) if c >= 1.0]
    ttc = (hi[0] / (len(obs) - 1)) if hi and len(obs) > 1 else 1.0
    return dict(n_obs=len(obs), alts=st.mean(alts), against=st.mean(against),
                revision=st.mean(rev), conf_start=confs[0],
                conf_rise=confs[-1] - confs[0], ttc=ttc)


def main():
    root = sys.argv[1] if len(sys.argv) > 1 else "results/tcga/run2"
    byarm = defaultdict(list)
    for f in glob.glob(f"{root}/*/g[0-3]*_s*.json"):
        if "scores" in f or "trace" in f:
            continue
        d = json.load(open(f))
        obs = d.get("observations") or (d.get("run_log") or {}).get("observations") or []
        m = metrics(obs)
        if m:
            byarm[os.path.basename(f).split("_")[0]].append(m)

    keys = ["n_obs", "alts", "against", "revision", "conf_start", "conf_rise", "ttc"]
    print(f"{'arm':5} {'n':>3} " + " ".join(f"{k:>10}" for k in keys))
    for arm in sorted(byarm):
        rows = byarm[arm]
        print(f"{arm:5} {len(rows):>3} " + " ".join(f"{st.mean(r[k] for r in rows):>10.2f}" for k in keys))
    print("\nexplorer(G2) expects HIGHER n_obs/revision/conf_rise/ttc, LOWER conf_start vs exploiter(G0/G1)")


if __name__ == "__main__":
    main()
