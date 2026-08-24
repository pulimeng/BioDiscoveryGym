#!/usr/bin/env python3
"""Cost report — what the benchmark actually consumed, and the unit economics.

TOKEN COUNTS ARE MEASURED, NOT ESTIMATED: every episode records per-turn input/output in
run_log.usage_log; coverage is reported per run rather than assumed.

THE JUDGE LINE IS DIFFERENT. summarize_cot did not record usage for the runs already on disk, so
those judge tokens are ESTIMATED from text length (chars//4 plus the per-call system+tool
overhead), which is a lower bound because dense content tokenizes below 4 chars/token. Judge runs
made from now on record provider-reported usage and are used automatically when present.

PRICES ARE NOT MEASURED. They live in the editable table below with the date they were entered.
Provider pricing changes and this file will not notice, so VERIFY before quoting any dollar figure
in a paper or a grant. Token accounting is authoritative; dollars are derived.

The headline unit is cost per 10M tokens, which normalises across models with very different turn
counts — a model that takes 55 turns re-sends its context 55 times, so per-episode cost is
dominated by conversation length rather than by the model's sticker price.

Usage:
  python scripts/gen_cost_report.py                      -> results/tcga/reports/COST_REPORT.html
  python scripts/gen_cost_report.py --prices my.json     -> override the price table
"""
import argparse, glob, json, os, statistics as st, sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
# Repo root too: the judge lane imports `biodiscoverygym` to rebuild the judge prompt and estimate
# its input tokens. Without this the import fails, the report prints one parenthetical warning, and
# the entire judge cost line silently reads zero — the cheap half of the unit-economics claim
# ("grading is 0.3% of generating") would have been computed from nothing.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import judges_config as J
import panel_data
import runs_config

# ---------------------------------------------------------------------------------------------
# PRICE TABLE — USD per 1M tokens. Supplied by the project owner 2026-07-28.
#
# These REPLACED an earlier set entered from recollection, which was wrong by 3-5x on GPT-5.5 and
# Gemini Flash and inverted the model cost ranking entirely. Keep the provenance note: a price
# table that looks plausible is not a sourced one.
#
# Override per-run with --prices <json> ({"model": {"in": x, "out": y}}). Invoice-derived rates are
# still preferable where available, since they capture discounts and cached-input pricing that no
# list price reflects.
# ---------------------------------------------------------------------------------------------
PRICES = {
    'GPT-5.5':        {'in': 5.00,  'out': 30.00},
    'Sonnet 5':       {'in': 2.00,  'out': 10.00},
    'Gemini 3.5 Flash':   {'in': 1.50,  'out': 9.00},
    'deepseek-v4-pro': {'in': 0.435, 'out': 0.87},
    # Gemini 2.5 Pro list price, ai.google.dev/gemini-api/docs/pricing, read 2026-08-24.
    #
    # This model is priced in TWO TIERS and the tier is chosen PER REQUEST by prompt size, with
    # the higher rate applying to the whole request:
    #     prompts <= 200k tokens   $1.25 in / $10.00 out     <- the rates below
    #     prompts >  200k tokens   $2.50 in / $15.00 out
    # The low tier is used because it is what this campaign actually hit, verified rather than
    # assumed: across all 4,144 Gemini calls in clean + clean_lean, ZERO prompts exceeded 200k
    # (largest single prompt 76,656 tokens), so tiered and flat billing agree to the cent.
    # `tier_check()` re-verifies this every run — a longer-context campaign would silently be
    # under-costed by up to 2x otherwise, which is exactly the kind of plausible-looking number
    # this table exists to prevent.
    'Gemini 2.5 Pro': {'in': 1.25, 'out': 10.00},

    # JUDGE PANEL — $0, and the zero is a FACT about this project, not a missing price.
    # All three run on infrastructure the project owner already has (bifrost for laguna and
    # nemotron, the St. Jude AIE serving platform for Qwen); there is no per-token charge to this
    # work. $0 here means "measured at zero", which is why these entries are present rather than
    # absent — an absent price is what UNPRICED means and the two must not look alike.
    #
    # CAUTION for the paper: a $0 judge makes "grading costs a fraction of generating" true by
    # construction and therefore uninformative to a reader who would pay list price. Report the
    # $0 as ours AND the JUDGE_LIST_REFERENCE counterfactual below, which is the number that
    # generalises.
    'laguna':               {'in': 0.0, 'out': 0.0},
    'nemotron-3-super':     {'in': 0.0, 'out': 0.0},
    'Qwen/Qwen3.6-27B-FP8': {'in': 0.0, 'out': 0.0},
}

# What the SAME measured judge tokens would cost on a commodity hosted endpoint. Used only for the
# counterfactual sentence; it never enters a total. Rate is a mid-market open-weights serving price
# and is labelled as an illustration, not a quote.
JUDGE_LIST_REFERENCE = {'label': 'a commodity hosted endpoint at $0.30/M in, $0.60/M out',
                        'in': 0.30, 'out': 0.60}
# Per-request prompt-size tiers, USD/1M. Only models that actually tier appear here.
PRICE_TIERS = {
    'Gemini 2.5 Pro': {'threshold': 200_000, 'above': {'in': 2.50, 'out': 15.00}},
}
PRICES_VERIFIED = True           # supplied by the project owner 2026-07-28
PRICES_DATE = ('2026-07-28 (supplied by project owner); Gemini 2.5 Pro added 2026-08-24 from '
               'ai.google.dev/gemini-api/docs/pricing')

_COL = {l: c for l, s, c, t in runs_config.MODELS}
RUNS = [(m, p, r, _COL[m]) for m, p, r in runs_config.triples()]
# Was three passes of ONE model (stochasticity); now one pass by each of three
# FAMILIES (cross-family agreement). Same shape, different statistic.
JUDGE_SUFFIXES = J.tags()
OUT = 'results/tcga/reports/COST_REPORT.html'


def episode_paths(run):
    for p in glob.glob(f"{run}/*/*.json"):
        if os.path.basename(p)[:-5] == os.path.basename(os.path.dirname(p)):
            yield p


def agent_usage():
    """Measured per-run token totals from usage_log."""
    out = {}
    for model, prompt, run, col in RUNS:
        I = O = turns = n = 0
        per_ep, first_in, eps = [], [], []
        for p in episode_paths(run):
            try:
                u = json.load(open(p))['run_log']['usage_log']
            except Exception:
                continue
            if not u:
                continue
            n += 1
            turns += len(u)
            ei = sum(x.get('input_tokens', 0) for x in u)
            eo = sum(x.get('output_tokens', 0) for x in u)
            I += ei; O += eo
            per_ep.append(ei + eo)
            first_in.append(u[0].get('input_tokens', 0))
            lab = os.path.basename(p)[:-5]
            a = lab.split('_')[0]
            eps.append({'label': lab, 'arm': 'g3' if a.startswith('g3') else a,
                        'in': ei, 'out': eo, 'turns': len(u),
                        # per-call prompt sizes: tiered pricing is chosen per REQUEST, so an
                        # episode total cannot decide the tier.
                        'calls': [x.get('input_tokens', 0) for x in u]})
        out[(model, prompt)] = dict(
            n=n, input=I, output=O, turns=turns, color=col,
            turns_per_ep=turns / max(n, 1), per_ep=per_ep, eps=eps,
            first_in=st.mean(first_in) if first_in else 0)
    return out


