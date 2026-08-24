#!/usr/bin/env python3
"""Integrity check for CoT judge outputs before resuming an interrupted panel run.

WHY THIS EXISTS: summarize_cot.py writes with a plain json.dump to an open file and SKIPS any
episode whose output already exists. So a run killed mid-write leaves a truncated file that the
resume will never regenerate — it looks "done" to the resume logic and fails silently at analysis
time, or worse, parses but is missing fields. This finds those files so they can be deleted and
re-judged.

Checks, per judge family:
  1. parses as JSON at all              (truncated write)
  2. is a dict, non-empty               (garbage write)
  3. has every schema-required field    (partial tool call)
  4. categorical fields hold LEGAL enum values (judge drifting off-schema)
  5. filename matches its episode dir   (misplaced/stray artifact)
  6. coverage per run dir vs episodes on disk

Usage:
  python scripts/check_judge_integrity.py                       # all suffixes, the 6 live runs
  python scripts/check_judge_integrity.py --suffix laguna       # one judge family
  python scripts/check_judge_integrity.py --delete-bad          # remove corrupt files so a
                                                                # resume re-judges them
"""
import argparse, glob, json, os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import judges_config as J
import panel_data
import runs_config

# Resolved from runs_config, not hardcoded. This list used to name the six PILOT lanes, so a
# bare `python scripts/check_judge_integrity.py` certified the judge outputs of a campaign that
# is not the one under analysis — passing loudly while saying nothing about the clean run.
# runs_config defaults to the clean campaign and announces whatever it picked.
RUNS = runs_config.flat()
# Judge TAGS on the panel, not the retired flat filename suffixes. Globbing `*/*_cotsummary.json`
# after the layout move matched nothing, so this printed
#     "ALL CLEAN - 0 judge outputs parsed, complete and schema-valid"
# and exited 0. A gate that certifies an empty set is worse than no gate: it is the exact
# "non-event rendering as a benign value" failure it was written to catch, in the catcher.
SUFFIXES = J.tags()

# Pulled from summarize_cot's tool schema rather than hardcoded, so the two cannot drift apart.
# The repo root must be importable: summarize_cot imports biodiscoverygym, and without it the
# import below fails, the fallback engages, and this checker then validates 3 of 10 fields with no
# enum checking WHILE STILL PRINTING "complete and schema-valid". That is a weaker claim wearing a
# stronger claim's words — the exact failure class this script exists to catch.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCHEMA_DEGRADED = False
try:
    from summarize_cot import _COT_TOOL, _REQUIRED
    SCHEMA = _COT_TOOL["input_schema"]["properties"]
    REQUIRED = list(_REQUIRED)
except Exception as e:                                            # keep usable if the import moves
    SCHEMA_DEGRADED = str(e)
    print(f"  (!) could not import schema from summarize_cot ({e})", file=sys.stderr)
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
    # Under scoring/<judge>/ the filename is a constant (cotsummary.json) and the EPISODE dir is
    # two levels up. The old basename-vs-dirname test compared "cotsummary" against the judge tag
    # and rejected every real file.
    label = panel_data.label_of(p)
    if label != os.path.basename(panel_data.episode_dir_of(p)):
        return [f"artifact/episode-dir mismatch (label={label})"]
    if os.path.basename(os.path.dirname(p)) != sfx:
        return [f"judge-dir mismatch (in {os.path.basename(os.path.dirname(p))!r}, expected {sfx!r})"]
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
    covgaps = []
    for sfx in sfxs:
        found = any(glob.glob(panel_data.artifact_glob(r, 'cot', sfx)) for r in runs)
        if not found:
            print(f"\n{'='*74}\n  {sfx}   — none on disk, skipping\n{'='*74}")
            continue
        print(f"\n{'='*74}\n  {sfx}\n{'='*74}")
        print(f"  {'run dir':40} {'files':>6} {'eps':>5} {'bad':>4}")
        tot_f = tot_bad = 0
        for r in runs:
            eps = episodes(r)
            fs = sorted(glob.glob(panel_data.artifact_glob(r, 'cot', sfx)))
            if len(fs) < len(eps):
                covgaps.append((r, sfx, len(fs), len(eps)))
            bad = []
            for p in fs:
                probs = check_file(p, sfx)
                if probs:
                    bad.append((p, probs))
            tot_f += len(fs); tot_bad += len(bad)
            grand_bad.extend(bad)
            flag = ("  <-- CORRUPT" if bad else
                    ("  <-- INCOMPLETE" if len(fs) < len(eps) else ""))
            lbl = f"{os.path.basename(os.path.dirname(r))}/{os.path.basename(r)}"
            print(f"  {lbl:40} {len(fs):>6} {len(eps):>5} {len(bad):>4}{flag}")
        grand_files += tot_f
        print(f"  {'TOTAL':40} {tot_f:>6} {'':>5} {tot_bad:>4}")

    print(f"\n{'='*74}")
    # An empty check is a FAILED check. Nothing below can distinguish "every file is healthy"
    # from "no file was looked at" unless this says so first.
    if grand_files == 0:
        print(f"  FAILED — 0 judge outputs found under {len(runs)} run dir(s) for "
              f"{', '.join(sfxs)}.\n"
              f"  This is a path/layout mismatch, not a clean panel. Expected\n"
              f"    <run>/<episode>/scoring/<judge>/cotsummary.json\n"
              f"  Nothing was validated; do not read this as a pass.")
        return 1
    if covgaps:
        print(f"  INCOMPLETE — {len(covgaps)} run x judge lane(s) missing judge outputs:")
        for r, sfx, nf, ne in covgaps:
            print(f"    {r}  [{sfx}]  {nf}/{ne} episodes judged  ({ne - nf} missing)")
        print("  The missing episodes are not random — they are the ones whose traces break a\n"
              "  judge — so analysing around them moves every denominator silently.")
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
    if SCHEMA_DEGRADED:
        print(f"  PARSED — {grand_files} judge outputs parsed and carry "
              f"{len(REQUIRED)} spot-checked fields.")
        print(f"  !! NOT a schema validation. The authoritative schema could not be imported "
              f"({SCHEMA_DEGRADED}),")
        print(f"     so {len(REQUIRED)} of 10 required fields were checked and NO enum validation ran.")
        print(f"     Do not cite this as 'schema-valid'. Fix the import and re-run.")
    else:
        print(f"  ALL CLEAN — {grand_files} judge outputs parsed, complete and schema-valid "
              f"({len(REQUIRED)} required fields, {len(ENUMS)} enum-checked).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
