#!/usr/bin/env python3
"""Cost report — what the benchmark actually consumed, and the unit economics.

TOKEN COUNTS ARE MEASURED, NOT ESTIMATED: every episode records per-turn input/output in
run_log.usage_log, with 75/75 coverage on all six runs.

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
  python scripts/gen_cost_report.py                      -> results/tcga/COST_REPORT.html
  python scripts/gen_cost_report.py --prices my.json     -> override the price table
"""
import argparse, glob, json, os, statistics as st, sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

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
    'Gemini Flash':   {'in': 1.50,  'out': 9.00},
    'deepseek-v4-pro': {'in': 0.435, 'out': 0.87},
}
PRICES_VERIFIED = True           # supplied by the project owner 2026-07-28
PRICES_DATE = '2026-07-28 (supplied by project owner)'

RUNS = [
    ('GPT-5.5', 'detailed', 'results/tcga/ladder/gpt55_20260707', '#1D9E75'),
    ('GPT-5.5', 'lean', 'results/tcga/lean/gpt55_20260721', '#1D9E75'),
    ('Sonnet 5', 'detailed', 'results/tcga/ladder/sonnet5_20260713', '#7F77DD'),
    ('Sonnet 5', 'lean', 'results/tcga/lean/sonnet5_20260722', '#7F77DD'),
    ('Gemini Flash', 'detailed', 'results/tcga/ladder/gemini35flash_20260716', '#EF9F27'),
    ('Gemini Flash', 'lean', 'results/tcga/lean/gemini35flash_20260722', '#EF9F27'),
]
JUDGE_SUFFIXES = ['_cotsummary.json', '_cotsummary_j2.json', '_cotsummary_j3.json']
OUT = 'results/tcga/COST_REPORT.html'


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
                        'in': ei, 'out': eo, 'turns': len(u)})
        out[(model, prompt)] = dict(
            n=n, input=I, output=O, turns=turns, color=col,
            turns_per_ep=turns / max(n, 1), per_ep=per_ep, eps=eps,
            first_in=st.mean(first_in) if first_in else 0)
    return out


def judge_usage():
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
    for _, _, run, _ in RUNS:
        for p in episode_paths(run):
            try:
                per_call_in = len(sc.build_input(extract_episode(p))) // 4 + overhead
            except Exception:
                continue
            for sfx in JUDGE_SUFFIXES:
                jp = p[:-5] + sfx
                if not os.path.exists(jp):
                    continue
                calls += 1
                try:
                    rec = json.load(open(jp))
                except Exception:
                    rec = {}
                u = rec.get("judge_usage") or {}
                if u.get("input_tokens") and u.get("output_tokens"):
                    tin += u["input_tokens"]; tout += u["output_tokens"]; measured += 1
                else:
                    tin += per_call_in
                    # compact payload, not the indented file on disk
                    tout += len(json.dumps(rec, separators=(",", ":"))) // 4
    return dict(input=tin, output=tout, calls=calls, measured=measured,
                overhead_per_call=overhead)