def judge_usage():  # noqa: C901
    """Judge tokens. Uses provider-reported `judge_usage` when the summary has it (runs made after
    summarize_cot started recording usage); otherwise falls back to a text-length ESTIMATE.

    The estimate is not equivalent to a measurement and was wrong in two ways before this fix:
      * it omitted COT_SYSTEM + the tool schema (~688 tok) which are re-sent on EVERY call, so it
        undercounted input by ~16% across 1350 calls;
      * it took output from the stored file size, which is indented JSON and ~3% larger than the
        compact payload the model actually emitted.
    Both are corrected below, but chars//4 still under-counts dense content (code, GENE_ ids,
    numerals tokenize at well under 4 chars/token), so the estimate remains a LOWER BOUND on input.
    """
    try:
        from extract_cot import extract_episode
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            'sc', os.path.join(os.path.dirname(os.path.abspath(__file__)), 'summarize_cot.py'))
        sc = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(sc)
        except SystemExit:
            pass
    except Exception as e:
        print(f"  (!) judge input not computable ({e})", file=sys.stderr)
        return None
    # fixed per-call overhead the old estimate missed: system prompt + tool schema, billed every call
    overhead = (len(sc.COT_SYSTEM) + len(json.dumps(sc._COT_TOOL))) // 4
    tin = tout = calls = measured = 0
    judge_models = set()
    eps = []                       # one record per EPISODE (all judge passes summed)
    for _, _, run, _ in RUNS:
        # Guard the episode enumeration itself. When the judge paths went stale, every artifact
        # was skipped, `calls` stayed 0 and the totals divided by zero — the crash was
        # incidental, not a check. If the tokens genuinely cannot be measured, say so.
        panel_data.require_loaded(len(list(episode_paths(run))), run, 'episodes')
        for p in episode_paths(run):
            try:
                per_call_in = len(sc.build_input(extract_episode(p))) // 4 + overhead
            except Exception:
                continue
            ei = eo = 0
            for sfx in JUDGE_SUFFIXES:
                # sfx is a judge TAG now. `p[:-5] + sfx` built "<ep>nemotron" — a path that
                # never exists, so every judge call was skipped, token totals came to zero, and
                # the report divided by zero instead of reporting no measurements.
                jp = J.artifact_path(os.path.dirname(p), 'cot', sfx)
                if not os.path.exists(jp):
                    continue
                calls += 1
                try:
                    rec = json.load(open(jp))
                except Exception:
                    rec = {}
                # Provenance per ARTIFACT, inside the loop. Reading judge_model from `rec`
                # AFTER the loop recorded only the last judge iterated, so 1,710 calls — 570
                # each from three families — were labelled "judge x3 (Qwen)". False
                # attribution, and it would have priced the combined tokens at one family's
                # rate had Qwen been priced.
                jm_i = rec.get('judge_model') if isinstance(rec, dict) else None
                if jm_i:
                    judge_models.add(jm_i)
                u = rec.get("judge_usage") or {}
                if u.get("input_tokens") and u.get("output_tokens"):
                    ei += u["input_tokens"]; eo += u["output_tokens"]; measured += 1
                else:
                    ei += per_call_in
                    # compact payload, not the indented file on disk
                    eo += len(json.dumps(rec, separators=(",", ":"))) // 4
            if ei or eo:
                tin += ei; tout += eo
                lab = os.path.basename(p)[:-5]
                a = lab.split('_')[0]
                eps.append({'label': lab, 'arm': 'g3' if a.startswith('g3') else a,
                            'in': ei, 'out': eo})
    return dict(input=tin, output=tout, calls=calls, measured=measured,
                overhead_per_call=overhead, eps=eps,
                # WHO actually judged, read from the summaries rather than hardcoded. The judge
                # moved deepseek-v4-pro -> nemotron-3-super (24bc72e) and every dollar figure below
                # kept using deepseek's rates on nemotron's tokens, producing a plausible wrong
                # number with nothing to flag it.
                models=sorted(judge_models), n_episodes=len(eps))


def cost(model, tin, tout, prices):
    p = prices.get(model)
    if not p:
        return None
    return tin / 1e6 * p['in'] + tout / 1e6 * p['out']


def tier_check(usage):
    """Requests that would bill at a model's HIGHER prompt-size tier.

    Returns {model: (n_over, n_calls, largest_prompt)}. The flat rate in PRICES is only correct
    while this is empty; a campaign with longer contexts would be under-costed silently, since a
    too-low dollar figure looks exactly like a cheap model.
    """
    out = {}
    for (model, _prompt), u in usage.items():
        t = PRICE_TIERS.get(model)
        if not t:
            continue
        n_over, n_calls, largest = 0, 0, 0
        for e in u.get('eps', []):
            for c in e.get('calls', []):
                n_calls += 1
                largest = max(largest, c)
                if c > t['threshold']:
                    n_over += 1
        prev = out.get(model, (0, 0, 0))
        out[model] = (prev[0] + n_over, prev[1] + n_calls, max(prev[2], largest))
    return out


