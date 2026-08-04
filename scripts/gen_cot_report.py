#!/usr/bin/env python3
"""Detailed chain-of-thought report — the deep-dive behind the manuscript report's §2/§3.

The manuscript report compresses the CoT evidence to one rate per arm (data-derived %) plus an
agreement table. That is the right altitude for a paper but it hides everything needed to defend
the number: the full label distributions, how the ladder progresses arm by arm, which episodes the
three judge passes actually disagreed on, and the agent's own words. This report is that layer.

SECTIONS
  1 Reasoning strategy      what kind of process each model ran, by prompt
  2 Identity derivation     full 4-way distribution across G0->G1->G2->G3 (the ladder progression;
                            G0/G1 pre-reveal the codebook so "recalled" is EXPECTED there — the
                            contrast against G2 is the point)
  3 Rigor & codebook        validation_rigor, and annotate-vs-rebuild when the codebook lands
  4 Hypothesis pivots       how often the model changed its mind
  5 Per-episode detail      all three judge votes side by side, G2, with consensus
  6 Judge disagreements     the episodes with no majority — where the label is genuinely ambiguous
  7 Verbatim evidence       pre-reveal sample-count naming, quoted, via the TIGHTENED probe

All labels are the 3-pass CONSENSUS unless a section says otherwise; ties are shown as unresolved
rather than silently broken.

Usage: python scripts/gen_cot_report.py   ->  results/tcga/COT_REPORT.html
"""
import glob, html as H, json, os, re, sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import runs_config
from extract_cot import extract_episode, count_based_identity

_COL = {l: c for l, s, c, t in runs_config.MODELS}
RUNS = [(m, p, r, _COL[m]) for m, p, r in runs_config.triples()]
SUFFIXES = ['_cotsummary.json', '_cotsummary_j2.json', '_cotsummary_j3.json']
OUT = 'results/tcga/COT_REPORT.html'

ID_ORDER = ['data-derived', 'mixed', 'recalled-prior', 'not-established']
RIG_ORDER = ['high', 'medium', 'low']
CB_ORDER = ['annotated-existing', 'rebuilt-from-priors', 'overfit-to-revealed', 'not-applicable']
ID_COL = {'data-derived': '#3fb950', 'mixed': '#d29922',
          'recalled-prior': '#f85149', 'not-established': '#6b7683'}


def arm(l):
    a = l.split('_')[0]
    return 'g3' if a.startswith('g3') else a


def load(run, sfx):
    d = {}
    for p in glob.glob(f"{run}/*/*{sfx}"):
        l = os.path.basename(p).replace(sfx, '')
        if os.path.basename(os.path.dirname(p)) == l:
            d[l] = json.load(open(p))
    return d


def consensus(votes):
    c = Counter(votes).most_common()
    return None if len(c) > 1 and c[0][1] == c[1][1] else c[0][0]


# ---- gather: per run, per episode, the three votes + consensus ----------------------------
EP = {}
for model, prompt, run, col in RUNS:
    L = [load(run, s) for s in SUFFIXES]
    if not all(L):
        continue
    keys = sorted(set(L[0]) & set(L[1]) & set(L[2]))
    rows = []
    for k in keys:
        votes = {f: [d[k].get(f) for d in L]
                 for f in ('identity_derivation', 'validation_rigor', 'codebook_response')}
        rows.append({
            'label': k, 'arm': arm(k), 'cohort': L[0][k].get('cohort', '?'),
            'votes': votes,
            'cons': {f: consensus(v) for f, v in votes.items()},
            'strategy': L[0][k].get('reasoning_strategy', '?'),
            'pivots': L[0][k].get('num_pivots', 0),
            'verdict': L[0][k].get('overall_verdict', ''),
        })
    EP[(model, prompt)] = {'rows': rows, 'color': col, 'run': run}

SIZES = {}
for _, _, run, _ in RUNS:
    for p in glob.glob(f"{run}/g2_*/grouping.json"):
        c = os.path.basename(os.path.dirname(p)).split('_')[1].upper()
        try: SIZES[c] = len(json.load(open(p)))
        except Exception: pass