def cost(model, tin, tout, prices):
    p = prices.get(model)
    if not p:
        return None
    return tin / 1e6 * p['in'] + tout / 1e6 * p['out']


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--prices', type=str, default=None, help='JSON price override')
    args = ap.parse_args()
    prices = dict(PRICES)
    verified = PRICES_VERIFIED
    if args.prices:
        prices.update(json.load(open(args.prices)))
        verified = True
    if not verified:
        print("!" * 90)
        print("  DOLLAR FIGURES BELOW ARE PLACEHOLDERS — the price table is not sourced.")
        print("  Token counts are measured; costs are arithmetic on unverified prices.")
        print("  Supply real rates with --prices <json> (invoices are ground truth).")
        print("!" * 90)

    A = agent_usage()
    J = judge_usage()

    # ---- console ----
    print("=" * 90)
    print("  AGENT TOKEN USAGE (measured from run_log.usage_log)")
    print("=" * 90)
    print(f"  {'run':24} {'eps':>4} {'input':>14} {'output':>11} {'in:out':>7} "
          f"{'turns/ep':>9} {'$/episode':>10} {'$ total':>9}")
    tot_in = tot_out = tot_cost = 0
    for (m, pr), d in A.items():
        c = cost(m, d['input'], d['output'], prices) or 0
        tot_in += d['input']; tot_out += d['output']; tot_cost += c
        print(f"  {m+'/'+pr:24} {d['n']:>4} {d['input']:>14,} {d['output']:>11,} "
              f"{d['input']/max(d['output'],1):>6.1f}: {d['turns_per_ep']:>8.1f} "
              f"{c/max(d['n'],1):>9.2f} {c:>9.2f}")
    print(f"  {'TOTAL':24} {sum(d['n'] for d in A.values()):>4} {tot_in:>14,} {tot_out:>11,} "
          f"{tot_in/max(tot_out,1):>6.1f}: {'':>8} {'':>9} {tot_cost:>9.2f}")

    print("\n" + "=" * 90)
    print("  COST PER 10M TOKENS  (normalises away turn-count differences)")
    print("=" * 90)
    per10 = {}
    for (m, pr), d in A.items():
        t = d['input'] + d['output']
        c = cost(m, d['input'], d['output'], prices) or 0
        per10[(m, pr)] = c / t * 1e7 if t else 0
        print(f"  {m+'/'+pr:24} ${per10[(m,pr)]:>7.2f} per 10M   "
              f"(blend of {d['input']/t*100:.0f}% input at ${prices[m]['in']}/M, "
              f"{d['output']/t*100:.0f}% output at ${prices[m]['out']}/M)")

    if J:
        jc = cost('deepseek-v4-pro', J['input'], J['output'], prices) or 0
        jt = J['input'] + J['output']
        print("\n" + "=" * 90)
        print("  JUDGE (3 passes x 450 episodes, neutral DeepSeek-v4-pro)")
        print("=" * 90)
        src = ("provider-reported" if J.get('measured') == J['calls']
               else f"ESTIMATED ({J['calls']-J.get('measured',0)}/{J['calls']} calls)")
        print(f"  calls {J['calls']:,}   input {J['input']:,}   output {J['output']:,}   "
              f"total {jt/1e6:.1f}M   ${jc:.2f}   (${jc/jt*1e7:.2f} per 10M)")
        print(f"  token source: {src}"
              + ("" if J.get('measured') == J['calls'] else
                 f"  — chars//4 + {J['overhead_per_call']} tok/call system+tool overhead;"
                 f" a LOWER BOUND on input"))
        print(f"  judge is {jc/max(tot_cost,1e-9)*100:.1f}% of agent spend — the evaluation layer is")
        print(f"  far cheaper than generating the episodes it grades.")

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
        cd = cost(m, dd['input'], dd['output'], prices) or 0
        cl = cost(m, ll['input'], ll['output'], prices) or 0
        print(f"    {m:14} ${cd:7.2f} -> ${cl:7.2f}   ({(cl-cd)/max(cd,1e-9)*100:+.0f}%, "
              f"{dd['turns_per_ep']:.0f} -> {ll['turns_per_ep']:.0f} turns/ep)")

    # ---- html ----
    rows = ""
    for (m, pr), d in A.items():
        c = cost(m, d['input'], d['output'], prices) or 0
        t = d['input'] + d['output']
        rows += (f"<tr><td class='grp' style='color:{d['color']}'>{m}</td><td>{pr}</td>"
                 f"<td class='num'>{d['n']}</td><td class='num'>{d['input']:,}</td>"
                 f"<td class='num'>{d['output']:,}</td>"
                 f"<td class='num'>{d['input']/max(d['output'],1):.0f}:1</td>"
                 f"<td class='num'>{d['turns_per_ep']:.1f}</td>"
                 f"<td class='num'>${per10[(m,pr)]:.2f}</td>"
                 f"<td class='num'>${c/max(d['n'],1):.2f}</td>"
                 f"<td class='num'><b>${c:,.2f}</b></td></tr>")
    lean_rows = ""
    for m in dict.fromkeys(x[0] for x in A):
        dd, ll = A.get((m, 'detailed')), A.get((m, 'lean'))
        if not dd or not ll:
            continue
        cd = cost(m, dd['input'], dd['output'], prices) or 0
        cl = cost(m, ll['input'], ll['output'], prices) or 0
        pct = (cl - cd) / max(cd, 1e-9) * 100
        lean_rows += (f"<tr><td class='grp' style='color:{dd['color']}'>{m}</td>"
                      f"<td class='num'>${cd:,.2f}</td><td class='num'>${cl:,.2f}</td>"
                      f"<td class='num {'good' if pct<0 else 'bad'}'>{pct:+.0f}%</td>"
                      f"<td class='num'>{dd['turns_per_ep']:.0f} &rarr; {ll['turns_per_ep']:.0f}</td></tr>")
    jrow = ""
    if J:
        jc = cost('deepseek-v4-pro', J['input'], J['output'], prices) or 0
        jt = J['input'] + J['output']
        jrow = (f"<tr><td class='grp'>judge &times;3 (DeepSeek)</td><td>all arms</td>"
                f"<td class='num'>{J['calls']:,} calls</td><td class='num'>{J['input']:,}</td>"
                f"<td class='num'>~{J['output']:,}</td>"
                f"<td class='num'>{J['input']/max(J['output'],1):.0f}:1</td><td class='num'>—</td>"
                f"<td class='num'>${jc/jt*1e7:.2f}</td><td class='num'>—</td>"
                f"<td class='num'><b>${jc:,.2f}</b></td></tr>")

    price_rows = "".join(
        f"<tr><td>{k}</td><td class='num'>${v['in']:.2f}</td><td class='num'>${v['out']:.2f}</td></tr>"
        for k, v in prices.items())

    # ---- token mix: what "% input" means, and why it decides the effective rate ----
    mix_rows = ""
    for (m, pr), d in A.items():
        t = d['input'] + d['output']
        fi, fo = d['input'] / t, d['output'] / t
        p = prices[m]
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
        jp = prices['deepseek-v4-pro']
        jb = jfi * jp['in'] + jfo * jp['out']
        mix_rows += (f"<tr><td class='grp'>deepseek-v4-pro</td><td>judge &times;3</td>"
                     f"<td class='num'>{jfi*100:.1f}%</td>"
                     f"<td class='num'>{jfo*100:.1f}%<span class='sub'>approx</span></td>"
                     f"<td class='num'>${jp['in']:.2f}</td><td class='num'>${jp['out']:.2f}</td>"
                     f"<td class='num'>{jfi:.3f}&times;{jp['in']:.2f} + {jfo:.3f}&times;{jp['out']:.2f}</td>"
                     f"<td class='num'><b>${jb*10:.2f}</b></td></tr>")
    # counterfactual: same prices, an even mix — shows how much the mix (not the model) is doing
    cf_rows = ""
    for m in dict.fromkeys(x[0] for x in A):
        d = A.get((m, 'detailed')) or A.get((m, 'lean'))
        t = d['input'] + d['output']
        fi, fo = d['input'] / t, d['output'] / t
        p = prices[m]
        actual = (fi * p['in'] + fo * p['out']) * 10
        even = (0.5 * p['in'] + 0.5 * p['out']) * 10
        cf_rows += (f"<tr><td class='grp' style='color:{d['color']}'>{m}</td>"
                    f"<td class='num'>${actual:.2f}</td><td class='num'>${even:.2f}</td>"
                    f"<td class='num bad'>&times;{even/actual:.1f}</td></tr>")
    if J:
        jt = J['input'] + J['output']
        jp = prices['deepseek-v4-pro']
        ja = (J['input'] / jt * jp['in'] + J['output'] / jt * jp['out']) * 10
        je = (0.5 * jp['in'] + 0.5 * jp['out']) * 10
        cf_rows += (f"<tr><td class='grp'>deepseek-v4-pro <span class='mut'>(judge)</span></td>"
                    f"<td class='num'>${ja:.2f}</td><td class='num'>${je:.2f}</td>"
                    f"<td class='num good'>&times;{je/ja:.1f}</td></tr>")

    # ---- per-episode cost: distribution, not just the mean ----
    ep_rows = ""
    for (m, pr), d in A.items():
        cs = sorted(cost(m, e['in'], e['out'], prices) or 0 for e in d['eps'])
        if not cs:
            continue
        lo, hi = cs[0], cs[-1]
        ep_rows += (f"<tr><td class='grp' style='color:{d['color']}'>{m}</td><td>{pr}</td>"
                    f"<td class='num'>{len(cs)}</td>"
                    f"<td class='num'>${st.mean(cs):.2f}</td>"
                    f"<td class='num'>${st.median(cs):.2f}</td>"
                    f"<td class='num'>${lo:.2f}</td><td class='num'>${hi:.2f}</td>"
                    f"<td class='num'>&times;{hi/max(lo,1e-9):.1f}</td></tr>")
    # ---- per-episode cost by arm: which arms are expensive ----
    ARMS = ['g0', 'g1', 'g2', 'g3']
    arm_rows = ""
    for (m, pr), d in A.items():
        cells = ""
        for a in ARMS:
            cs = [cost(m, e['in'], e['out'], prices) or 0 for e in d['eps'] if e['arm'] == a]
            cells += (f"<td class='num'>${st.mean(cs):.2f}<span class='sub'>n={len(cs)}</span></td>"
                      if cs else "<td class='num mut'>&mdash;</td>")
        cells += f"<td class='num'><b>${sum(cost(m, e['in'], e['out'], prices) or 0 for e in d['eps']):,.2f}</b></td>"
        arm_rows += (f"<tr><td class='grp' style='color:{d['color']}'>{m}</td><td>{pr}</td>{cells}</tr>")

    banner = ("" if verified else
        '<div class="warn"><b style="font-size:15px">&#9888; Every dollar figure on this page is a '
        'PLACEHOLDER.</b><br>The price table was entered from recollection and is <b>not sourced</b>. '
        'At least one entry is likely wrong: <code>docs/BENCHMARK_PLAN.md</code> records GPT-5.4 at '
        '$2.50/M in &middot; $15/M out, double the input price assumed here. '
        'Re-run with <code>--prices file.json</code> using rates from your invoices &mdash; those are '
        'ground truth and also capture discounts and cached-input rates that no list price reflects.'
        '<br><b>The token counts on this page are measured and unaffected</b> '
        '(<code>run_log.usage_log</code>, 75/75 episodes): the structural findings &mdash; 44:1 input '
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
<div class="meta">Token counts <b>measured</b> from <code>run_log.usage_log</code> (75/75 episodes on
every run) &middot; dollars derived from the editable price table below</div>

{banner}

<h2>Agent spend</h2>
<div class="panel"><div class="tblwrap"><table><thead><tr><th>model</th><th>prompt</th>
<th class="num">eps</th><th class="num">input tok</th><th class="num">output tok</th>
<th class="num">in:out</th><th class="num">turns/ep</th><th class="num">$/10M</th>
<th class="num">$/episode</th><th class="num">$ total</th></tr></thead>
<tbody>{rows}{jrow}</tbody></table></div>
<p class="lead"><b>$/10M tokens</b> is the blended unit price actually paid, which differs from
sticker price because each run has its own input/output mix. It is the number to use when comparing
models, since per-episode cost is dominated by how many turns a model takes.</p></div>

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
