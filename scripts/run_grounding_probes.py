#!/usr/bin/env python3
"""Validate the grounding judge against known-answer probes BEFORE trusting it on real runs.

Each probe (scripts/grounding_probes.json) is a hand-authored trace with the correct verdict
pre-committed. This feeds trace+card to the judge and compares its {strategy, grounding,
contradiction} per decision to `expected`. Reports field-level agreement overall and for the
scored axis (grounding), plus every mismatch and any internal-consistency flags.

>=80% agreement is NECESSARY-not-sufficient (docs/GROUNDING_JUDGE_PROMPT.md): clean-cut
probes prove the judge isn't broken, not that it's reliable on the ambiguous middle.

Usage:
    python scripts/run_grounding_probes.py --dry                 # print judge inputs, no API
    python scripts/run_grounding_probes.py --dry --id lihc_anchored_ignored
    ANTHROPIC_API_KEY=sk-... python scripts/run_grounding_probes.py
"""
from __future__ import annotations
import argparse, json, os, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import grounding_judge as gj

PROBES = Path(__file__).resolve().parent / "grounding_probes.json"
FIELDS = ["strategy", "grounding", "contradiction"]


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--model", default="claude-sonnet-4-6")
    p.add_argument("--dry", action="store_true", help="print judge input, no API call")
    p.add_argument("--id", help="run only the probe with this id")
    args = p.parse_args()

    probes = [q for q in json.load(open(PROBES))["probes"]
              if not args.id or q["id"] == args.id]
    if not probes:
        sys.exit(f"no probe matching id={args.id!r}")
    if not args.dry and not os.environ.get("ANTHROPIC_API_KEY"):
        sys.exit("ANTHROPIC_API_KEY not set (or use --dry)")

    tot = tot_ok = grd = grd_ok = 0
    for q in probes:
        umsg = gj.build_user_msg(q["trace"], q["cohort"])
        if args.dry:
            print(f"\n===== {q['id']} ({q['cohort']}) =====")
            print(f"TESTS: {q['tests']}")
            print(umsg[:2200] + ("..." if len(umsg) > 2200 else ""))
            print(f"EXPECTED: {json.dumps(q['expected'])}")
            continue
        try:
            got = gj.call_judge(umsg, args.model)
        except Exception as e:
            print(f"!! {q['id']} judge failed: {e}", file=sys.stderr)
            continue
        mism = []
        for d in gj.DECISIONS:
            for f in FIELDS:
                exp = q["expected"][d][f]
                act = got.get(d, {}).get(f)
                tot += 1
                if f == "grounding":
                    grd += 1
                if act == exp:
                    tot_ok += 1
                    if f == "grounding":
                        grd_ok += 1
                else:
                    mism.append(f"{d[:2]}.{f}: exp={exp} got={act}")
        flags = gj.audit_flags(got)
        status = "OK " if not mism else "XX "
        print(f"{status}{q['id']:28} grounding "
              + " ".join(got.get(d, {}).get("grounding", "?")[:4] for d in gj.DECISIONS)
              + (f"   MISMATCH: {'; '.join(mism)}" if mism else "")
              + (f"   [audit: {', '.join(flags)}]" if flags else ""))

    if args.dry or tot == 0:
        return
    print(f"\n=== agreement ===")
    print(f"  all fields : {tot_ok}/{tot} = {tot_ok/tot:.0%}")
    print(f"  grounding  : {grd_ok}/{grd} = {grd_ok/grd:.0%}   (the scored axis — the one that matters)")
    print(f"  gate: >=80% is NECESSARY, not sufficient (see judge-prompt doc).")


if __name__ == "__main__":
    main()
