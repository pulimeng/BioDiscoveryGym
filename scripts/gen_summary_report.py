#!/usr/bin/env python3
"""A narrative summary of how the agents actually worked — qualitative, quote-led.

This study is descriptive. The question is what these agents DO when handed a cancer-genomics
cohort, and the honest answer is a characterisation with examples, not a p-value. This report is
that: how each model works, what a typical episode looks like end to end, what changes as
information is withheld, and what the judges keep saying about the same behaviours.

Counts appear where a count is the clearest way to say "usually" or "rarely". They are descriptive
— shares of episodes, not tests, and no significance is claimed anywhere on the page.

Sources, both already on disk:
  manuscript/figures/cot_flow.json          deterministic process record (scripts/cot_flow.py)
  <ep>/scoring/<judge>/cotsummary.json      the judges' prose: key moves, strengths, weaknesses

Usage:
  BDG_RUNS=clean python scripts/cot_flow.py         # produces the process JSON
  BDG_RUNS=clean python scripts/gen_summary_report.py
      -> results/tcga/reports/SUMMARY.html
"""
import glob
import html as H
import json
import os
import re
import statistics as st
import sys
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import judges_config as J
import panel_data
import runs_config

FLOW = 'manuscript/figures/cot_flow.json'
OUT = 'results/tcga/reports/SUMMARY.html'

ARM_STORY = {
    'g0': ('G0 &mdash; told the cohort', 'the agent is handed the cancer type outright'),
    'g1': ('G1 &mdash; real gene names', 'identity is recoverable from the genes, but not given'),
    'g2': ('G2 &mdash; blinded', 'genes are anonymised; identity must be inferred from data'),
    'g3': ('G3 &mdash; a false label is planted', 'the harness asserts the wrong cohort mid-run'),
}


def esc(s):
    return H.escape(str(s if s is not None else ''))


def load_summaries():
    """[(label, model, prompt, arm, judge, record)] over every cotsummary on the panel."""
    out = []
    for model, prompt, run in runs_config.triples():
        for tag in J.tags():
            for p in glob.glob(panel_data.artifact_glob(run, 'cot', tag)):
                try:
                    d = json.load(open(p))
                except Exception:
                    continue
                lab = panel_data.label_of(p)
                a = lab.split('_')[0]
                out.append((lab, model, prompt, 'g3' if a.startswith('g3') else a, tag, d))
    return out


def flat(x):
    """The judges sometimes nest a list inside a list field; walk it rather than crash."""
    if isinstance(x, str):
        yield x
    elif isinstance(x, list):
        for y in x:
            yield from flat(y)


# Themes are counted by matching a short phrase list built by reading the most frequent
# weakness/strength phrasings, not invented: "exploration of" (96), "external validation" (35),
# "statistically significant" (23), "explore alternative" (21) were the top hits across 1,710
# judge records. Each theme below is a family of those phrasings.
THEMES = [
    ('narrow exploration',   r'explor\w+ (?:of|alternative)|did not explore|limited explor|'
                             r'alternative (?:clustering|algorithm|k |solutions)'),
    ('no external validation', r'external validation|independent (?:cohort|validation)|'
                               r'held[- ]out|replicat\w+ (?:cohort|dataset)'),
    ('weak statistics',      r'statistical(?:ly)? (?:significan|power)|borderline|underpowered|'
                             r'multiple[- ]test|not significant'),
    ('shallow cluster validation', r'silhouette|cluster (?:stability|validation)|'
                                   r'assess clustering|number of clusters|choice of k\b'),
    ('leaned on prior knowledge', r'prior knowledge|known markers|post[- ]hoc|canonical|'
                                  r'literature|textbook'),
    ('mechanism asserted, not shown', r'mechanis\w+ (?:not|was not|remains)|causal|speculativ|'
                                      r'unsupported (?:claim|mechanism)|hypothes\w+ without'),
]
THEME_RE = [(n, re.compile(p, re.I)) for n, p in THEMES]