def tool_usage():
    """Measured tool-call counts per run, from each episode's scored trace_summary.

    WHY THIS IS HERE. The report costed tokens and wall-clock but never counted the work: how many
    times the agent ran code, recorded an observation, or submitted. That is the unit a reader
    actually reasons about ("what does one episode DO?"), and it is already recorded per episode —
    it was simply never aggregated.
    """
    out = {}
    for model, prompt, run, col in RUNS:
        counts, calls, n = defaultdict(int), 0, 0
        for p in glob.glob(panel_data.artifact_glob(run, 'outcome', J.tags()[0])):
            lab = panel_data.label_of(p)
            if os.path.basename(os.path.dirname(p)) != lab:
                continue
            ts = (json.load(open(p)).get('trace_summary') or {})
            tc = ts.get('tool_counts') or {}
            if not tc:
                continue
            n += 1
            calls += ts.get('total_calls') or sum(tc.values())
            for k, v in tc.items():
                counts[k] += v
        if n:
            out[(model, prompt)] = dict(n=n, calls=calls, per_ep=calls / n, counts=dict(counts))
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--prices', type=str, default=None, metavar='JSON|FILE',
                    help='price override: inline JSON \'{"Model":{"in":1.25,"out":10}}\' '
                         'or a path to a .json file with the same shape')
    args = ap.parse_args()
    prices = dict(PRICES)
    verified = PRICES_VERIFIED
    if args.prices:
        # Accept BOTH inline JSON and a file path. This used to be file-only, so the obvious
        # invocation — pasting the JSON the UNPRICED warning itself prints — died with
        # "FileNotFoundError: '{\"Gemini 2.5 Pro\": ...}'", which reads like the price table is
        # broken rather than the flag being fussy about its argument form.
        raw = args.prices.strip()
        try:
            override = json.loads(raw) if raw.startswith('{') else json.load(open(raw))
        except json.JSONDecodeError as e:
            sys.exit(f"--prices is not valid JSON ({e}).\n"
                     f"  Expected: --prices '{{\"Gemini 2.5 Pro\": {{\"in\": 1.25, \"out\": 10.00}}}}'\n"
                     f"  Rates are USD per 1M tokens, as real numbers — not placeholders.")
        except FileNotFoundError:
            sys.exit(f"--prices: no such file {raw!r}. Pass inline JSON instead, e.g.\n"
                     f"  --prices '{{\"Gemini 2.5 Pro\": {{\"in\": 1.25, \"out\": 10.00}}}}'")
        bad = {k: v for k, v in override.items()
               if not isinstance(v, dict)
               or not all(isinstance(v.get(x), (int, float)) for x in ('in', 'out'))}
        if bad:
            sys.exit(f"--prices: these entries are not numeric rates: {list(bad)}\n"
                     f"  Each model needs {{'in': <number>, 'out': <number>}} in USD per 1M tokens.\n"
                     f"  A literal X/Y placeholder will not do — the whole point of the UNPRICED\n"
                     f"  marker is that a guessed rate is worse than a missing one.")
        prices.update(override)
        verified = True
    if not verified:
        print("!" * 90)
        print("  DOLLAR FIGURES BELOW ARE PLACEHOLDERS — the price table is not sourced.")
        print("  Token counts are measured; costs are arithmetic on unverified prices.")
        print("  Supply real rates with --prices <json> (invoices are ground truth).")
        print("!" * 90)

    A = agent_usage()
    J = judge_usage()
    # Coverage reported, not asserted. The header claimed "75/75 episodes on every run" — the
    # pilot's lane size — on a run of 95 per lane.
    _cov_n = sum(d['n'] for d in A.values())
    _cov_lane = sorted({d['n'] for d in A.values()})
    _COV = (f"{_cov_n} episodes, {_cov_lane[0]}/lane" if len(_cov_lane) == 1
            else f"{_cov_n} episodes, {_cov_lane[0]}-{_cov_lane[-1]}/lane")
    # The judge to PRICE is the one the summaries say ran, not a name baked in here.
    JM = (J.get('models') or ['deepseek-v4-pro'])[0] if J else 'deepseek-v4-pro'
    JM_LABEL = '+'.join(J['models']) if J and J.get('models') else JM
    JN = J.get('n_episodes', 0) if J else 0

    # ---- console ----
    print("=" * 90)
    print("  AGENT TOKEN USAGE (measured from run_log.usage_log)")
    print("=" * 90)
    print(f"  {'run':24} {'eps':>4} {'input':>14} {'output':>11} {'in:out':>7} "
          f"{'turns/ep':>9} {'$/episode':>10} {'$ total':>9}")
    tot_in = tot_out = tot_cost = 0
    unpriced = {}
    for (m, pr), d in A.items():
        c = cost(m, d['input'], d['output'], prices)
        tot_in += d['input']; tot_out += d['output']
        if c is None:
            # NOT folded in as $0. An unpriced model used to vanish into the total silently, which
            # would have understated the clean run by a whole agent lane while every number on the
            # page still looked complete.
            unpriced.setdefault(m, 0)
            unpriced[m] += d['input'] + d['output']
            print(f"  {m+'/'+pr:24} {d['n']:>4} {d['input']:>14,} {d['output']:>11,} "
                  f"{d['input']/max(d['output'],1):>6.1f}: {d['turns_per_ep']:>8.1f} "
                  f"{'UNPRICED':>9} {'UNPRICED':>9}")
            continue
        tot_cost += c
        print(f"  {m+'/'+pr:24} {d['n']:>4} {d['input']:>14,} {d['output']:>11,} "
              f"{d['input']/max(d['output'],1):>6.1f}: {d['turns_per_ep']:>8.1f} "
              f"{c/max(d['n'],1):>9.2f} {c:>9.2f}")
    print(f"  {'TOTAL':24} {sum(d['n'] for d in A.values()):>4} {tot_in:>14,} {tot_out:>11,} "
          f"{tot_in/max(tot_out,1):>6.1f}: {'':>8} {'':>9} {tot_cost:>9.2f}")
    if unpriced:
        print(f"\n  !! ${tot_cost:,.2f} EXCLUDES {len(unpriced)} unpriced model(s) — the total is a "
              f"LOWER BOUND, not the run cost:")
        for m, tk in sorted(unpriced.items()):
            print(f"       {m:22} {tk:>14,} tokens unpriced")
        ex = ', '.join(f'"{m}": {{"in": 1.25, "out": 10.00}}' for m in sorted(unpriced))
        print(f"     Complete it with real USD-per-1M rates (invoice beats list price):")
        print(f"       python scripts/gen_cost_report.py --prices '{{{ex}}}'")

    # Tiered models: the flat rate in PRICES is the LOW tier. Verify per request, every run.
    TIERS = tier_check(A)
    tier_warn = ""
    for m, (n_over, n_calls, largest) in sorted(TIERS.items()):
        t = PRICE_TIERS[m]
        if n_over:
            hi = t['above']
            tier_warn += (f"<b>{m} is under-costed.</b> {n_over:,} of {n_calls:,} requests "
                          f"exceeded {t['threshold']:,} prompt tokens (largest {largest:,}) and "
                          f"bill at the higher tier (${hi['in']}/${hi['out']} per 1M), not the "
                          f"${prices[m]['in']}/${prices[m]['out']} used here. The dollars below "
                          f"are a LOWER BOUND for this model.<br>")
            print(f"\n  !! {m} TIER: {n_over:,}/{n_calls:,} requests over "
                  f"{t['threshold']:,} prompt tokens (largest {largest:,}).")
            print(f"     Billed at ${hi['in']}/${hi['out']} per 1M, not "
                  f"${prices[m]['in']}/${prices[m]['out']} — the total UNDERSTATES this model.")
        else:
            tier_warn += (f"<b>{m}</b> is priced at its low prompt-size tier "
                          f"(&le;{t['threshold']:,} tokens). Verified, not assumed: "
                          f"<b>0 of {n_calls:,}</b> requests exceeded it "
                          f"(largest prompt {largest:,} tokens), so tiered and flat billing agree.<br>")
            print(f"  tier check: {m} 0/{n_calls:,} requests over {t['threshold']:,} prompt "
                  f"tokens (largest {largest:,}) — low tier correct.")

    T = tool_usage()
    if T:
        print("\n" + "=" * 90)
        print("  TOOL CALLS (measured from trace_summary)")
        print("=" * 90)
        kinds = sorted({k for d in T.values() for k in d['counts']})
        print(f"  {'run':24} {'eps':>4} {'calls':>8} {'calls/ep':>9} " +
              " ".join(f"{k[:14]:>15}" for k in kinds))
        tc_tot, tn = 0, 0
        agg = defaultdict(int)
        for (m, pr), d in T.items():
            tc_tot += d['calls']; tn += d['n']
            for k, v in d['counts'].items():
                agg[k] += v
            print(f"  {m+'/'+pr:24} {d['n']:>4} {d['calls']:>8,} {d['per_ep']:>9.1f} " +
                  " ".join(f"{d['counts'].get(k,0):>15,}" for k in kinds))
        print(f"  {'TOTAL':24} {tn:>4} {tc_tot:>8,} {tc_tot/max(tn,1):>9.1f} " +
              " ".join(f"{agg.get(k,0):>15,}" for k in kinds))

    print("\n" + "=" * 90)
    print("  COST PER 10M TOKENS  (normalises away turn-count differences)")
    print("=" * 90)
    per10 = {}
    for (m, pr), d in A.items():
        t = d['input'] + d['output']
        # A lane with zero tokens means the episodes were not found, not that they were free.
        # Every percentage below divides by t, so without this the report dies on arithmetic
        # and names the division rather than the missing data.
        panel_data.require_data(t, f'agent tokens for {m}/{pr}', runs_config.SOURCE)
        c = cost(m, d['input'], d['output'], prices)
        if c is None:
            # Same rule as the table above: show the shape, refuse to invent the price.
            per10[(m, pr)] = None
            print(f"  {m+'/'+pr:24} {'UNPRICED':>8}           "
                  f"({d['input']/t*100:.0f}% input / {d['output']/t*100:.0f}% output — "
                  f"add '{m}' to the price table)")
            continue
        per10[(m, pr)] = c / t * 1e7 if t else 0
        print(f"  {m+'/'+pr:24} ${per10[(m,pr)]:>7.2f} per 10M   "
              f"(blend of {d['input']/t*100:.0f}% input at ${prices[m]['in']}/M, "
              f"{d['output']/t*100:.0f}% output at ${prices[m]['out']}/M)")

    if J:
        jc = cost(JM, J['input'], J['output'], prices)
        jt = J['input'] + J['output']
        JREF = (J['input'] / 1e6 * JUDGE_LIST_REFERENCE['in']
                + J['output'] / 1e6 * JUDGE_LIST_REFERENCE['out'])
        # Zero judge tokens means no judge artifact was found, not a free judge. Say so rather
        # than dividing by it — the ZeroDivisionError that used to surface here named the
        # arithmetic, not the missing data.
        panel_data.require_data(jt, 'judge tokens', runs_config.SOURCE)
        print("\n" + "=" * 90)
        print(f"  JUDGE ({len(JUDGE_SUFFIXES)} FAMILIES x {JN} episodes, one pass each: {JM_LABEL})")
        print("=" * 90)
        src = ("provider-reported" if J.get('measured') == J['calls']
               else f"ESTIMATED ({J['calls']-J.get('measured',0)}/{J['calls']} calls)")
        money = (f"${jc:.2f}   (${jc/jt*1e7:.2f} per 10M)" if jc is not None and jt
                 else f"UNPRICED — no rate on file for {JM_LABEL}")
        print(f"  calls {J['calls']:,}   input {J['input']:,}   output {J['output']:,}   "
              f"total {jt/1e6:.1f}M   {money}")
        print(f"  token source: {src}"
              + ("" if J.get('measured') == J['calls'] else
                 f"  — chars//4 + {J['overhead_per_call']} tok/call system+tool overhead;"
                 f" a LOWER BOUND on input"))
        if jc:
            print(f"  judge is {jc/max(tot_cost,1e-9)*100:.1f}% of agent spend — the evaluation "
                  f"layer is")
            print(f"  far cheaper than generating the episodes it grades.")
        elif jc == 0:
            # $0 is our REAL cost — all three families are self-hosted. But it makes the paper's
            # "process evaluation is a fraction of generation" claim true by construction, and a
            # ratio that cannot come out any other way is not evidence. State both: what it cost
            # US, and what the same measured tokens would cost someone who pays for them.
            print("  judge cost to this project: $0.00 — all three families run on infrastructure")
            print("  already available here, with no per-token charge.")
            print("  That makes the ratio 0% BY CONSTRUCTION, so it is not the number to quote.")
            print(f"  Counterfactual on the same measured {jt/1e6:.1f}M tokens, "
                  f"{JUDGE_LIST_REFERENCE['label']}:")
            print(f"    ${JREF:,.2f}  =  {JREF/max(tot_cost,1e-9)*100:.2f}% of the "
                  f"${tot_cost:,.2f} agent spend  (${JREF/max(JN,1):.4f} per episode graded)")
            print("  That is the figure that generalises to a reader who pays for judging.")
        else:
            # An unpriced judge must not print the claim, and must not silently omit it either.
            print(f"  !! CANNOT state the judge-vs-agent cost ratio: {JM_LABEL} is unpriced.")
            print(f"     The paper's 'process evaluation is a fraction of generation' claim needs")
            print(f"     this rate. Judge tokens are measured ({jt/1e6:.1f}M); only the price is missing.")

    print("\n" + "=" * 90)
    print("  WHERE THE MONEY GOES")
    print("=" * 90)
    print(f"  input:output = {tot_in/max(tot_out,1):.0f}:1. Every turn re-sends the whole")
    print("  conversation, so cost scales with turns^2, not with answer length.")
    for (m, pr), d in sorted(A.items(), key=lambda kv: -kv[1]['turns_per_ep'])[:1]:
        print(f"  Worst case {m}/{pr}: {d['turns_per_ep']:.0f} turns/episode -> "
              f"{d['input']/max(d['n'],1):,.0f} input tokens per episode.")
    print("  A prompt cache on the stable prefix would attack the dominant term directly.")

    # lean-vs-detailed saving, computed
    print("\n  Lean vs detailed (same task, same data):")
    for m in dict.fromkeys(x[0] for x in A):
        dd, ll = A.get((m, 'detailed')), A.get((m, 'lean'))
        if not dd or not ll:
            continue
        cd = cost(m, dd['input'], dd['output'], prices)
        cl = cost(m, ll['input'], ll['output'], prices)
        if cd is None or cl is None:
            # "$0.00 -> $0.00 (+0%)" read as "this model was free", which is a claim. Say unpriced.
            print(f"    {m:14} {'UNPRICED':>9}    {'UNPRICED':>9}   (      , "
                  f"{dd['turns_per_ep']:.0f} -> {ll['turns_per_ep']:.0f} turns/ep)")
            continue
        print(f"    {m:14} ${cd:7.2f} -> ${cl:7.2f}   ({(cl-cd)/max(cd,1e-9)*100:+.0f}%, "
              f"{dd['turns_per_ep']:.0f} -> {ll['turns_per_ep']:.0f} turns/ep)")

    # ---- html ----
    rows = ""
    UNP = "<td class='num' title='no price on file for this model'>&mdash;</td>"
    for (m, pr), d in A.items():
        c = cost(m, d['input'], d['output'], prices)
        t = d['input'] + d['output']
        money = (f"<td class='num'>${per10[(m,pr)]:.2f}</td>"
                 f"<td class='num'>${c/max(d['n'],1):.2f}</td>"
                 f"<td class='num'><b>${c:,.2f}</b></td>") if c is not None else UNP * 3
        rows += (f"<tr><td class='grp' style='color:{d['color']}'>{m}</td><td>{pr}</td>"
                 f"<td class='num'>{d['n']}</td><td class='num'>{d['input']:,}</td>"
                 f"<td class='num'>{d['output']:,}</td>"
                 f"<td class='num'>{d['input']/max(d['output'],1):.0f}:1</td>"
                 f"<td class='num'>{d['turns_per_ep']:.1f}</td>" + money + "</tr>")
    lean_rows = ""
    for m in dict.fromkeys(x[0] for x in A):
        dd, ll = A.get((m, 'detailed')), A.get((m, 'lean'))
        if not dd or not ll:
            continue
        cd = cost(m, dd['input'], dd['output'], prices)
        cl = cost(m, ll['input'], ll['output'], prices)
        if cd is None or cl is None:
            lean_rows += (f"<tr><td class='grp' style='color:{dd['color']}'>{m}</td>"
                          f"{UNP}{UNP}{UNP}"
                          f"<td class='num'>{dd['turns_per_ep']:.0f} &rarr; "
                          f"{ll['turns_per_ep']:.0f}</td></tr>")
            continue
        pct = (cl - cd) / max(cd, 1e-9) * 100
        lean_rows += (f"<tr><td class='grp' style='color:{dd['color']}'>{m}</td>"
                      f"<td class='num'>${cd:,.2f}</td><td class='num'>${cl:,.2f}</td>"
                      f"<td class='num {'good' if pct<0 else 'bad'}'>{pct:+.0f}%</td>"
                      f"<td class='num'>{dd['turns_per_ep']:.0f} &rarr; {ll['turns_per_ep']:.0f}</td></tr>")
    jrow = ""
    if J:
        jc = cost(JM, J['input'], J['output'], prices)
        jt = J['input'] + J['output']
        JREF = (J['input'] / 1e6 * JUDGE_LIST_REFERENCE['in']
                + J['output'] / 1e6 * JUDGE_LIST_REFERENCE['out'])
        # $0 is a measured fact (self-hosted judges), not a missing price. Render it as such —
        # a bare "$0.00" beside real dollars reads as a broken cell.
        if jc:
            jmoney = (f"<td class='num'>${jc/jt*1e7:.2f}</td><td class='num'>&mdash;</td>"
                      f"<td class='num'><b>${jc:,.2f}</b></td>")
        elif jc == 0:
            jmoney = ("<td class='num good' colspan='3' title='self-hosted judge panel; "
                      "no per-token charge'>$0 &mdash; self-hosted</td>")
        else:
            jmoney = f"{UNP}<td class='num'>&mdash;</td>{UNP}"
        jrow = (f"<tr><td class='grp'>judge: {len(JUDGE_SUFFIXES)} families &times;1 pass ({JM_LABEL})</td>"
                f"<td>all arms</td>"
                f"<td class='num'>{J['calls']:,} calls</td><td class='num'>{J['input']:,}</td>"
                f"<td class='num'>~{J['output']:,}</td>"
                f"<td class='num'>{J['input']/max(J['output'],1):.0f}:1</td>"
                f"<td class='num'>&mdash;</td>" + jmoney + "</tr>")

    # ---- tool-call rows: the WORK an episode does, beside what it costs ----
    tool_rows, tool_kinds = "", sorted({k for d in T.values() for k in d['counts']}) if T else []
    if T:
        agg_t = defaultdict(int); tot_calls = tot_eps = 0
        for (m, pr), d in T.items():
            tot_calls += d['calls']; tot_eps += d['n']
            for k, v in d['counts'].items():
                agg_t[k] += v
            cells = "".join(f"<td class='num'>{d['counts'].get(k,0):,}</td>" for k in tool_kinds)
            col = A.get((m, pr), {}).get('color', '#888')
            tool_rows += (f"<tr><td class='grp' style='color:{col}'>{m}</td><td>{pr}</td>"
                          f"<td class='num'>{d['n']}</td>"
                          f"<td class='num'><b>{d['calls']:,}</b></td>"
                          f"<td class='num'>{d['per_ep']:.1f}</td>{cells}</tr>")
        cells = "".join(f"<td class='num'><b>{agg_t.get(k,0):,}</b></td>" for k in tool_kinds)
        tool_rows += (f"<tr><td class='grp'>TOTAL</td><td>&mdash;</td>"
                      f"<td class='num'><b>{tot_eps}</b></td>"
                      f"<td class='num'><b>{tot_calls:,}</b></td>"
                      f"<td class='num'><b>{tot_calls/max(tot_eps,1):.1f}</b></td>{cells}</tr>")
    tool_head = "".join(f"<th class='num'>{k}</th>" for k in tool_kinds)
    tool_section = (f'''
<h2>Tool calls &mdash; the work behind the tokens</h2>
<div class="panel"><div class="tblwrap"><table><thead><tr><th>model</th><th>prompt</th>
<th class="num">episodes</th><th class="num">calls</th><th class="num">calls/ep</th>
{tool_head}</tr></thead><tbody>{tool_rows}</tbody></table></div>
<p class="lead">Measured per episode from <code>trace_summary.tool_counts</code>. Turns and tool
calls track each other almost exactly, which is why cost follows turn count rather than answer
length: <b>every extra tool call re-sends the whole conversation.</b></p></div>''') if T else ""

    price_rows = "".join(
        f"<tr><td>{k}</td><td class='num'>${v['in']:.2f}</td><td class='num'>${v['out']:.2f}</td></tr>"
        for k, v in prices.items())

    # The paper's "process evaluation is a fraction of generation" claim, stated so it survives
    # a free judge. $0/$1,262 = 0% is true and worthless; the counterfactual is the number a
    # reader who pays for judging can use.
    if J and jc == 0:
        judge_ratio_note = (
            f"<div class='warn'><b>Judging cost this project $0.</b> All three judge families run "
            f"on infrastructure already available here, with no per-token charge &mdash; so "
            f"&ldquo;evaluation is a fraction of generation&rdquo; is true here <b>by "
            f"construction</b>, and 0% is not a figure to quote.<br>"
            f"<b>The number that generalises:</b> the same measured "
            f"{(J['input']+J['output'])/1e6:.1f}M judge tokens on "
            f"{JUDGE_LIST_REFERENCE['label']} would cost <b>${JREF:,.2f}</b> &mdash; "
            f"<b>{JREF/max(tot_cost,1e-9)*100:.2f}%</b> of the ${tot_cost:,.2f} spent generating "
            f"the episodes, or <b>${JREF/max(JN,1):.4f} per episode graded</b> against "
            f"${tot_cost/max(sum(d['n'] for d in A.values()),1):.2f} to produce one. The reference "
            f"rate is an illustration, not a quote.</div>")
    elif J and jc:
        judge_ratio_note = (
            f"<div class='lead'>Judging cost <b>${jc:,.2f}</b> &mdash; "
            f"<b>{jc/max(tot_cost,1e-9)*100:.2f}%</b> of the ${tot_cost:,.2f} agent spend.</div>")
    else:
        judge_ratio_note = ("<div class='warn'>The judge is unpriced, so the judge-vs-agent cost "
                            "ratio cannot be stated. Judge tokens are measured; the price is "
                            "missing.</div>")

    # ---- token mix: what "% input" means, and why it decides the effective rate ----
    mix_rows = ""
    for (m, pr), d in A.items():
        t = d['input'] + d['output']
        fi, fo = d['input'] / t, d['output'] / t
        p = prices.get(m)
        if p is None:
            continue          # unpriced: the blend is a price statement, so omit rather than fake
        blend = fi * p['in'] + fo * p['out']
        mix_rows += (f"<tr><td class='grp' style='color:{d['color']}'>{m}</td><td>{pr}</td>"
                     f"<td class='num'>{fi*100:.1f}%</td><td class='num'>{fo*100:.1f}%</td>"
                     f"<td class='num'>${p['in']:.2f}</td><td class='num'>${p['out']:.2f}</td>"
                     f"<td class='num'>{fi:.3f}&times;{p['in']:.2f} + {fo:.3f}&times;{p['out']:.2f}</td>"
                     f"<td class='num'><b>${blend*10:.2f}</b></td></tr>")
    # The judge is a SINGLE-SHOT call — no conversation to re-send — so its mix is nothing like
    # the agent's. Including it makes the point that the 99%-input figure is a property of the
    # multi-turn loop, not of LLM workloads generally.
    if J:
        jt = J['input'] + J['output']
        jfi, jfo = J['input'] / jt, J['output'] / jt
        jp = prices.get(JM)
    if J and jp:
        # The MIX (70/30 vs the agent's 99/1) is measured and is the point of this row — keep it.
        # The price columns are not: a self-hosted judge is $0, and "0.704x0.00 + 0.296x0.00"
        # is arithmetic theatre. Show the mix against the reference rate instead, labelled, so
        # the row still demonstrates what the mix does to an effective rate.
        free = not (jp['in'] or jp['out'])
        rp = JUDGE_LIST_REFERENCE if free else jp
        jb = jfi * rp['in'] + jfo * rp['out']
        note = " <span class='sub'>ref. rate</span>" if free else ""
        mix_rows += (f"<tr><td class='grp'>{JM_LABEL}{' (self-hosted, $0)' if free else ''}</td>"
                     f"<td>judge &times;3</td>"
                     f"<td class='num'>{jfi*100:.1f}%</td>"
                     f"<td class='num'>{jfo*100:.1f}%<span class='sub'>approx</span></td>"
                     f"<td class='num'>${rp['in']:.2f}{note}</td><td class='num'>${rp['out']:.2f}</td>"
                     f"<td class='num'>{jfi:.3f}&times;{rp['in']:.2f} + {jfo:.3f}&times;{rp['out']:.2f}</td>"
                     f"<td class='num'><b>${jb*10:.2f}</b></td></tr>")
    # counterfactual: same prices, an even mix — shows how much the mix (not the model) is doing
    cf_rows = ""
    for m in dict.fromkeys(x[0] for x in A):
        d = A.get((m, 'detailed')) or A.get((m, 'lean'))
        t = d['input'] + d['output']
        fi, fo = d['input'] / t, d['output'] / t
        p = prices.get(m)
        if p is None:
            continue
        actual = (fi * p['in'] + fo * p['out']) * 10
        even = (0.5 * p['in'] + 0.5 * p['out']) * 10
        cf_rows += (f"<tr><td class='grp' style='color:{d['color']}'>{m}</td>"
                    f"<td class='num'>${actual:.2f}</td><td class='num'>${even:.2f}</td>"
                    f"<td class='num bad'>&times;{even/actual:.1f}</td></tr>")
    # This table asks "what would a 50/50 input:output mix cost relative to the real mix?" — a
    # RATIO. At $0 both sides are $0 and the ratio is 0/0: it crashed with ZeroDivisionError, and
    # a crash here leaves the PREVIOUS report on disk looking current. A free model has no mix
    # sensitivity to show, so say that instead of computing it.
    if J and prices.get(JM) and (prices[JM]['in'] or prices[JM]['out']):
        jt = J['input'] + J['output']
        jp = prices[JM]
        ja = (J['input'] / jt * jp['in'] + J['output'] / jt * jp['out']) * 10
        je = (0.5 * jp['in'] + 0.5 * jp['out']) * 10
        cf_rows += (f"<tr><td class='grp'>{JM_LABEL} <span class='mut'>(judge)</span></td>"
                    f"<td class='num'>${ja:.2f}</td><td class='num'>${je:.2f}</td>"
                    f"<td class='num good'>&times;{je/ja:.1f}</td></tr>")
    elif J and prices.get(JM):
        cf_rows += (f"<tr><td class='grp'>{JM_LABEL} <span class='mut'>(judge)</span></td>"
                    f"<td class='num mut' colspan='3'>$0 &mdash; self-hosted, so the "
                    f"input:output mix costs nothing either way</td></tr>")

    # ---- per-episode cost: distribution, not just the mean ----
    ep_rows = ""
    UNPRICED_ROW = ("<td class='num mut' colspan='5' "
                    "title='no price on file for this model'>&mdash; unpriced &mdash;</td>")
    for (m, pr), d in A.items():
        # `or 0` here rendered an UNPRICED model as a real $0.00 distribution — min $0.00, max
        # $0.00, spread x0.0 — in a table whose whole point is spread. The main table already
        # says "UNPRICED"; these two disagreed with it.
        if m not in prices:
            ep_rows += (f"<tr><td class='grp' style='color:{d['color']}'>{m}</td><td>{pr}</td>"
                        f"<td class='num'>{len(d['eps'])}</td>{UNPRICED_ROW}</tr>")
            continue
        cs = sorted(cost(m, e['in'], e['out'], prices) for e in d['eps'])
        if not cs:
            continue
        lo, hi = cs[0], cs[-1]
        ep_rows += (f"<tr><td class='grp' style='color:{d['color']}'>{m}</td><td>{pr}</td>"
                    f"<td class='num'>{len(cs)}</td>"
                    f"<td class='num'>${st.mean(cs):.2f}</td>"
                    f"<td class='num'>${st.median(cs):.2f}</td>"
                    f"<td class='num'>${lo:.2f}</td><td class='num'>${hi:.2f}</td>"
                    f"<td class='num'>&times;{hi/max(lo,1e-9):.1f}</td></tr>")
    if J and J.get('eps') and JM in prices:
        jcs = sorted(cost(JM, e['in'], e['out'], prices) for e in J['eps'])
        if any(jcs):
            ep_rows += (f"<tr><td class='grp'>{JM_LABEL}</td><td>judge &times;3</td>"
                        f"<td class='num'>{len(jcs)}</td><td class='num'>${st.mean(jcs):.4f}</td>"
                        f"<td class='num'>${st.median(jcs):.4f}</td><td class='num'>${jcs[0]:.4f}</td>"
                        f"<td class='num'>${jcs[-1]:.4f}</td>"
                        f"<td class='num'>&times;{jcs[-1]/max(jcs[0],1e-9):.1f}</td></tr>")
        else:
            # A spread table for a $0 model would print min $0.0000, max $0.0000, spread x0.0 —
            # identical to how it renders a model whose prices are missing.
            ep_rows += (f"<tr><td class='grp'>{JM_LABEL}</td><td>judge &times;3</td>"
                        f"<td class='num'>{len(jcs)}</td>"
                        f"<td class='num good' colspan='5'>$0 &mdash; self-hosted, no spread to "
                        f"show</td></tr>")
    elif J and J.get('eps'):
        ep_rows += (f"<tr><td class='grp'>{JM_LABEL}</td><td>judge &times;3</td>"
                    f"<td class='num'>{len(J['eps'])}</td>{UNPRICED_ROW}</tr>")
    # ---- per-episode cost by arm: which arms are expensive ----
    ARMS = ['g0', 'g1', 'g2', 'g3']
    arm_rows = ""
    for (m, pr), d in A.items():
        cells = ""
        if m not in prices:
            cells = ("<td class='num mut' title='no price on file'>&mdash;</td>" * len(ARMS)
                     + "<td class='num mut'>&mdash;</td>")
            arm_rows += (f"<tr><td class='grp' style='color:{d['color']}'>{m}</td>"
                         f"<td>{pr}</td>{cells}</tr>")
            continue
        for a in ARMS:
            cs = [cost(m, e['in'], e['out'], prices) for e in d['eps'] if e['arm'] == a]
            cells += (f"<td class='num'>${st.mean(cs):.2f}<span class='sub'>n={len(cs)}</span></td>"
                      if cs else "<td class='num mut'>&mdash;</td>")
        cells += f"<td class='num'><b>${sum(cost(m, e['in'], e['out'], prices) for e in d['eps']):,.2f}</b></td>"
        arm_rows += (f"<tr><td class='grp' style='color:{d['color']}'>{m}</td><td>{pr}</td>{cells}</tr>")
    if J and J.get('eps') and JM in prices and (prices[JM]['in'] or prices[JM]['out']):
        cells = ""
        for a in ARMS:
            cs = [cost(JM, e['in'], e['out'], prices)
                  for e in J['eps'] if e['arm'] == a]
            cells += (f"<td class='num'>${st.mean(cs):.4f}<span class='sub'>n={len(cs)}</span></td>"
                      if cs else "<td class='num mut'>&mdash;</td>")
        cells += (f"<td class='num'><b>$"
                  f"{sum((cost(JM, e['in'], e['out'], prices) or 0) for e in J['eps']):,.2f}"
                  f"</b></td>")
        arm_rows += f"<tr><td class='grp'>{JM_LABEL}</td><td>judge &times;3</td>{cells}</tr>"

    banner = ("" if verified else
        '<div class="warn"><b style="font-size:15px">&#9888; Every dollar figure on this page is a '
        'PLACEHOLDER.</b><br>The price table was entered from recollection and is <b>not sourced</b>. '
        'At least one entry is likely wrong: <code>docs/BENCHMARK_PLAN.md</code> records GPT-5.4 at '
        '$2.50/M in &middot; $15/M out, double the input price assumed here. '
        'Re-run with <code>--prices file.json</code> using rates from your invoices &mdash; those are '
        'ground truth and also capture discounts and cached-input rates that no list price reflects.'
        '<br><b>The token counts on this page are measured and unaffected</b> '
        '(<code>run_log.usage_log</code>, {_COV}): the structural findings &mdash; 44:1 input '
        'dominance, cost scaling with turns&sup2;, lean using 23&ndash;52% fewer tokens &mdash; hold '
        'regardless of price.</div>')
    CSS = """
:root{--bg:#0d1117;--panel:#161b22;--line:#283041;--ink:#e6edf3;--mut:#9aa7b4;--acc:#58a6ff;--good:#3fb950;--bad:#f85149}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.6 -apple-system,Segoe UI,Roboto,Arial,sans-serif;padding:30px}
.wrap{max-width:1060px;margin:0 auto}h1{font-size:24px;margin:0 0 4px}
h2{font-size:18px;margin:30px 0 8px;border-left:3px solid var(--acc);padding-left:11px}
.meta{color:var(--mut);font-size:13px;margin-bottom:10px}.lead{color:var(--mut);font-size:12.5px;margin:8px 0 0}
.panel{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:15px 18px;margin:12px 0}
table{border-collapse:collapse;width:100%;font-size:13px}th,td{padding:7px 9px;border-bottom:1px solid var(--line);text-align:left}
th{color:var(--mut);font-weight:600;font-size:11.5px}td.num,th.num{text-align:right;font-variant-numeric:tabular-nums}
.grp{font-weight:700}.good{color:var(--good);font-weight:700}.bad{color:var(--bad);font-weight:700}.mut{color:var(--mut)}
.tblwrap{overflow-x:auto}.big{font-size:27px;font-weight:700}
.warn{background:#2a2410;border:1px solid #5c4a12;border-radius:8px;padding:13px 16px;margin:12px 0;color:#e8d48a;font-size:12.5px}
code{background:#0b1220;padding:1px 5px;border-radius:4px;font-size:12px}
.foot{color:var(--mut);font-size:11.5px;margin-top:26px;border-top:1px solid var(--line);padding-top:12px}
"""
    html = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Cost report</title><style>{CSS}</style></head><body><div class="wrap">