def bar(counts, order, colmap, n):
    """Stacked proportion bar."""
    if not n:
        return "<span class='mut'>—</span>"
    segs = ""
    for k in order:
        v = counts.get(k, 0)
        if not v:
            continue
        segs += (f"<div style='width:{v/n*100:.1f}%;background:{colmap.get(k,'#6b7683')}' "
                 f"title='{H.escape(k)}: {v}/{n}'></div>")
    return f"<div class='stack'>{segs}</div>"


# ---- §1 reasoning strategy ----------------------------------------------------------------
strat_rows = ""
for (m, pr), d in EP.items():
    c = Counter(r['strategy'] for r in d['rows'])
    top = "  ".join(f"<span class='chip'>{H.escape(str(t))} &times;{n}</span>"
                    for t, n in c.most_common(4))
    strat_rows += (f"<tr><td class='grp' style='color:{d['color']}'>{m}</td><td>{pr}</td>"
                   f"<td>{top}</td></tr>")

# ---- §2 identity derivation by arm --------------------------------------------------------
arm_rows = ""
for (m, pr), d in EP.items():
    cells = ""
    for a in ('g0', 'g1', 'g2', 'g3'):
        rs = [r for r in d['rows'] if r['arm'] == a]
        if not rs:
            cells += "<td class='mut'>—</td>"; continue
        c = Counter(r['cons']['identity_derivation'] for r in rs)
        unres = sum(1 for r in rs if r['cons']['identity_derivation'] is None)
        dd = c.get('data-derived', 0)
        cells += (f"<td>{bar(c, ID_ORDER, ID_COL, len(rs))}"
                  f"<span class='sub'>{dd}/{len(rs)} derived"
                  f"{f' &middot; {unres} unres' if unres else ''}</span></td>")
    arm_rows += (f"<tr><td class='grp' style='color:{d['color']}'>{m}</td><td>{pr}</td>{cells}</tr>")

# ---- §3 rigor + codebook ------------------------------------------------------------------
rig_rows = ""
RIG_COL = {'high': '#3fb950', 'medium': '#d29922', 'low': '#f85149'}
CB_COL = {'annotated-existing': '#3fb950', 'rebuilt-from-priors': '#f85149',
          'overfit-to-revealed': '#d29922', 'not-applicable': '#6b7683'}
for (m, pr), d in EP.items():
    hon = [r for r in d['rows'] if r['arm'] in ('g0', 'g1', 'g2')]
    cr = Counter(r['cons']['validation_rigor'] for r in hon)
    cc = Counter(r['cons']['codebook_response'] for r in hon)
    # A label held by only ONE of three passes can never reach majority, so consensus reports it
    # as zero and a genuinely rare behaviour disappears. Show any-vote counts alongside so the
    # rare-but-real cases (rebuild / overfit) stay visible.
    anyv = Counter()
    for r in hon:
        for x in set(r['votes']['codebook_response']):
            anyv[x] += 1
    rare = (f"<span class='sub'>consensus: annotated {cc.get('annotated-existing',0)} &middot; "
            f"rebuilt {cc.get('rebuilt-from-priors',0)} &middot; "
            f"overfit {cc.get('overfit-to-revealed',0)}<br>"
            f"any single vote: rebuilt {anyv.get('rebuilt-from-priors',0)} &middot; "
            f"overfit {anyv.get('overfit-to-revealed',0)}</span>")
    rig_rows += (f"<tr><td class='grp' style='color:{d['color']}'>{m}</td><td>{pr}</td>"
                 f"<td>{bar(cr, RIG_ORDER, RIG_COL, len(hon))}"
                 f"<span class='sub'>high {cr.get('high',0)}/{len(hon)}</span></td>"
                 f"<td>{bar(cc, CB_ORDER, CB_COL, len(hon))}{rare}</td></tr>")

# ---- §4 pivots ----------------------------------------------------------------------------
piv_rows = ""
for (m, pr), d in EP.items():
    v = [r['pivots'] or 0 for r in d['rows']]
    mean = sum(v) / len(v) if v else 0
    piv_rows += (f"<tr><td class='grp' style='color:{d['color']}'>{m}</td><td>{pr}</td>"
                 f"<td class='num'>{mean:.2f}</td><td class='num'>{min(v)}–{max(v)}</td>"
                 f"<td class='num'>{sum(1 for x in v if x == 0)}/{len(v)}</td></tr>")