def theme_counts(texts):
    c = Counter()
    for t in texts:
        for name, rx in THEME_RE:
            if rx.search(t):
                c[name] += 1
    return c


def pick_representative(flowrows, model, prompt, arm='g2'):
    """The episode closest to this lane's MEDIAN run_code count — typical, not cherry-picked."""
    R = [r for r in flowrows if r['model'] == model and r['prompt'] == prompt and r['arm'] == arm]
    R = [r for r in R if r.get('hypotheses')]
    if not R:
        return None
    med = st.median([r['n_code'] for r in R])
    return min(R, key=lambda r: (abs(r['n_code'] - med), r['label']))


CSS = """
:root{--bg:#0d1117;--panel:#161b22;--line:#283041;--ink:#e6edf3;--mut:#9aa7b4;--acc:#58a6ff;
--good:#3fb950;--warn:#d29922;--bad:#f85149}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);
font:15.5px/1.68 -apple-system,Segoe UI,Roboto,Arial,sans-serif;padding:30px}
.wrap{max-width:900px;margin:0 auto}h1{font-size:25px;margin:0 0 4px}
h2{font-size:19px;margin:34px 0 8px;border-left:3px solid var(--acc);padding-left:11px}
h3{font-size:15px;margin:20px 0 6px;color:var(--acc)}
.meta{color:var(--mut);font-size:13px;margin-bottom:10px}
.lead{color:var(--mut);font-size:13px;margin:8px 0 0}
.panel{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:16px 20px;margin:12px 0}
p{margin:10px 0}
table{border-collapse:collapse;width:100%;font-size:13px}
th,td{padding:6px 9px;border-bottom:1px solid var(--line);text-align:left}
th{color:var(--mut);font-weight:600;font-size:11.5px}
td.num,th.num{text-align:right;font-variant-numeric:tabular-nums}
.grp{font-weight:700}.mut{color:var(--mut)}
.tblwrap{overflow-x:auto}
code{background:#0b1220;padding:1px 5px;border-radius:4px;font-size:12px}
blockquote{margin:10px 0;padding:9px 14px;border-left:3px solid var(--line);
background:#0b1220;border-radius:0 6px 6px 0;color:#c9d4e0;font-size:13.5px}
blockquote .who{display:block;color:var(--mut);font-size:11px;margin-top:5px}
.arc{margin:10px 0;padding-left:18px;border-left:2px solid var(--line)}
.arc .step{margin:9px 0;font-size:13.5px}
.arc .n{color:var(--acc);font-weight:700;font-size:11px;letter-spacing:.5px}
.warn{background:#2a2410;border:1px solid #5c4a12;border-radius:8px;padding:13px 16px;margin:12px 0;
color:#e8d48a;font-size:13px}
.seq{font-family:ui-monospace,Menlo,monospace;font-size:11.5px;letter-spacing:1.5px}
.seq .c{color:var(--acc)}.seq .r{color:var(--good)}.seq .s{color:var(--warn)}
.foot{color:var(--mut);font-size:11.5px;margin-top:30px;border-top:1px solid var(--line);padding-top:12px}
"""


def rng(lo, hi):
    """'4' when the two ends are equal, '4-5' when they are not. '4-4' reads as a typo."""
    return lo if lo == hi else f"{lo}&ndash;{hi}"


def seq_html(shape, limit=48):
    out = ''.join(f"<span class='{ {'C':'c','R':'r','S':'s'}.get(ch,'') }'>{ch}</span>"
                  for ch in shape[:limit])
    return f"<span class='seq'>{out}{'&hellip;' if len(shape) > limit else ''}</span>"