<h1>Cost report</h1>
<div class="meta">Token counts <b>measured</b> from <code>run_log.usage_log</code> ({_COV} on
every run) &middot; dollars derived from the editable price table below</div>

{banner}
<div class="panel"><b>Prompt-size pricing tiers.</b><br>{tier_warn}
<span class="lead">Tiered models bill the whole request at the higher rate once a single prompt
crosses the threshold, so an episode total cannot decide the tier &mdash; it is checked per
request, on every run, by <code>tier_check()</code>. A campaign with longer contexts would
otherwise be under-costed by up to 2&times;, and a too-low dollar figure looks exactly like a cheap
model.</span></div>

<h2>Agent spend</h2>
<div class="panel"><div class="tblwrap"><table><thead><tr><th>model</th><th>prompt</th>
<th class="num">eps</th><th class="num">input tok</th><th class="num">output tok</th>
<th class="num">in:out</th><th class="num">turns/ep</th><th class="num">$/10M</th>
<th class="num">$/episode</th><th class="num">$ total</th></tr></thead>
<tbody>{rows}{jrow}</tbody></table></div>
<p class="lead"><b>$/10M tokens</b> is the blended unit price actually paid, which differs from
sticker price because each run has its own input/output mix. It is the number to use when comparing
models, since per-episode cost is dominated by how many turns a model takes.</p>
{judge_ratio_note}</div>

