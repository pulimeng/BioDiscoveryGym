"""Judge provenance read from the artifacts, for the HTML report generators."""
from __future__ import annotations

import glob
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import panel_data


def panel_judges(runs, kinds=('cot', 'support', 'outcome')):
    """Every judge_model actually recorded across the run set, per artifact kind.

    Replaces three copies of a helper that scanned only CoT summaries and `break`ed after the
    first file in each run dir — so under a panel it reported ONE family for a run judged by
    three, and reported the support judge as "not recorded" although every panel artifact now
    records provenance. Reading one file and generalising is the stale-attribution failure those
    helpers existed to prevent.
    """
    seen = {k: set() for k in kinds}
    for r in runs:
        for k in kinds:
            for p in glob.glob(panel_data.artifact_glob(r, k)):
                try:
                    m = json.load(open(p)).get('judge_model')
                except Exception:
                    continue
                if m:
                    seen[k].add(m)
    return {k: sorted(v) for k, v in seen.items()}


def panel_judge_label(runs):
    """'nemotron-3-super + laguna + Qwen/...' — or an explicit gap if provenance is missing."""
    s = panel_judges(runs)
    allj = sorted(set().union(*s.values())) if any(s.values()) else []
    return " + ".join(allj) if allj else "unrecorded"
