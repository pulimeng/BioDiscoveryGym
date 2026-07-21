#!/usr/bin/env python3
"""cot_compare.py — aggregate the per-episode _cotsummary.json into a cross-model comparison.

The ladder scores tie on outcome; this surfaces HOW the models reason differently. Reads every
<run>/<episode>/*_cotsummary.json, tabulates the structured fields by model (and by arm), and
highlights the discriminating signal: identity_derivation on the BLINDED arms (G2/G3), where the
agent must derive the cancer identity from anonymized data rather than read a pre-revealed codebook.

Usage:
  python scripts/cot_compare.py results/tcga/ladder/sonnet5_20260713 \
                                results/tcga/ladder/gpt55_20260707 \
                                results/tcga/ladder/gemini35flash_20260716
  (no args → the three default ladder runs)
"""
import argparse, glob, json, os, sys
from collections import Counter, defaultdict

DEFAULT = ["results/tcga/ladder/sonnet5_20260713",
           "results/tcga/ladder/gpt55_20260707",
           "results/tcga/ladder/gemini35flash_20260716"]

def load(run_dir, suffix="_cotsummary.json"):
    """Return {label: summary} deduped by episode label, for a given judge's output suffix."""
    out = {}
    for p in glob.glob(f"{run_dir}/*/*{suffix}"):
        label = os.path.basename(p).replace(suffix, "")
        try:
            out[label] = json.load(open(p))
        except Exception as e:
            print(f"  !! {p}: {e}", file=sys.stderr)
    return out

def arm_of(label):  # g0/g1/g2/g3a/g3b
    return label.split("_")[0]

def pct_row(counts, keys, n):
    return "  ".join(f"{k}={counts.get(k,0)} ({counts.get(k,0)/n*100:.0f}%)" for k in keys) if n else "—"

def bar(counts, keys):
    return "/".join(str(counts.get(k, 0)) for k in keys)

def agreement(runs, suffix_a, suffix_b):
    """Inter-judge robustness: % agreement on identity_derivation & validation_rigor between two
    judges' outputs, per model. Addresses 'the field is a model call, not ground truth'."""
    print("=" * 78)
    print(f"  INTER-JUDGE AGREEMENT   judge A={suffix_a}   judge B={suffix_b}")
    print("=" * 78)
    fields = ["identity_derivation", "validation_rigor", "codebook_response"]
    for r in runs:
        A, B = load(r, suffix_a), load(r, suffix_b)
        both = sorted(set(A) & set(B))
        if not both:
            print(f"  {os.path.basename(r):32} no overlap (run judge B first)"); continue
        model = A[both[0]].get("model", os.path.basename(r))
        print(f"\n  {model}   (n={len(both)} episodes judged by both)")
        for fld in fields:
            agree = sum(1 for l in both if A[l].get(fld) == B[l].get(fld))
            print(f"    {fld:20} {agree}/{len(both)} agree  ({agree/len(both)*100:.0f}%)")
        # identity confusion (G2 only, the key arm)
        g2 = [l for l in both if l.split("_")[0] == "g2"]
        if g2:
            flips = [(A[l]["identity_derivation"], B[l]["identity_derivation"])
                     for l in g2 if A[l]["identity_derivation"] != B[l]["identity_derivation"]]
            print(f"    G2 identity_derivation: {len(g2)-len(flips)}/{len(g2)} agree"
                  + (f"; disagreements: {Counter(flips).most_common()}" if flips else ""))


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("run_dirs", nargs="*", default=DEFAULT,
                    help="ladder run dirs (default: the three ladder runs)")
    ap.add_argument("--suffix", default="_cotsummary.json", help="primary judge's output suffix")
    ap.add_argument("--agree", default=None, metavar="SUFFIX_B",
                    help="also load a SECOND judge's output (this suffix) and report inter-judge "
                         "agreement instead of the distributions — the multi-judge robustness check")
    args = ap.parse_args()
    runs = args.run_dirs or DEFAULT

    if args.agree:
        agreement(runs, args.suffix, args.agree)
        return

    data = {}
    for r in runs:
        d = load(r, args.suffix)
        if d:
            model = next(iter(d.values())).get("model", os.path.basename(r))
            data[model] = d
    if not data:
        sys.exit("no _cotsummary.json found — run summarize_cot.py --save first")

    models = list(data)
    ID = ["data-derived", "mixed", "recalled-prior", "not-established"]
    RIG = ["high", "medium", "low"]
    CB = ["annotated-existing", "rebuilt-from-priors", "overfit-to-revealed", "not-applicable"]

    print("=" * 78)
    print("  CoT CROSS-MODEL COMPARISON  (n =", ", ".join(f"{m}:{len(data[m])}" for m in models), ")")
    print("=" * 78)

    # ---- overall distributions ----
    print("\n## Identity derivation — ALL honest arms (G0/G1/G2)")
    print("   (G0/G1 pre-reveal the codebook, so 'recalled' is expected there; G2 is the real test)")
    for m in models:
        s = [v for k, v in data[m].items() if arm_of(k) in ("g0", "g1", "g2")]
        c = Counter(x["identity_derivation"] for x in s)
        print(f"  {m:18} {pct_row(c, ID, len(s))}")

    print("\n## Identity derivation — G2 ONLY (blinded; must DERIVE identity from data)  ← key signal")
    for m in models:
        s = [v for k, v in data[m].items() if arm_of(k) == "g2"]
        c = Counter(x["identity_derivation"] for x in s)
        print(f"  {m:18} data-derived/mixed/recalled/none = {bar(c, ID)}   (n={len(s)})")

    print("\n## Validation rigor (honest arms)   high/medium/low")
    for m in models:
        s = [v for k, v in data[m].items() if arm_of(k) in ("g0", "g1", "g2")]
        c = Counter(x["validation_rigor"] for x in s)
        print(f"  {m:18} {bar(c, RIG)}   ({pct_row(c, RIG, len(s))})")

    print("\n## Codebook response (honest arms)")
    for m in models:
        s = [v for k, v in data[m].items() if arm_of(k) in ("g0", "g1", "g2")]
        c = Counter(x["codebook_response"] for x in s)
        print(f"  {m:18} " + "  ".join(f"{k.split('-')[0]}={c.get(k,0)}" for k in CB))

    print("\n## Mean hypothesis pivots (all arms)")
    for m in models:
        piv = [x.get("num_pivots", 0) for x in data[m].values()]
        print(f"  {m:18} {sum(piv)/len(piv):.2f}  (range {min(piv)}-{max(piv)})")

    print("\n## Top reasoning_strategy tags per model")
    for m in models:
        c = Counter(x["reasoning_strategy"] for x in data[m].values())
        print(f"  {m:18} " + "  ".join(f"{tag}×{n}" for tag, n in c.most_common(4)))

    # ---- fooling arms (G3): did the mislead frame corrupt the reasoning? ----
    print("\n## G3 mislead arms — identity derivation under a false frame")
    for m in models:
        s = [v for k, v in data[m].items() if arm_of(k) in ("g3a", "g3b")]
        c = Counter(x["identity_derivation"] for x in s)
        print(f"  {m:18} data-derived/mixed/recalled/none = {bar(c, ID)}   (n={len(s)})")

    print("\n" + "=" * 78)
    print("  Per-episode fields live in <episode>/*_cotsummary.json (verdict + prose summary).")

if __name__ == "__main__":
    main()
