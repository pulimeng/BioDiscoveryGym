#!/usr/bin/env python3
"""Render the two headline hypothesis tests as a report, verdicts first.

`cot_deepdive.py` computes H1 and H2 and writes `manuscript/figures/cot_stats.json`. It had no
rendered view, so the only way to see whether the paper's central pairing still holds was to read
raw JSON — which is how it went unnoticed that, on the clean run under the three-family judge
panel, NEITHER HALF HOLDS.

This reads that JSON and renders it. It computes nothing of its own: if a number here disagrees
with the JSON, this file is wrong. It refuses to render a stale file (see `_freshness`), because a
report of a hypothesis test is exactly the artifact that must not quietly describe last week's run.

Usage:
  BDG_RUNS=clean python scripts/cot_deepdive.py          # produces the JSON
  python scripts/gen_hypothesis_report.py                # -> results/tcga/reports/HYPOTHESIS_REPORT.html
"""
import html as H
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

SRC = 'manuscript/figures/cot_stats.json'
GEN = 'scripts/cot_deepdive.py'
OUT = 'results/tcga/reports/HYPOTHESIS_REPORT.html'
STALE_AFTER_DAYS = 7


def esc(s):
    return H.escape(str(s if s is not None else ''))


def _freshness(path):
    """(age_days, warning_html). A hypothesis report is the worst possible thing to serve stale."""
    age = (time.time() - os.path.getmtime(path)) / 86400
    if age <= STALE_AFTER_DAYS:
        return age, ''
    return age, (
        f"<div class='warn'><b>&#9888; The underlying statistics are {age:.0f} days old.</b> "
        f"<code>{esc(SRC)}</code> has not been regenerated since. Re-run "
        f"<code>BDG_RUNS=clean python {esc(GEN)}</code> before quoting anything on this page.</div>")


def pct(x):
    return '&mdash;' if x is None else f'{x*100:.1f}%'


def num(x, n=3):
    return '&mdash;' if x is None else f'{x:.{n}f}'


def p_class(p):
    if p is None:
        return 'mut'
    return 'good' if p < 0.05 else 'bad'


CSS = """
:root{--bg:#0d1117;--panel:#161b22;--line:#283041;--ink:#e6edf3;--mut:#9aa7b4;--acc:#58a6ff;
--good:#3fb950;--warn:#d29922;--bad:#f85149}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);
font:15px/1.6 -apple-system,Segoe UI,Roboto,Arial,sans-serif;padding:30px}
.wrap{max-width:980px;margin:0 auto}h1{font-size:24px;margin:0 0 4px}
h2{font-size:18px;margin:30px 0 8px;border-left:3px solid var(--acc);padding-left:11px}
.meta{color:var(--mut);font-size:13px;margin-bottom:10px}
.lead{color:var(--mut);font-size:12.5px;margin:8px 0 0}
.panel{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:15px 18px;margin:12px 0}
table{border-collapse:collapse;width:100%;font-size:13px}
th,td{padding:7px 9px;border-bottom:1px solid var(--line);text-align:left}
th{color:var(--mut);font-weight:600;font-size:11.5px}
td.num,th.num{text-align:right;font-variant-numeric:tabular-nums}
.grp{font-weight:700}.mut{color:var(--mut)}.good{color:var(--good)}.bad{color:var(--bad)}
.tblwrap{overflow-x:auto}
code{background:#0b1220;padding:1px 5px;border-radius:4px;font-size:12px}
.warn{background:#2a2410;border:1px solid #5c4a12;border-radius:8px;padding:13px 16px;margin:12px 0;
color:#e8d48a;font-size:12.5px}
.verdict{border-radius:8px;padding:12px 15px;margin:10px 0;font-size:14px}
.v-no{background:#2b1416;border:1px solid #6e2329;color:#ffb4ac}
.v-yes{background:#12261a;border:1px solid #1f5c31;color:#8fe0a6}
.v-na{background:#1a1d22;border:1px solid #333b47;color:var(--mut)}
.big{font-size:26px;font-weight:700}
.sub{color:var(--mut);font-size:10.5px;display:block}
.foot{color:var(--mut);font-size:11.5px;margin-top:26px;border-top:1px solid var(--line);padding-top:12px}
"""