# ---- §5 per-episode G2 detail -------------------------------------------------------------
SHORT = {'data-derived': 'D', 'mixed': 'M', 'recalled-prior': 'R', 'not-established': '-'}
ep_rows = ""
for (m, pr), d in EP.items():
    for r in sorted([x for x in d['rows'] if x['arm'] == 'g2'], key=lambda x: x['label']):
        v = r['votes']['identity_derivation']
        cons = r['cons']['identity_derivation']
        chips = " ".join(f"<span class='v' style='background:{ID_COL.get(x,'#6b7683')}33;"
                         f"color:{ID_COL.get(x,'#9aa7b4')}'>{SHORT.get(x,'?')}</span>" for x in v)
        cc = ID_COL.get(cons, '#9aa7b4') if cons else '#d29922'
        ep_rows += (f"<tr><td class='grp' style='color:{d['color']}'>{m}</td><td>{pr}</td>"
                    f"<td><code>{H.escape(r['label'])}</code></td><td>{chips}</td>"
                    f"<td style='color:{cc};font-weight:700'>{cons or 'no majority'}</td></tr>")

# ---- §6 disagreements ---------------------------------------------------------------------
dis_rows = ""
ndis = 0
for (m, pr), d in EP.items():
    for r in d['rows']:
        v = r['votes']['identity_derivation']
        if len(set(v)) == 1:
            continue
        ndis += 1
        if r['cons']['identity_derivation'] is not None and ndis > 0:
            pass
        if r['cons']['identity_derivation'] is None:      # only the genuinely unresolved
            dis_rows += (f"<tr><td class='grp' style='color:{d['color']}'>{m}</td><td>{pr}</td>"
                         f"<td><code>{H.escape(r['label'])}</code></td>"
                         f"<td>{' / '.join(H.escape(str(x)) for x in v)}</td>"
                         f"<td class='vd'>{H.escape((r['verdict'] or '')[:180])}</td></tr>")
ntot = sum(len(d['rows']) for d in EP.values())

# ---- §7 verbatim shape-leak evidence ------------------------------------------------------
quotes = ""
leak_tot = 0
for model, prompt, run, col in RUNS:
    for p in sorted(glob.glob(f"{run}/g2_*/g2_*.json")):
        if os.path.basename(p)[:-5] != os.path.basename(os.path.dirname(p)):
            continue
        try:
            rec = extract_episode(p)
            snip = count_based_identity(rec, SIZES)
        except Exception:
            continue
        if not snip:
            continue
        leak_tot += 1
        coh = (rec.get('cohort') or '?').upper()
        clean = H.escape(re.sub(r"\s+", " ", str(snip)).strip()[:300])
        quotes += (f"<div class='q'><div class='qh'><b style='color:{col}'>{model}</b> &middot; "
                   f"{prompt} &middot; {coh} (n={SIZES.get(coh,'?')}) &middot; "
                   f"<code>{H.escape(os.path.basename(p)[:-5])}</code> &middot; "
                   f"<span class='tag'>pre-reveal</span></div>"
                   f"<div class='qt'>&ldquo;{clean}&rdquo;</div></div>")

