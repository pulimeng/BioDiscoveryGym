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


FIELDS = ["identity_derivation", "validation_rigor", "codebook_response"]

def consensus(labels):
    """Majority label over N passes. Returns (label, n_votes) or (None, top_count) on a tie.
    With 3 replicates a tie means all three disagree — genuinely unresolved, not a coin flip."""
    if not labels: return None, 0
    c = Counter(labels).most_common()
    if len(c) > 1 and c[0][1] == c[1][1]: return None, c[0][1]
    return c[0][0], c[0][1]

def panel(runs, suffixes, arms):
    """N-replicate judge panel. Separates 'the label is noisy' from 'the effect is real':
    unanimity/majority rates give the self-consistency ceiling, and every downstream rate is
    reported as consensus + the spread across individual passes (the honest uncertainty band)."""
    print("=" * 78)
    print(f"  JUDGE PANEL — {len(suffixes)} passes   arms={','.join(sorted(arms)) or 'all'}")
    print("  " + "  ".join(f"p{i+1}={s}" for i, s in enumerate(suffixes)))
    if len(suffixes) % 2 == 0:
        print(f"  NOTE: {len(suffixes)} passes is EVEN — every disagreement is a tie, so only")
        print("  unanimous episodes reach consensus and the consensus rate reads LOW by")
        print("  construction. Not comparable to an odd-N consensus; use 3 passes.")
    print("=" * 78)

    for r in runs:
        loads = [load(r, s) for s in suffixes]
        keys = sorted(set.intersection(*[set(d) for d in loads])) if loads else []
        if arms: keys = [k for k in keys if arm_of(k) in arms]
        cov = "  ".join(f"p{i+1}:{len([k for k in d if not arms or arm_of(k) in arms])}"
                        for i, d in enumerate(loads))
        if not keys:
            print(f"\n  {os.path.basename(r):34} NO COMMON EPISODES  ({cov})"); continue
        model = loads[0][keys[0]].get("model", os.path.basename(r))
        # the same agent appears under both prompts, so the run dir must disambiguate
        prompt = "lean" if os.sep + "lean" + os.sep in r + os.sep else "detailed"
        complete = len({len([k for k in d if not arms or arm_of(k) in arms]) for d in loads}) == 1
        print(f"\n  {model + ' / ' + prompt:28} n={len(keys)} co-judged   ({cov})"
              + ("" if complete else "   << UNEVEN COVERAGE — panel is provisional"))

        for f in FIELDS:
            votes = {k: [d[k].get(f) for d in loads] for k in keys}
            unan = sum(1 for v in votes.values() if len(set(v)) == 1)
            tie = sum(1 for v in votes.values() if consensus(v)[0] is None)
            # mean pairwise agreement — comparable to the 2-judge numbers
            pw = tot = 0
            for v in votes.values():
                for i in range(len(v)):
                    for j in range(i + 1, len(v)):
                        tot += 1; pw += (v[i] == v[j])
            print(f"    {f:20} unanimous {unan}/{len(keys)} ({unan/len(keys)*100:3.0f}%)   "
                  f"pairwise {pw/tot*100:3.0f}%   no-majority {tie}")

        # the load-bearing rate: G2 identity data-derived, consensus vs per-pass spread
        g2 = [k for k in keys if arm_of(k) == "g2"]
        if g2:
            per = [sum(1 for k in g2 if d[k].get("identity_derivation") == "data-derived") / len(g2)
                   for d in loads]
            cons = [consensus([d[k].get("identity_derivation") for d in loads])[0] for k in g2]
            cr = sum(1 for c in cons if c == "data-derived") / len(g2)
            print(f"    → G2 data-derived: consensus {cr*100:.0f}%   "
                  f"per-pass [{', '.join(f'{p*100:.0f}%' for p in per)}]   "
                  f"spread {(max(per)-min(per))*100:.0f} pts")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("run_dirs", nargs="*", default=DEFAULT,
                    help="ladder run dirs (default: the three ladder runs)")
    ap.add_argument("--suffix", default="_cotsummary.json", help="primary judge's output suffix")
    ap.add_argument("--agree", default=None, metavar="SUFFIX_B",
                    help="also load a SECOND judge's output (this suffix) and report inter-judge "
                         "agreement instead of the distributions — the multi-judge robustness check")
    ap.add_argument("--panel", default=None, metavar="SFX1,SFX2,...",
                    help="N-replicate panel: comma list of judge suffixes. Reports unanimity, "
                         "pairwise agreement and consensus-vs-per-pass spread instead of the "
                         "distributions. Use for the 3-replicate self-consistency check.")
    ap.add_argument("--arms", default="", help="restrict to these arms, e.g. g0,g1,g2")
    args = ap.parse_args()
    runs = args.run_dirs or DEFAULT
    arms = {a.strip() for a in args.arms.split(",") if a.strip()}

    if args.panel:
        panel(runs, [s.strip() for s in args.panel.split(",") if s.strip()], arms)
        return
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