def main():
    if not os.path.exists(FLOW):
        sys.exit(f"missing {FLOW} — run: BDG_RUNS=clean python scripts/cot_flow.py")
    flow = json.load(open(FLOW))
    rows = flow['episodes']
    sums = load_summaries()
    panel_data.require_data(len(sums), 'judge summaries', runs_config.SOURCE)
    lanes = [(m, p) for m, p, _ in runs_config.triples()]

    # ---------- how each model works ----------
    model_blocks = ''
    for model in dict.fromkeys(m for m, _ in lanes):
        per = {}
        for prompt in ('detailed', 'lean'):
            a = flow['by_lane'].get(f'{model} / {prompt}')
            if a:
                per[prompt] = a
        if not per:
            continue
        d = per.get('detailed') or list(per.values())[0]
        l = per.get('lean') or d
        S = [s for s in sums if s[1] == model]
        verdicts = [s[5].get('overall_verdict', '') for s in S if s[5].get('overall_verdict')]
        vq = sorted(verdicts, key=len)[len(verdicts) // 2] if verdicts else ''
        rep = pick_representative(rows, model, 'detailed')
        arc = ''
        if rep:
            for i, h in enumerate(rep['hypotheses'][:5], 1):
                arc += (f"<div class='step'><span class='n'>CHECKPOINT {i}</span><br>"
                        f"{esc(h[:330])}{'&hellip;' if len(h) > 330 else ''}</div>")
        model_blocks += f"""
<h3>{esc(model)}</h3>
<div class="panel">
<p>{esc(model)} runs <b>{d['code_calls']:.0f} code executions</b> in a typical staged episode and
<b>{l['code_calls']:.0f}</b> without the staged prompt, while logging
<b>{d['checkpoints']:.1f}</b> and <b>{l['checkpoints']:.1f}</b> narrated checkpoints. It spends
about <b>{d['wall_s']/60:.0f} minutes</b> per episode, <b>{d['pct_exec']:.0f}%</b> of it inside
code rather than waiting on the model.</p>
<p class="lead">A representative staged, blinded episode &mdash; the one closest to this lane's
median execution count, not a favourable pick:
{f"<code>{esc(rep['label'])}</code>, sequence {seq_html(rep['shape'])}" if rep else '&mdash;'}</p>
{f"<div class='arc'>{arc}</div>" if arc else ''}
{f'<blockquote>{esc(vq)}<span class="who">a judge, summing up one {esc(model)} episode</span></blockquote>' if vq else ''}
</div>"""

    # ---------- the ladder ----------
    arm_rows = ''
    for arm, (title, gloss) in ARM_STORY.items():
        a = flow['by_arm'].get(arm)
        if not a:
            continue
        M = a['median']
        arm_rows += (
            f"<tr><td class='grp'>{title}<span class='mut'><br>{gloss}</span></td>"
            f"<td class='num'>{a['n']}</td>"
            f"<td class='num'>{M['n_code']:.0f}<span class='mut'> / {a['code_calls']:.0f}</span></td>"
            f"<td class='num'>{M['n_checkpoints']:.0f}<span class='mut'> / {a['checkpoints']:.1f}</span></td>"
            f"<td class='num'>{M['mean_alternatives']:.1f}<span class='mut'> / {a['alternatives']:.1f}</span></td>"
            f"<td class='num'>{M['mean_evidence_against']:.1f}<span class='mut'> / {a['evidence_against']:.1f}</span></td>"
            f"<td class='num'>{M['pivots_measured']:.0f}<span class='mut'> / {a['pivots_measured']:.1f}</span></td>"
            f"<td class='num'>{M['conf_rise']:.2f}</td></tr>")
    g0, g2 = flow['by_arm'].get('g0'), flow['by_arm'].get('g2')
    _M = {a: flow['by_arm'][a]['median'] for a in ('g0', 'g1', 'g2', 'g3') if flow['by_arm'].get(a)}
    gm0, gm2, gm3 = (f"{_M[a]['n_checkpoints']:.0f}" for a in ('g0', 'g2', 'g3'))
    pv0, pv2, pv3 = (f"{_M[a]['pivots_measured']:.0f}" for a in ('g0', 'g2', 'g3'))
    gm23, pv23 = rng(gm2, gm3), rng(pv2, pv3)
    _alt = [_M[a]['mean_alternatives'] for a in _M]
    _ag = [_M[a]['mean_evidence_against'] for a in _M]
    alt_lo, alt_hi = f"{min(_alt):.1f}", f"{max(_alt):.1f}"
    alt_rng, ag_rng = rng(alt_lo, alt_hi), None
    ag_lo, ag_hi = f"{min(_ag):.1f}", f"{max(_ag):.1f}"
    ag_rng = rng(ag_lo, ag_hi)

    # ---------- recurring themes ----------
    weak = [t for s in sums for t in flat(s[5].get('weaknesses') or [])]
    strong = [t for s in sums for t in flat(s[5].get('strengths') or [])]
    # Count per JUDGE RECORD, not per statement: "in 43% of records a judge raised this" is a
    # readable rate, while "735 of 6,082 weakness sentences" is not, and a record that makes the
    # same complaint twice should not count twice.
    rec_hits = Counter()
    example = {}
    for s in sums:
        texts = list(flat(s[5].get('weaknesses') or []))
        for name, rx in THEME_RE:
            m = next((t for t in texts if rx.search(t)), None)
            if m:
                rec_hits[name] += 1
                example.setdefault(name, m)
    theme_rows = ''
    for name, _ in sorted(THEMES, key=lambda t: -rec_hits.get(t[0], 0)):
        w = rec_hits.get(name, 0)
        theme_rows += (f"<tr><td class='grp'>{esc(name)}</td>"
                       f"<td class='num'>{w/max(len(sums),1):.0%}</td>"
                       f"<td class='mut'>{esc(example.get(name, '')[:130])}</td></tr>")

    # ---------- the judges' vocabulary ----------
    strat = Counter(s[5].get('reasoning_strategy') for s in sums)
    top_strat, top_n = strat.most_common(1)[0]
    n_variants = len(strat)

    quotes = ''
    seen = set()
    for lab, model, prompt, arm, tag, d in sums:
        v = (d.get('overall_verdict') or '').strip()
        if arm == 'g3' and v and len(v) > 60 and model not in seen:
            quotes += (f"<blockquote>{esc(v)}<span class='who'>{esc(tag)} on "
                       f"<code>{esc(lab)}</code> &mdash; {esc(model)} / {esc(prompt)}</span>"
                       f"</blockquote>")
            seen.add(model)
    ov = flow['overall']

    html = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>TCGA Benchmark — How the Agents Worked</title><style>{CSS}</style></head>
<body><div class="wrap">
<h1>How the agents worked</h1>
<div class="meta">{flow['n_episodes']} episodes &middot; {esc(flow['source'])} &middot;
{len(sums)} judge summaries &middot; <code>scripts/gen_summary_report.py</code></div>

<div class="warn"><b>This is a descriptive summary, not a set of tests.</b> Numbers below are
shares and typical values &mdash; they say <i>usually</i> and <i>rarely</i>, and no significance is
claimed for any of them. The process figures are deterministic, parsed from the episode traces; the
quotes are the judges' own words. Where the two disagree, both are shown.</div>

<h2>The short version</h2>
<div class="panel">
<p>Across {flow['n_episodes']} episodes the agents behave far more alike in <i>what they conclude</i>
than in <i>how they get there</i>. Every lane opens the same way &mdash; orient to the matrices,
reduce dimensions, cluster expression, then look for survival separation and pathway support
&mdash; and the staged prompt makes that sequence explicit rather than changing it.</p>
<p>The differences that matter are in volume and in narration, and they do not track each other.
A typical episode runs <b>{ov['code_calls']:.0f}</b> code executions and records
<b>{ov['checkpoints']:.1f}</b> checkpoints, but the spread between models is enormous on the first
number and small on the second. <b>The judges read the checkpoints.</b></p>
<p>The clearest behavioural shift on the ladder is not in what the agents find but in how they
hold it. Under blinding they narrate more (median {gm2} checkpoints against {gm0} when the cohort
is disclosed), revise the working hypothesis more often (median {pv2} against {pv0}), and build
confidence during the run instead of starting confident. They do <i>not</i> run measurably more
code &mdash; that difference appears in the means and vanishes in the medians.</p>
</div>

<h2>How each model works</h2>
{model_blocks}

<h2>What withholding information does</h2>
<div class="panel"><div class="tblwrap"><table>
<thead><tr><th>arm</th><th class="num">episodes</th>
<th class="num">code runs<span class="mut">median / mean</span></th>
<th class="num">checkpoints<span class="mut">median / mean</span></th>
<th class="num">alternatives<span class="mut">median / mean</span></th>
<th class="num">evidence against<span class="mut">median / mean</span></th>
<th class="num">hypothesis changes<span class="mut">median / mean</span></th>
<th class="num">confidence rise<span class="mut">median</span></th></tr></thead>
<tbody>{arm_rows}</tbody></table></div>
<p class="lead"><b>Read the medians; the means are not safe here.</b> A handful of episodes dump
enormous lists into these fields &mdash; one logs <b>352</b> alternatives per checkpoint and
another <b>516</b> pieces of counter-evidence &mdash; and a single run of that kind moves a whole
arm's mean by two or three times. Both columns are shown so the gap is visible.
<br><b>What actually separates the arms.</b> Blinded and misled episodes narrate more
(median {gm23} checkpoints against {gm0} when the cohort is disclosed), revise the
working hypothesis more (median {pv23} against {pv0}), and build confidence during the
run rather than starting there. That is the explore signature, and it is the part that survives.
<br><b>What does not separate them, despite appearances.</b> On medians the arms run about the
same amount of code, weigh about the same number of alternatives ({alt_rng}) and
record about the same counter-evidence ({ag_rng}). Earlier drafts of this page said
G1 was &ldquo;the quietest arm&rdquo;, that G2 &ldquo;runs more analysis&rdquo;, and that G3
&ldquo;records the most counter-evidence&rdquo;. <b>All three were the outliers talking</b>, and
none of them survives the median.</p></div>

<h2>What the judges keep saying</h2>
<div class="panel">
<div class="tblwrap"><table><thead><tr><th>recurring criticism</th>
<th class="num">raised in</th><th>a typical phrasing</th>
</tr></thead><tbody>{theme_rows}</tbody></table></div>
<p class="lead">Share of the <b>{len(sums)}</b> judge records that raise each theme at least once,
drawn from <b>{len(weak)}</b> weakness statements (and <b>{len(strong)}</b> strengths, not shown).
A record can raise several themes, so the column does not sum to 100%. Matching is keyword-based
over free text &mdash; a way to surface the recurring complaints, not a measurement of them.</p>
</div>

<h2>Where the judges' language runs out</h2>
<div class="panel">
<p><b>{top_n} of {len(sums)}</b> judge records ({top_n/len(sums):.0%}) tag the reasoning strategy as
<code>{esc(top_strat)}</code>, across {n_variants} distinct tags used in total. The field is free
text with three suggested examples in the schema, and the judges converge on the first one almost
every time.</p>
<p class="lead">Two readings, and this data cannot separate them: the episodes really are alike
&mdash; which the process figures above support, since every lane runs the same broad sequence
&mdash; or the prompt anchors the judge. Either way <b>the tag carries almost no information</b>
and should not be used to distinguish models. The deterministic process record is the better
instrument for that.</p>
</div>

<h2>The mislead arm, in the judges' words</h2>
<div class="panel">
<p class="lead">One verdict per model from a G3 episode, where a false cohort label was planted
mid-run:</p>
{quotes or '<p class="lead">No G3 verdicts recorded.</p>'}
</div>

<div class="foot">Process figures: <code>scripts/cot_flow.py</code> &rarr;
<code>{esc(FLOW)}</code> and <code>FLOW_REPORT.html</code> (per-episode detail).
Quotes: the per-episode <code>cotsummary.json</code> written by each judge family.</div>
</div></body></html>"""
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    open(OUT, 'w').write(html)
    print(f'wrote {OUT}  ({len(html)} bytes)')
    print(f"  {flow['n_episodes']} episodes, {len(sums)} judge summaries, "
          f"{len(weak)} weakness statements themed")


if __name__ == '__main__':
    main()