CSS = """
:root{--bg:#0d1117;--panel:#161b22;--line:#283041;--ink:#e6edf3;--mut:#9aa7b4;--acc:#58a6ff;--bad:#f85149;--warn:#d29922}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.6 -apple-system,Segoe UI,Roboto,Arial,sans-serif;padding:30px}
.wrap{max-width:1080px;margin:0 auto}h1{font-size:24px;margin:0 0 4px}
h2{font-size:18px;margin:32px 0 8px;border-left:3px solid var(--acc);padding-left:11px}
.meta{color:var(--mut);font-size:13px;margin-bottom:10px}.lead{color:var(--mut);font-size:12.5px;margin:8px 0 0}
.panel{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:15px 18px;margin:12px 0}
table{border-collapse:collapse;width:100%;font-size:13px}th,td{padding:7px 9px;border-bottom:1px solid var(--line);text-align:left;vertical-align:middle}
th{color:var(--mut);font-weight:600;font-size:11.5px}td.num,th.num{text-align:right;font-variant-numeric:tabular-nums}
.grp{font-weight:700}.mut{color:var(--mut)}.tblwrap{overflow-x:auto}
.stack{display:flex;height:15px;border-radius:4px;overflow:hidden;background:#0b1220;min-width:110px}
.sub{display:block;font-size:9.5px;color:var(--mut);margin-top:3px}
.chip{display:inline-block;background:#0b1220;border:1px solid var(--line);border-radius:5px;padding:1px 7px;font-size:11px;margin:1px 3px 1px 0}
.v{display:inline-block;width:19px;text-align:center;border-radius:4px;font-size:11px;font-weight:700;margin-right:2px}
.vd{color:var(--mut);font-size:11.5px}
.q{border-radius:8px;padding:10px 13px;margin:8px 0;border-left:3px solid var(--bad);background:#0b1220}
.qh{font-size:11.5px;color:var(--mut);margin-bottom:5px}.qt{font-size:13px;font-style:italic}
.tag{background:#3a1414;color:var(--bad);padding:1px 7px;border-radius:5px;font-size:10.5px;font-weight:700}
.legend{display:flex;gap:14px;flex-wrap:wrap;font-size:11.5px;color:var(--mut);margin:8px 0 2px}
.legend span{display:flex;align-items:center;gap:5px}.legend i{width:11px;height:11px;border-radius:2px;display:inline-block}
.warn{background:#2a2410;border:1px solid #5c4a12;border-radius:8px;padding:12px 16px;margin:12px 0;color:#e8d48a;font-size:12.5px}
code{background:#0b1220;padding:1px 5px;border-radius:4px;font-size:11.5px}
.foot{color:var(--mut);font-size:11.5px;margin-top:26px;border-top:1px solid var(--line);padding-top:12px}
"""
id_legend = "".join(f"<span><i style='background:{ID_COL[k]}'></i>{k}</span>" for k in ID_ORDER)

html = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Chain-of-thought — detailed report</title><style>{CSS}</style></head><body><div class="wrap">
<h1>Chain-of-thought &mdash; detailed report</h1>
<div class="meta">Deep-dive behind &sect;2/&sect;3 of the manuscript report &middot; {len(EP)} run arms
&times; 75 episodes &middot; labels are the <b>3-pass consensus</b> of a neutral DeepSeek-v4-pro judge;
ties are shown as <i>no majority</i> rather than silently broken</div>

<h2>1 &middot; Reasoning strategy</h2>
<div class="panel"><div class="tblwrap"><table><thead><tr><th>model</th><th>prompt</th>
<th>most common strategy tags (pass 1)</th></tr></thead><tbody>{strat_rows}</tbody></table></div>
<p class="lead">The judge's free-text characterisation of the process the agent ran. Descriptive
only &mdash; it is not scored and not part of any claim; it is here to show what the arms look like
qualitatively.</p></div>

<h2>2 &middot; Identity derivation across the ladder</h2>
<div class="panel"><div class="legend">{id_legend}</div>
<div class="tblwrap"><table><thead><tr><th>model</th><th>prompt</th>
<th>G0 <span class="sub">told the cohort</span></th><th>G1 <span class="sub">genes-only</span></th>
<th>G2 <span class="sub">blind</span></th><th>G3 <span class="sub">mislead</span></th>
</tr></thead><tbody>{arm_rows}</tbody></table></div>
<p class="lead"><b>Read across each row.</b> G0 and G1 pre-reveal the codebook, so
<i>recalled-prior</i> is the EXPECTED label there and carries no criticism &mdash; the informative
contrast is how much of the bar stays green once the cohort is blinded (G2) and once a false frame
is injected (G3). This is the arm-by-arm detail the manuscript report compresses to a single G2
rate.</p></div>