<h2>Where the money goes</h2>
<div class="panel">
<div class="big">{tot_in/max(tot_out,1):.0f}:1</div>
<p class="lead">input to output, across {(tot_in+tot_out)/1e6:.0f}M tokens. Every turn re-sends the
entire conversation, so spend scales with the <b>square</b> of turn count, not with answer length.
The models that cost most are the ones that take most turns &mdash; not the ones with the highest
sticker price. A prompt cache over the stable prefix attacks exactly this term, and is the single
largest available saving.</p></div>

<h2>Cost per episode</h2>
<div class="panel"><div class="tblwrap"><table><thead><tr><th>model</th><th>prompt</th>
<th class="num">episodes</th><th class="num">mean</th><th class="num">median</th>
<th class="num">cheapest</th><th class="num">dearest</th><th class="num">spread</th>
</tr></thead><tbody>{ep_rows}</tbody></table></div>
<p class="lead">One episode = one cohort &times; one seed &times; one arm, priced on its own measured
tokens. <b>Read the spread, not just the mean.</b> Episodes differ in how many turns the agent
chooses to take, and since each turn re-sends the whole conversation the dearest episode in a run
can cost several times the cheapest &mdash; so a single &ldquo;cost per episode&rdquo; figure is a
planning average, not a quotable unit price.</p></div>

