#!/usr/bin/env python3
"""Decision-point explore/exploit scorer (prototype).

SUPERSEDED (2026-07-02) by scripts/score_support.py. This ranked derived>recalled (i.e.
scored exploration above exploitation); the grounding scorer replaces that with a neutral
strategy tag + a scored grounding axis. Kept because it produced run1+2's _dpscores.json
(the partition derived-rate gradient cited in docs/EXPLORE_EXPLOIT_SCORING.md). See docs/README.md.


For each episode in a run dir, an LLM judge reads the TRACE (run_code # WHY: headers +
record_observation hypotheses + the final discovery) and classifies the agent's approach
at three decision points — D1 partition, D2 identity, D3 mechanism — as
derived(explore) / recalled(exploit) / mixed / hedged / none. The judge returns ONLY the
levels; points are computed programmatically. Outputs per-episode levels + a process
score, and aggregates derived-rate by arm (the G0->G2 shift is the explore/exploit signal).

Design: docs/DECISION_POINT_RUBRIC.md.

Usage:
    # inspect the judge input for one episode WITHOUT calling the API:
    python scripts/score_decision_points.py results/tcga/run1+2 --dry --limit 1
    # run the judge over the whole dir (needs ANTHROPIC_API_KEY; ~1 call/episode):
    python scripts/score_decision_points.py results/tcga/run1+2 --save
"""
from __future__ import annotations
import argparse, glob, json, os, sys
from collections import defaultdict

LEVEL_POINTS = {"derived": 1.0, "mixed": 0.6, "recalled": 0.5, "hedged": 0.3,
                "none": 0.0, "fooled": 0.0}
WEIGHTS = {"d1_partition": 2.0, "d2_identity": 2.0, "d3_mechanism": 1.0}
DECISIONS = list(WEIGHTS)

JUDGE_SYSTEM = """\
You classify HOW a cancer-genomics agent reached three decisions, from its analysis
trace. This is about PROCESS (did it derive from the data, or recall a prior?), NOT about
whether the final answer is correct — correctness is scored separately. Judge only what
the trace shows the agent actually did.

For each decision, choose exactly one level:

D1 — PARTITION (how was the sample grouping arrived at?)
  derived  : grouping built from this dataset's molecular structure (variance / PCA /
             clustering); the method was chosen from the data.
  recalled : imported a known scheme or gene-set, or labeled clusters by a textbook
             scheme without deriving structure (e.g. "use the PAM50 genes to cluster").
  mixed    : derived structure but forced/framed through a recalled scheme.
  none     : no defensible partition.

D2 — IDENTITY (how was the cancer type / biological context determined?)
  derived  : inferred from data evidence accumulated during analysis (mutation pattern,
             marker expression computed here) BEFORE committing.
  recalled : recognized/named the cohort early, from prior knowledge, before or without
             the data work (e.g. "check known breast cancer genes to confirm tissue type").
  hedged   : did not commit / stayed uncertain.
  none     : identity never addressed.

D3 — MECHANISM (how was the mechanistic hypothesis formed?)
  derived  : reasoned from this cohort's data; revised against the prior when the data
             contradicted it (e.g. "survival is INVERTED from expected -> revise").
  recalled : retrofitted to the textbook mechanism for the recalled cancer type; ignored
             contradictory data.
  mixed    : partial grounding.
  none     : no mechanism.

Respond ONLY with valid JSON:
{
  "d1_partition": {"level": "...", "evidence": "<one quote/observation>"},
  "d2_identity":  {"level": "...", "evidence": "<one quote/observation>"},
  "d3_mechanism": {"level": "...", "evidence": "<one quote/observation>"}
}
"""


def extract_trace(ep: dict) -> dict:
    whys, ros = [], []
    for m in ep.get("messages", []):
        if m.get("role") != "assistant" or not isinstance(m.get("content"), list):
            continue
        for b in m["content"]:
            if not isinstance(b, dict) or b.get("type") != "tool_use":
                continue
            if b["name"] == "run_code":
                for ln in b["input"].get("code", "").splitlines():
                    if ln.strip().startswith("# WHY"):
                        whys.append(ln.strip()[6:].strip()); break
            elif b["name"] == "record_observation":
                ros.append(f"[{b['input'].get('confidence')}] "
                           + (b["input"].get("current_hypothesis") or "")[:200])
    disc = ep.get("discovery") or {}
    grp = disc.get("proposed_grouping") or {}
    labels = sorted({str(v) for v in grp.values()}) if isinstance(grp, dict) else []
    return {
        "why_headers": whys,
        "observations": ros,
        "subtype_labels": labels,
        "top_genes": (disc.get("top_genes") or [])[:15],
        "mechanism": (disc.get("mechanism_hypothesis") or "")[:600],
    }


