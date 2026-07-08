#!/usr/bin/env python3
"""Support scorer — the calibration (strategy x support) scorer for the explore/exploit study.

For each episode a validated judge (scripts/support_judge.py; prompt validated to ~95% on
scripts/support_probes.json) reads the trace + the cohort's reference card and returns, per
decision (D1 partition / D2 identity / D3 mechanism):
  strategy      neutral tag : explore / exploit / mixed   (NOT scored — the manipulation check)
  support     scored      : grounded / unsupported / anchored
  contradiction audit       : revised / ignored / none

Scored on support ONLY (docs/SUPPORT_JUDGE_PROMPT.md). Writes <episode>_supportscores.json and
prints the strategy x support cross-tab by arm — exploit x anchored = the miscalibration cell.
The judge is BLIND to the objective backstops (concordance, cohort gate); reconcile offline.

Replaces the derived>recalled prototype (score_decision_points.py -> _dpscores.json), which
ranked exploration above exploitation. Cohort per episode = ep["cohort"] (true cohort; for G3
that is the real data, not the mislead label).

Usage:
    python scripts/score_support.py results/tcga/run1+2 --dry --limit 1
    ANTHROPIC_API_KEY=sk-... python scripts/score_support.py results/tcga/run1+2 --save
    python scripts/score_support.py results/tcga/run1+2 --arms g0,g1 --save   # money panel
"""
from __future__ import annotations
import argparse, glob, json, os, sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import support_judge as gj

STRATS = ["explore", "exploit", "mixed"]
GRDS = ["grounded", "unsupported", "anchored"]


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


def arm_of(fname: str) -> str:
    return os.path.basename(fname).split("_")[0]  # g0 g1 g2 g3a g3b


def main():
    p = argparse.ArgumentParser()
    p.add_argument("run_dir")
    p.add_argument("--model", default="deepseek-v4-pro",
                   help="judge model — NEUTRAL family (not in the benchmarked set). "
                        "deepseek-v4-pro (default) / claude-* / gpt-* all supported.")
    p.add_argument("--save", action="store_true", help="write <episode>_supportscores.json")
    p.add_argument("--dry", action="store_true", help="print judge input, no API")
    p.add_argument("--limit", type=int, default=0)
    p.add_argument("--arms", default="", help="comma list to include, e.g. g0,g1")
    p.add_argument("--rescore", action="store_true",
                   help="re-judge episodes that already have _supportscores.json (default: skip them)")
    args = p.parse_args()

    if not args.dry:
        m = args.model.lower()
        need = ("DEEPSEEK_API_KEY" if m.startswith("deepseek")
                else "ANTHROPIC_API_KEY" if "claude" in m else "OPENAI_API_KEY")
        if not os.environ.get(need):
            sys.exit(f"{need} not set for judge model {args.model} (or use --dry)")

    files = sorted(f for f in glob.glob(f"{args.run_dir}/*/g[0-3]*_s*.json")
                   if "scores" not in f and "trace" not in f)
    arms_filter = {a.strip() for a in args.arms.split(",") if a.strip()}
    if arms_filter:
        files = [f for f in files if arm_of(f) in arms_filter]
    # resume-safe: skip already-scored episodes (unless --dry or --rescore) so re-runs don't re-bill
    if args.save and not args.rescore and not args.dry:
        _before = len(files)
        files = [f for f in files if not os.path.exists(f[:-5] + "_supportscores.json")]
        _skipped = _before - len(files)
        if _skipped:
            print(f"(skipping {_skipped} already-scored; --rescore to redo)")
    if args.limit:
        files = files[:args.limit]

    cross = defaultdict(lambda: defaultdict(lambda: defaultdict(int)))  # arm->decision->(strat,grd)->n
    scores = defaultdict(list)                                          # arm -> [support_score]
    rows = []
    for f in files:
        ep = json.load(open(f))
        cohort, arm = ep.get("cohort", ""), arm_of(f)
        try:
            t = extract_trace(ep)
            umsg = gj.build_user_msg(t, cohort)
        except KeyError as e:
            print(f"  !! {os.path.basename(f)} skipped: {e}", file=sys.stderr); continue
        if args.dry:
            print(f"===== {os.path.basename(f)}  cohort={cohort} arm={arm} "
                  f"({len(t['why_headers'])} WHY, {len(t['observations'])} obs) =====")
            print(umsg[:1800] + "\n...\n")
            continue
        try:
            levels = gj.call_judge(umsg, args.model)
            sc = gj.support_score(levels)
            flags = gj.audit_flags(levels)
        except Exception as e:
            print(f"  !! {os.path.basename(f)} judge failed: {e}", file=sys.stderr); continue
        scores[arm].append(sc)
        for d in gj.DECISIONS:
            cross[arm][d][(levels[d].get("strategy"), levels[d].get("support"))] += 1
        rows.append((os.path.basename(f), arm, cohort, levels, sc, flags))
        print(f"{os.path.basename(f):34} {cohort:5} score={sc:.1f}/5  "
              + "  ".join(f"{d[:2]}:{(levels[d].get('strategy') or '?')[:3]}/"
                          f"{(levels[d].get('support') or '?')[:4]}" for d in gj.DECISIONS)
              + (f"  [audit: {';'.join(flags)}]" if flags else ""))
        if args.save:
            out = {"cohort": cohort, "arm": arm, "levels": levels,
                   "support_score": sc, "score_max": sum(gj.WEIGHTS.values()),
                   "audit_flags": flags, "weights": gj.WEIGHTS}
            json.dump(out, open(f[:-5] + "_supportscores.json", "w"), indent=2)

    if args.dry or not rows:
        return
    _report(cross, scores)


def _pool(cross, arms):
    tab = defaultdict(int)
    for a in arms:
        for d in cross[a]:
            for key, c in cross[a][d].items():
                tab[key] += c
    return tab


def _print_crosstab(tab):
    print(f"      {'':8}" + "".join(f"{g:>12}" for g in GRDS))
    for s in STRATS:
        print(f"      {s:8}" + "".join(f"{tab.get((s, g), 0):>12}" for g in GRDS))


def _report(cross, scores):
    arms = sorted(cross)
    print("\n=== support score by arm (mean /5) ===")
    for a in arms:
        s = scores[a]
        print(f"  {a:4} n={len(s):2}  mean={sum(s)/len(s):.2f}")

    print("\n=== strategy distribution by arm (manipulation check — explore share) ===")
    for a in arms:
        tot = defaultdict(int); n = 0
        for d in cross[a]:
            for (strat, _grd), c in cross[a][d].items():
                tot[strat] += c; n += c
        n = n or 1
        print(f"  {a:4}  " + "  ".join(f"{s}={tot.get(s, 0)/n:.0%}" for s in STRATS))

    print("\n=== strategy x support cross-tab (pooled decisions, ALL arms) ===")
    _print_crosstab(_pool(cross, arms))
    print("      -> exploit x anchored = miscalibration (recall against the data)")
    for a in arms:
        print(f"\n  --- {a} ---")
        _print_crosstab(_pool(cross, [a]))


if __name__ == "__main__":
    main()