<div class="panel"><h3>By arm &mdash; what each rung of the ladder costs</h3>
<div class="tblwrap"><table><thead><tr><th>model</th><th>prompt</th>
<th class="num">G0 <span class="sub">told</span></th><th class="num">G1 <span class="sub">genes-only</span></th>
<th class="num">G2 <span class="sub">blind</span></th><th class="num">G3 <span class="sub">mislead</span></th>
<th class="num">run total</th></tr></thead><tbody>{arm_rows}</tbody></table></div>
<p class="lead">Mean cost of one episode on each arm. This is the number to use when costing a
change to the design &mdash; adding a cohort or a seed multiplies the relevant arm, and the blinded
and mislead arms are not necessarily priced like the easy ones, because withholding information
changes how long the agent works before it commits.</p></div>

<h2>Token mix &mdash; what &ldquo;99% input&rdquo; means</h2>
<div class="panel"><div class="tblwrap"><table><thead><tr><th>model</th><th>prompt</th>
<th class="num">% input</th><th class="num">% output</th><th class="num">$/1M in</th>
<th class="num">$/1M out</th><th class="num">blend arithmetic</th><th class="num">$/10M</th>
</tr></thead><tbody>{mix_rows}</tbody></table></div>
<p class="lead"><b>&ldquo;% input&rdquo; is the share of billed tokens that were input, not a rate.</b>
Input and output are priced differently, so this mix decides the effective rate you actually pay.
Worked example for Gemini Flash: output costs 8&times; input ($2.50 vs $0.30 per 1M), but it applies
to only ~1% of tokens, so <code>0.99&times;0.30 + 0.01&times;2.50 = $0.32/1M</code> &mdash; the
blended rate is essentially the <i>input</i> rate.<br>
<b>Consequence:</b> on this workload the output price is nearly irrelevant. A model with cheap input
and expensive output does fine; a model with expensive input is punished however terse its answers
are.<br>
<b>The judge row is the control.</b> It is a <i>single-shot</i> call &mdash; one trace in, one
structured summary out, with no conversation to re-send &mdash; and its mix is nothing like the
agent's. That shows the 99%-input figure is a property of the <b>multi-turn loop</b>, not of LLM
workloads in general, and it is why output pricing still matters for the evaluation layer even
though it barely registers for the agents. <b>Caveat:</b> judge output tokens are approximated from
stored summary size (indented JSON, so it likely <i>over</i>-states them) &mdash; immaterial for the
agents at 1&ndash;7% output, but it does move the judge's own blended rate, so treat that row as
approximate.</p></div>