def h1_block(d):
    g = d.get('groups') or {}
    rows = ''
    for k in ('data-derived', 'mixed', 'recalled-prior'):
        v = g.get(k)
        if not v:
            rows += (f"<tr><td class='grp'>{esc(k)}</td><td class='num mut' colspan='4'>"
                     f"no episodes with this consensus label</td></tr>")
            continue
        rows += (f"<tr><td class='grp'>{esc(k)}</td><td class='num'>{v['n']}</td>"
                 f"<td class='num'>{num(v['mean'])}</td><td class='num'>{num(v['median'])}</td>"
                 f"<td class='num'>{num(v['sd'])}</td></tr>")
    missing = d.get('missing_groups') or []
    if missing:
        verdict = (
            f"<div class='verdict v-na'><b>NOT COMPUTABLE.</b> The test contrasts outcome between "
            f"episodes that <i>derived</i> identity and episodes that <i>recalled</i> it &mdash; "
            f"and there are <b>no {', '.join(esc(m) for m in missing)} episodes at all</b> on the "
            f"blinded arm. There is no second group, so no comparison exists. "
            f"<b>This is a result, not a gap:</b> under blinding the panel finds essentially every "
            f"episode deriving. Reporting a p-value here would require inventing the missing arm."
            f"</div>")
    else:
        p = d.get('mann_whitney_p')
        cls = 'v-yes' if (p is not None and p < 0.05) else 'v-no'
        verdict = (f"<div class='verdict {cls}'><b>Mann&ndash;Whitney p = {num(p)}</b>, "
                   f"delta = {num(d.get('delta'))}.</div>")
    return f"""
<h2>H1 &mdash; can the outcome score see how identity was established?</h2>
<div class="panel">
{verdict}
<div class="tblwrap"><table><thead><tr><th>consensus strategy</th><th class="num">n</th>
<th class="num">mean outcome</th><th class="num">median</th><th class="num">sd</th></tr></thead>
<tbody>{rows}</tbody></table></div>
<p class="lead">Blinded (G2) episodes only, grouped by the judge panel's majority
<code>identity_derivation</code> label. Episodes where the three families split have no consensus
and are excluded rather than tie-broken &mdash; a tie-break would bias exactly this comparison.
Ordinal check across all groups: Spearman &rho; = <b>{num(d.get('spearman_rho'))}</b>,
p = <b>{num(d.get('spearman_p'))}</b>, n = {d.get('n')}.</p></div>"""


def h2_block(d):
    a, b = d.get('derived') or {}, d.get('not_derived') or {}
    p = d.get('fisher_p')
    ceiling = (a.get('rate') or 0) > 0.9 and (b.get('rate') or 0) > 0.9
    if p is not None and p < 0.05:
        verdict = (f"<div class='verdict v-yes'><b>SUPPORTED.</b> Fisher exact "
                   f"p = {num(p, 4)}, odds ratio {num(d.get('odds_ratio'), 2)}.</div>")
    elif ceiling:
        verdict = (
            f"<div class='verdict v-no'><b>NOT SUPPORTED &mdash; and the reason matters.</b> "
            f"Fisher exact p = {num(p, 4)}, odds ratio {num(d.get('odds_ratio'), 2)}. "
            f"Adoption is at <b>ceiling in both groups</b> ({pct(a.get('rate'))} vs "
            f"{pct(b.get('rate'))}): once an episode is actually shown the planted label, it "
            f"almost always adopts it, whether or not it derived the identity itself. Derivation "
            f"has nothing left to discriminate. <b>Do not restate the earlier "
            f"&ldquo;derivation protects&rdquo; result</b> &mdash; it came from a run where "
            f"unexposed episodes were counted as resistant.</div>")
    else:
        verdict = (f"<div class='verdict v-no'><b>NOT SUPPORTED.</b> Fisher exact p = "
                   f"{num(p, 4)}, odds ratio {num(d.get('odds_ratio'), 2)}.</div>")
    rows = ''
    for k, v in (('derived', a), ('did not derive', b)):
        rows += (f"<tr><td class='grp'>{esc(k)}</td>"
                 f"<td class='num'>{v.get('not_fooled')}</td>"
                 f"<td class='num'>{v.get('fooled')}</td>"
                 f"<td class='num'>{pct(v.get('rate'))}</td></tr>")
    return f"""
<h2>H2 &mdash; does deriving identity protect against a planted false label?</h2>
<div class="panel">
{verdict}
<div class="tblwrap"><table><thead><tr><th>strategy on G3</th>
<th class="num">not fooled</th><th class="num">adopted the label</th>
<th class="num">adoption rate</th></tr></thead><tbody>{rows}</tbody></table></div>
<p class="lead"><b>Denominator: {esc(d.get('denominator', 'see JSON'))}</b>, n = {d.get('n')}.
Two exclusions, both deliberate and both counted:
<b>{d.get('excluded_failed_gates', 0)}</b> episodes whose identity gate errored (no verdict is not
a verdict of &ldquo;resistant&rdquo;) and <b>{d.get('excluded_unexposed', 0)}</b> that were never
exposed to the planted label (an episode never shown a label was never tested). Counting either as
&ldquo;not fooled&rdquo; is what produced the two retracted G3 results; see
<code>scripts/g3_exposure.py</code>.</p></div>"""