<h2>3 &middot; Validation rigor and codebook response</h2>
<div class="panel"><div class="tblwrap"><table><thead><tr><th>model</th><th>prompt</th>
<th>validation rigor <span class="sub">high / medium / low</span></th>
<th>codebook response <span class="sub">annotate / rebuild / overfit</span></th>
</tr></thead><tbody>{rig_rows}</tbody></table></div>
<p class="lead"><b>Codebook response is the behavioural tell.</b> When gene identities are revealed,
does the agent <i>annotate</i> the structure it already found, or <i>rebuild</i> its answer from
priors? Rebuilding is recall arriving late. Honest arms (G0/G1/G2) only.<br>
<b>Read the two lines together.</b> Across all 1350 judge votes the label is overwhelmingly
<i>annotated-existing</i> (1168), with <i>rebuilt-from-priors</i> (23) and
<i>overfit-to-revealed</i> (4) genuinely rare. Because a label held by only one of three passes can
never win a majority, <b>consensus reports those rare cases as zero</b> &mdash; the any-vote line
keeps them visible. Two consequences: this field is near-constant, so it cannot discriminate
between models, and its ~100% inter-pass agreement is largely a <b>ceiling effect</b> rather than
evidence that the judge is reliable in general.</p></div>

<h2>4 &middot; Hypothesis pivots</h2>
<div class="panel"><div class="tblwrap"><table><thead><tr><th>model</th><th>prompt</th>
<th class="num">mean pivots</th><th class="num">range</th><th class="num">never pivoted</th>
</tr></thead><tbody>{piv_rows}</tbody></table></div>
<p class="lead">How often the agent changed its working hypothesis mid-episode. A model that never
pivots is either right immediately or not testing itself &mdash; this does not distinguish those,
so treat it as descriptive.</p></div>

<h2>5 &middot; Per-episode detail (G2, blind)</h2>
<div class="panel"><div class="tblwrap"><table><thead><tr><th>model</th><th>prompt</th>
<th>episode</th><th>3 votes</th><th>consensus</th></tr></thead><tbody>{ep_rows}</tbody></table></div>
<p class="lead">Every G2 episode with all three judge passes shown side by side
(<b>D</b> data-derived, <b>M</b> mixed, <b>R</b> recalled-prior). Three identical chips mean the
judge was stable on that episode; mixed chips mean it was not. <b>Do not quote an individual row as
fact</b> &mdash; per-episode labels are the least reliable level of this data.</p></div>

<h2>6 &middot; Where the judges could not agree</h2>
<div class="panel"><div class="tblwrap"><table><thead><tr><th>model</th><th>prompt</th>
<th>episode</th><th>the three votes</th><th>pass-1 verdict</th></tr></thead>
<tbody>{dis_rows or "<tr><td colspan=5 class='mut'>no unresolved episodes</td></tr>"}</tbody></table></div>
<p class="lead">Episodes where all three passes disagreed, so no majority exists
({ndis} of {ntot} episodes had any disagreement at all). These are not judge failures &mdash; they
are the genuinely ambiguous cases, where the trace supports more than one reading. They are the
honest place to look when deciding how much weight the label can carry.</p></div>

<h2>7 &middot; Verbatim evidence &mdash; recognising the benchmark by its shape</h2>
<div class="panel">{quotes or "<p class='lead'>No pre-reveal sample-count naming detected.</p>"}
<p class="lead"><b>{leak_tot} episodes</b> where the model named this cohort's cancer <i>and</i> the
cohort's exact sample size appeared within ~120 characters, before the codebook revealed any gene.
This is the most literal form of recall: recognising the <i>dataset</i> by its dimensions rather
than deriving the biology. Uses the <b>tightened</b> probe, hand-validated against a manual read
&mdash; the earlier loose probe over-counted by matching analogy lists and incidental numbers.</p></div>

<div class="warn"><b>Scope.</b> This is the agent's <i>stated</i> reasoning &mdash; WHY headers,
inter-call text and <code>record_observation</code> hypotheses. Provider adapters strip raw
thinking tokens, so no true hidden chain-of-thought exists for any model here. Judge replicates are
three passes of the SAME model, so they bound stochasticity, not cross-family bias.</div>

<div class="foot">Generated by <code>scripts/gen_cot_report.py</code>. Summary layer:
<code>scripts/gen_manuscript_report.py</code> &rarr; <code>results/MANUSCRIPT_REPORT.html</code>.</div>
</div></body></html>"""

os.makedirs(os.path.dirname(OUT), exist_ok=True)
open(OUT, 'w').write(html)
print(f"wrote {OUT}  ({len(html)} bytes)")
print(f"  run arms={len(EP)}  episodes={ntot}  with-disagreement={ndis}  shape-leak quotes={leak_tot}")