def build_user_msg(t: dict) -> str:
    return (
        "RUN_CODE # WHY: headers, in order:\n"
        + "\n".join(f"  {i}. {w}" for i, w in enumerate(t["why_headers"])) + "\n\n"
        "record_observation hypotheses, in order:\n"
        + "\n".join(f"  - {r}" for r in t["observations"]) + "\n\n"
        f"SUBMITTED subtype labels: {t['subtype_labels']}\n"
        f"SUBMITTED top genes: {t['top_genes']}\n"
        f"SUBMITTED mechanism: {t['mechanism']}"
    )


def judge(user_msg: str, model: str) -> dict:
    import anthropic
    from biodiscoverygym.scoring.judge import _parse_json
    r = anthropic.Anthropic().messages.create(
        model=model, max_tokens=600, system=JUDGE_SYSTEM,
        messages=[{"role": "user", "content": user_msg}],
    )
    return _parse_json(r.content[0].text)


def process_score(levels: dict) -> float:
    return sum(LEVEL_POINTS.get(levels[d]["level"], 0.0) * WEIGHTS[d] for d in DECISIONS)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("run_dir")
    p.add_argument("--model", default="claude-sonnet-4-6")
    p.add_argument("--save", action="store_true", help="write <episode>_dpscores.json")
    p.add_argument("--dry", action="store_true", help="print judge input, no API call")
    p.add_argument("--limit", type=int, default=0, help="cap episodes (0 = all)")
    args = p.parse_args()

    if not args.dry and not os.environ.get("ANTHROPIC_API_KEY"):
        sys.exit("ANTHROPIC_API_KEY not set (or use --dry)")

    files = sorted(f for f in glob.glob(f"{args.run_dir}/*/g[0-3]*_s*.json")
                   if "scores" not in f and "trace" not in f)
    if args.limit:
        files = files[:args.limit]

    byarm = defaultdict(lambda: defaultdict(lambda: defaultdict(int)))  # arm -> decision -> level -> count
    rows = []
    for f in files:
        ep = json.load(open(f))
        arm = os.path.basename(f).split("_")[0]
        t = extract_trace(ep)
        umsg = build_user_msg(t)
        if args.dry:
            print(f"===== {os.path.basename(f)} ({len(t['why_headers'])} WHY, "
                  f"{len(t['observations'])} obs) =====")
            print(umsg[:2500]); print("..." if len(umsg) > 2500 else ""); print()
            continue
        try:
            levels = judge(umsg, args.model)
            sc = process_score(levels)
        except Exception as e:
            print(f"  !! {os.path.basename(f)} judge failed: {e}", file=sys.stderr); continue
        rows.append((os.path.basename(f), arm, levels, sc))
        for d in DECISIONS:
            byarm[arm][d][levels[d]["level"]] += 1
        print(f"{os.path.basename(f):34} score={sc:.1f}  "
              + "  ".join(f"{d[3:]}={levels[d]['level']}" for d in DECISIONS))
        if args.save:
            out = {"levels": levels, "process_score": sc, "weights": WEIGHTS}
            json.dump(out, open(f[:-5] + "_dpscores.json", "w"), indent=2)

    if args.dry or not rows:
        return
    print("\n=== derived-rate by arm (fraction 'derived') ===")
    print(f"{'arm':5} {'n':>3} " + " ".join(f"{d[3:]:>12}" for d in DECISIONS))
    for arm in sorted(byarm):
        n = sum(byarm[arm][DECISIONS[0]].values())
        cells = []
        for d in DECISIONS:
            tot = sum(byarm[arm][d].values()) or 1
            cells.append(f"{byarm[arm][d].get('derived', 0)/tot:>12.2f}")
        print(f"{arm:5} {n:>3} " + " ".join(cells))
    # the explore/exploit signal: G2 - G0 derived-rate shift per decision
    if "g0" in byarm and "g2" in byarm:
        print("\n=== explore/exploit shift  derived_rate(G2) - derived_rate(G0) ===")
        for d in DECISIONS:
            g0t = sum(byarm['g0'][d].values()) or 1; g2t = sum(byarm['g2'][d].values()) or 1
            shift = byarm['g2'][d].get('derived', 0)/g2t - byarm['g0'][d].get('derived', 0)/g0t
            print(f"  {d}: {shift:+.2f}")


if __name__ == "__main__":
    main()