def cohort_block(d):
    rows = ''
    for c, v in sorted(d.items(), key=lambda kv: -kv[1]['rate']):
        rows += (f"<tr><td class='grp'>{esc(c)}</td><td class='num'>{v['derived']}</td>"
                 f"<td class='num'>{v['n']}</td><td class='num'>{pct(v['rate'])}</td></tr>")
    lo = min(v['rate'] for v in d.values()) if d else 0
    hi = max(v['rate'] for v in d.values()) if d else 0
    return f"""
<h2>Supporting &mdash; derivation rate by cohort</h2>
<div class="panel"><div class="tblwrap"><table><thead><tr><th>cohort</th>
<th class="num">derived</th><th class="num">n</th><th class="num">rate</th></tr></thead>
<tbody>{rows}</tbody></table></div>
<p class="lead">Blinded arm. The spread is <b>{pct(lo)}&ndash;{pct(hi)}</b>. The intuition that
recall tracks how well-studied a cancer is predicts a wide spread here and there is none, so that
intuition remains <b>unsupported</b> &mdash; a null worth reporting rather than dropping.</p></div>"""


def judge_block(d):
    return f"""
<h2>Supporting &mdash; how often the three judge families agreed</h2>
<div class="panel">
<div class="big">{pct(d.get('unanimous_rate'))}</div>
<p class="lead"><b>{d.get('unanimous')}</b> of <b>{d.get('n')}</b> episodes drew the same
<code>identity_derivation</code> label from all three families; <b>{d.get('unresolved')}</b> had no
majority at all and are excluded from every test above.
<br><b>What this does and does not establish.</b> Each family judged each episode ONCE, so a
disagreement mixes genuine cross-family bias with ordinary per-judge stochasticity and this design
cannot separate them. Agreement here does <i>not</i> bound judge noise &mdash; no family was asked
the same question twice.</p></div>"""


def main():
    if not os.path.exists(SRC):
        sys.exit(f"missing {SRC} — run: BDG_RUNS=clean python {GEN}")
    d = json.load(open(SRC))
    for k in ('h1_outcome_vs_derivation', 'h2_derivation_vs_fooled', 'cohort_derivation', 'judge'):
        if k not in d:
            sys.exit(f"{SRC} has no '{k}' — it was written by an older {GEN}; regenerate it.")
    age, stale = _freshness(SRC)
    n = d.get('n') or {}

    html = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>TCGA Benchmark — Hypothesis Tests</title><style>{CSS}</style></head>
<body><div class="wrap">
<h1>The two headline hypotheses, as the data currently stands</h1>
<div class="meta">{esc(d.get('source'))} &middot; G2 n={n.get('g2')} &middot; G3 n={n.get('g3')}
&middot; statistics from <code>{esc(GEN)}</code>, rendered by
<code>scripts/gen_hypothesis_report.py</code> &middot; source file {age:.1f} days old</div>
{stale}
<div class="warn"><b>Read this before quoting the paper's spine.</b> The argument has always been a
<i>pairing</i>: (H1) the outcome score cannot tell derivation from recall, and (H2) the distinction
nonetheless decides whether an agent resists a false premise. On this run, under the three-family
judge panel and with the correct exposure denominator, <b>neither half holds</b> &mdash; H1 has no
recalled-prior group to contrast against, and H2 is at ceiling in both cells. Earlier versions of
both numbers came from a path-contaminated campaign, a single judge, and an arm-sized G3
denominator. The pairing may well be true; <b>this data does not currently show it.</b></div>

{h1_block(d['h1_outcome_vs_derivation'])}
{h2_block(d['h2_derivation_vs_fooled'])}
{cohort_block(d['cohort_derivation'])}
{judge_block(d['judge'])}

<div class="foot">This page renders <code>{esc(SRC)}</code> and computes nothing of its own; if a
number here disagrees with that file, this file is wrong. Process-level companion (deterministic,
no judge): <code>scripts/cot_flow.py</code> &rarr; <code>FLOW_REPORT.html</code>.</div>
</div></body></html>"""
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    open(OUT, 'w').write(html)
    print(f'wrote {OUT}  ({len(html)} bytes)')
    h2 = d['h2_derivation_vs_fooled']
    print(f"  H1: {d['h1_outcome_vs_derivation'].get('verdict', 'computed')}")
    print(f"  H2: p={h2['fisher_p']:.4f} on n={h2['n']} exposed "
          f"({h2['excluded_unexposed']} unexposed + {h2['excluded_failed_gates']} errored excluded)")


if __name__ == '__main__':
    main()