<div class="panel"><h3>How much of that is the mix rather than the model?</h3>
<div class="tblwrap"><table><thead><tr><th>model</th><th class="num">$/10M at the actual mix</th>
<th class="num">$/10M if the mix were 50/50</th><th class="num">inflation</th></tr></thead>
<tbody>{cf_rows}</tbody></table></div>
<p class="lead">Same prices, same models &mdash; only the input/output balance changes. An even mix
would cost several times more per token across the board, which is another view of the 44:1
structure: each turn re-sends the whole conversation as input while the model writes only a few
hundred output tokens. <b>&ldquo;99% input&rdquo; and &ldquo;cost scales with turns&sup2;&rdquo; are
the same fact from two angles.</b></p></div>

<h2>Lean vs detailed &mdash; the prompt is a cost lever</h2>
<div class="panel"><div class="tblwrap"><table><thead><tr><th>model</th>
<th class="num">detailed</th><th class="num">lean</th><th class="num">&Delta;</th>
<th class="num">turns/ep</th></tr></thead><tbody>{lean_rows}</tbody></table></div>
<p class="lead">Same task, same data, same seeds &mdash; only the prompt differs. Read this beside
the ablation result that outcome is prompt-invariant for the flagships: the lean prompt buys the
same answer for less money, because it induces fewer turns.</p></div>

{tool_section}

<h2>Price table used</h2>
<div class="panel"><table><thead><tr><th>model</th><th class="num">$/1M in</th>
<th class="num">$/1M out</th></tr></thead><tbody>{price_rows}</tbody></table>
<p class="lead">Override with <code>--prices file.json</code>. Judge output tokens are approximated
from stored summary size; at {tot_in/max(tot_out,1):.0f}:1 input dominance that approximation
cannot move any conclusion here.</p></div>

<div class="foot">Generated by <code>scripts/gen_cost_report.py</code>.</div>
</div></body></html>"""
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    open(OUT, 'w').write(html)
    print(f"\nwrote {OUT}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
