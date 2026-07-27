#!/usr/bin/env python3
"""Integrity check for CoT judge outputs before resuming an interrupted panel run.

WHY THIS EXISTS: summarize_cot.py writes with a plain json.dump to an open file and SKIPS any
episode whose output already exists. So a run killed mid-write leaves a truncated file that the
resume will never regenerate — it looks "done" to the resume logic and fails silently at analysis
time, or worse, parses but is missing fields. This finds those files so they can be deleted and
re-judged.

Checks, per judge suffix:
  1. parses as JSON at all              (truncated write)
  2. is a dict, non-empty               (garbage write)
  3. has every schema-required field    (partial tool call)
  4. categorical fields hold LEGAL enum values (judge drifting off-schema)
  5. filename matches its episode dir   (misplaced/stray artifact)
  6. coverage per run dir vs episodes on disk

Usage:
  python scripts/check_judge_integrity.py                       # all suffixes, the 6 live runs
  python scripts/check_judge_integrity.py --suffix _cotsummary_j2.json
  python scripts/check_judge_integrity.py --delete-bad          # remove corrupt files so a
                                                                # resume re-judges them
"""
import argparse, glob, json, os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

RUNS = [
    "results/tcga/ladder/sonnet5_20260713",
    "results/tcga/ladder/gpt55_20260707",
    "results/tcga/ladder/gemini35flash_20260716",
    "results/tcga/lean/sonnet5_20260722",
    "results/tcga/lean/gpt55_20260721",
    "results/tcga/lean/gemini35flash_20260722",
]
SUFFIXES = ["_cotsummary.json", "_cotsummary_j2.json", "_cotsummary_j3.json"]

# Pulled from summarize_cot's tool schema rather than hardcoded, so the two cannot drift apart.
try:
    from summarize_cot import _COT_TOOL, _REQUIRED
    SCHEMA = _COT_TOOL["input_schema"]["properties"]
    REQUIRED = list(_REQUIRED)
except Exception as e:                                            # keep usable if the import moves
    print(f"  (!) could not import schema from summarize_cot ({e}); using a fallback", file=sys.stderr)
    SCHEMA, REQUIRED = {}, ["reasoning_strategy", "identity_derivation", "validation_rigor"]
ENUMS = {k: set(v["enum"]) for k, v in SCHEMA.items() if isinstance(v, dict) and "enum" in v}


def episodes(run):
    """Episode traces on disk — the denominator for coverage."""
    out = []
    for p in glob.glob(f"{run}/*/g[0-3]*_s*.json"):
        b = os.path.basename(p)
        if b[:-5] == os.path.basename(os.path.dirname(p)):
            out.append(b[:-5])
    return set(out)


def check_file(p, sfx):
    """Return a list of problem strings for one judge output ([] == healthy)."""
    probs = []
    label = os.path.basename(p).replace(sfx, "")
    if label != os.path.basename(os.path.dirname(p)):
        return [f"filename/dir mismatch (label={label})"]
    if os.path.getsize(p) == 0:
        return ["ZERO BYTES"]
    try:
        d = json.load(open(p))
    except Exception as e:
        return [f"UNPARSEABLE ({type(e).__name__}: {str(e)[:60]})"]
    if not isinstance(d, dict) or not d:
        return ["not a non-empty object"]
    for f in REQUIRED:
        if f not in d or d[f] in (None, "", []):
            probs.append(f"missing/empty field: {f}")
    for f, allowed in ENUMS.items():
        if f in d and d[f] not in allowed:
            probs.append(f"illegal {f}={d[f]!r}")
    return probs


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("run_dirs", nargs="*", default=RUNS)
    ap.add_argument("--suffix", action="append", dest="suffixes",
                    help="judge suffix to check (repeatable; default: all three)")
    ap.add_argument("--delete-bad", action="store_true",
                    help="DELETE corrupt files so the next resume re-judges them")
    args = ap.parse_args()
    runs = args.run_dirs or RUNS
    sfxs = args.suffixes or SUFFIXES

    grand_bad, grand_files = [], 0
    for sfx in sfxs:
        found = any(glob.glob(f"{r}/*/*{sfx}") for r in runs)
        if not found:
            print(f"\n{'='*74}\n  {sfx}   — none on disk, skipping\n{'='*74}")
            continue
        print(f"\n{'='*74}\n  {sfx}\n{'='*74}")
        print(f"  {'run dir':40} {'files':>6} {'eps':>5} {'bad':>4}")
        tot_f = tot_bad = 0
        for r in runs:
            eps = episodes(r)
            fs = sorted(glob.glob(f"{r}/*/*{sfx}"))
            bad = []
            for p in fs:
                probs = check_file(p, sfx)
                if probs:
                    bad.append((p, probs))
            tot_f += len(fs); tot_bad += len(bad)
            grand_bad.extend(bad)
            flag = "  <-- CORRUPT" if bad else ""
            lbl = f"{os.path.basename(os.path.dirname(r))}/{os.path.basename(r)}"
            print(f"  {lbl:40} {len(fs):>6} {len(eps):>5} {len(bad):>4}{flag}")
        grand_files += tot_f
        print(f"  {'TOTAL':40} {tot_f:>6} {'':>5} {tot_bad:>4}")

    print(f"\n{'='*74}")
    if grand_bad:
        print(f"  {len(grand_bad)} CORRUPT FILE(S) of {grand_files} checked:\n")
        for p, probs in grand_bad:
            print(f"    {p}")
            for x in probs:
                print(f"        - {x}")
        if args.delete_bad:
            for p, _ in grand_bad:
                os.remove(p)
            print(f"\n  DELETED {len(grand_bad)} file(s) — re-run the panel to re-judge them.")
        else:
            print("\n  Re-run with --delete-bad to remove them, then resume the panel.")
        return 1
    print(f"  ALL CLEAN — {grand_files} judge outputs parsed, complete and schema-valid.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
