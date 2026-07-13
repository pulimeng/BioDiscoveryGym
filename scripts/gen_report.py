#!/usr/bin/env python3
"""Generate a TCGA benchmark comparison report (HTML) for ANY set of runs.

One parameterized report generator — replaces the old per-run one-offs
(gen_run1_report / gen_run2_report / gen_merged_report / gen_model_comparison).

Each --model is "Label:run_dir[:#hexcolor]". Outcome is read from *_v3scores.json;
grounding (mean support /5) is auto-included per model when *_supportscores.json
exist in that run dir, and omitted otherwise (no hardcoded "outcome only" caveat).

  python scripts/gen_report.py \
      --model "GPT-5.5:results/tcga/ladder/gpt55_20260707:#1D9E75" \
      --model "Claude Sonnet:results/tcga/run1+2:#7F77DD" \
      --model "Gemini 2.5 Pro:results/tcga/ladder/gemini25_:#D29922" \
      --out results/tcga/ladder/MODEL_COMPARISON.html

  # lean-vs-detailed ablation (same script, different run dirs):
  python scripts/gen_report.py \
      --model "GPT-5.5 detailed:results/tcga/ladder/gpt55_20260707:#1D9E75" \
      --model "GPT-5.5 lean:results/tcga/_ablation/lean_gpt55:#58a6ff" \
      --title "TCGA — lean vs detailed prompt (GPT-5.5)" --out results/tcga/_ablation/LEAN_VS_DETAILED.html
"""
import glob, os, json, argparse, statistics as st

COHORTS_DEFAULT = ['BRCA', 'LIHC', 'LUAD', 'OV']
PALETTE = ['#1D9E75', '#7F77DD', '#D29922', '#58a6ff', '#f85149', '#3fb950']  # cycled if no :color


def parse_model(spec, i):
    """'Label:dir[:#color]' -> (label, dir, color). Colon in the label is fine; the run dir
    is the last colon-field unless a #color trails it."""
    parts = spec.split(':')
    color = None
    if parts[-1].startswith('#'):
        color = parts[-1]; parts = parts[:-1]
    root = parts[-1]
    label = ':'.join(parts[:-1]) or os.path.basename(root)
    return label, root, (color or PALETTE[i % len(PALETTE)])


def load(root):
    """Per-episode: arm group, cohort, seed, normalized outcome, identity verdict, support /5."""
    EP = []
    for sc in glob.glob(f"{root}/**/*_v3scores.json", recursive=True):
        lab = os.path.basename(sc).replace('_v3scores.json', '')
        d = json.load(open(sc))
        if not d.get('raw_scores'):
            continue
        epj = sc.replace('_v3scores.json', '.json'); c = s = mis = None
        try:
            e = json.load(open(epj)); c = e.get('cohort'); s = e.get('seed')
            mis = (e.get('cli') or {}).get('mislead_cohort')
        except Exception:
            pass
        sup = None
        supf = sc.replace('_v3scores.json', '_supportscores.json')
        if os.path.exists(supf):
            try:
                sd = json.load(open(supf))
                sup = sd.get('support_score')
            except Exception:
                pass
        EP.append(dict(grp=lab.split('_')[0], cohort=c, seed=s, mis=mis, norm=d['normalized'],
                       verdict=d.get('cohort_identity_verdict') or '', support=sup))
    return EP


def honest_stats(EP, c):
    vs = [e['norm'] for e in EP if e['grp'] in ('g0', 'g1', 'g2') and e['cohort'] == c]
    return (round(st.mean(vs), 3), round(st.pstdev(vs), 3), len(vs)) if vs else (None, None, 0)


def allhon(EP):
    vs = [e['norm'] for e in EP if e['grp'] in ('g0', 'g1', 'g2')]
    return round(st.mean(vs), 3) if vs else 0.0


def ground_mean(EP):
    vs = [e['support'] for e in EP if e['grp'] in ('g0', 'g1', 'g2') and e['support'] is not None]
    return round(st.mean(vs), 2) if vs else None


def fooled(EP, grp):
    es = [e for e in EP if e['grp'] == grp]
    return sum(1 for e in es if e['verdict'] == 'mislead_cohort'), len(es)


CSS = """
:root{--bg:#0d1117;--panel:#161b22;--line:#283041;--ink:#e6edf3;--mut:#9aa7b4;--acc:#58a6ff;--good:#3fb950;--bad:#f85149;--mis:#d29922}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.55 -apple-system,Segoe UI,Roboto,Arial,sans-serif;padding:30px}
.wrap{max-width:900px;margin:0 auto}h1{font-size:24px;margin:0 0 2px}
h2{font-size:17px;margin:30px 0 6px;border-left:3px solid var(--acc);padding-left:10px}
.meta{color:var(--mut);font-size:13px;margin-bottom:6px}.lead{color:var(--mut);font-size:13.5px;margin:2px 0 10px}
.panel{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:14px 18px;margin:12px 0}
table{border-collapse:collapse;width:100%;font-size:13px}th,td{padding:7px 9px;border-bottom:1px solid var(--line);text-align:left}
th{color:var(--mut);font-weight:600;font-size:12px}td.num,th.num{text-align:center;font-variant-numeric:tabular-nums}
.grp{font-weight:700}.sd{color:var(--mut);font-size:11px}.bad{color:var(--bad);font-weight:700}
.kfind{display:grid;grid-template-columns:26px 1fr;gap:10px;margin:9px 0}.kfind .ix{font-size:19px}
.legend{display:flex;gap:16px;margin:4px 0 8px;font-size:12px;color:var(--mut)}.legend span{display:flex;align-items:center;gap:5px}.legend i{width:11px;height:11px;border-radius:2px;display:inline-block}
.chartbox{position:relative;width:100%;height:320px}
.warn{background:#2a2410;border:1px solid #5c4a12;border-radius:8px;padding:12px 16px;margin:12px 0;color:#e8d48a;font-size:13.5px}
.foot{color:var(--mut);font-size:11.5px;margin-top:26px;border-top:1px solid var(--line);padding-top:12px}
code{background:#0b1220;padding:1px 5px;border-radius:4px;font-size:12px}
"""

JS = """
var ink='#e6edf3',grid='rgba(255,255,255,0.10)';
var DS=__DS__;
var errPlugin={id:'err',afterDatasetsDraw:function(chart){var ctx=chart.ctx,y=chart.scales.y;ctx.save();ctx.strokeStyle=ink;ctx.lineWidth=1.3;
 chart.data.datasets.forEach(function(dset,di){if(!dset.errors)return;var meta=chart.getDatasetMeta(di);meta.data.forEach(function(bar,i){var e=dset.errors[i],m=dset.data[i];if(e==null||m==null||e===0)return;var x=bar.x,yt=y.getPixelForValue(m+e),yb=y.getPixelForValue(m-e),cap=4;ctx.beginPath();ctx.moveTo(x,yt);ctx.lineTo(x,yb);ctx.moveTo(x-cap,yt);ctx.lineTo(x+cap,yt);ctx.moveTo(x-cap,yb);ctx.lineTo(x+cap,yb);ctx.stroke();});});ctx.restore();}};
new Chart(document.getElementById('mc'),{type:'bar',
 data:{labels:__COH__,datasets:DS.map(function(d){return{label:d.label,backgroundColor:d.color,data:d.data,errors:d.errors,borderWidth:0,categoryPercentage:0.7,barPercentage:0.9};})},
 options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{display:false},tooltip:{callbacks:{label:function(c){var e=c.dataset.errors[c.dataIndex];return c.dataset.label+': '+c.parsed.y.toFixed(3)+(e!=null?' ± '+e.toFixed(3):'');}}}},
 scales:{y:{min:0,max:0.65,ticks:{color:ink,stepSize:0.1,callback:function(v){return v.toFixed(1);}},grid:{color:grid},title:{display:true,text:'outcome (faithfulness) — honest arms',color:ink}},x:{ticks:{color:ink,font:{size:13}},grid:{display:false}}}},plugins:[errPlugin]});
"""


def build(models, cohorts, title):
    data = {m[0]: load(m[1]) for m in models}
    names = [m[0] for m in models]

    # chart datasets
    chart_ds = [{'label': lab, 'color': col,
                 'data': [honest_stats(data[lab], c)[0] for c in cohorts],
                 'errors': [honest_stats(data[lab], c)[1] for c in cohorts]}
                for lab, _, col in models]
    js = JS.replace('__DS__', json.dumps(chart_ds)).replace('__COH__', json.dumps(cohorts))

    mhead = "".join(f'<th class="num">{n}</th>' for n in names)

    # cohort table
    crows = ""
    for c in cohorts:
        cells = ""
        for n in names:
            m, sd, _ = honest_stats(data[n], c)
            cells += f'<td class="num">{m:.3f} <span class="sd">±{sd:.3f}</span></td>' if m is not None else '<td class="num">—</td>'
        crows += f'<tr><td class="grp">{c}</td>{cells}</tr>'
    allrow = "".join(f'<td class="num"><b>{allhon(data[n]):.3f}</b></td>' for n in names)

    # grounding row (only if ANY model has support scores)
    grounds = {n: ground_mean(data[n]) for n in names}
    ground_row = ""
    if any(v is not None for v in grounds.values()):
        cells = "".join(f'<td class="num">{grounds[n]:.2f}/5</td>' if grounds[n] is not None else '<td class="num">—</td>' for n in names)
        ground_row = f'<tr style="border-top:2px solid var(--line)"><td class="grp">grounding (support /5)</td>{cells}</tr>'
    missing_ground = [n for n in names if grounds[n] is None]

    # fooling rows
    frows = ""
    for grp, lbl in [('g3a', 'G3a mislead·early'), ('g3b', 'G3b mislead·late')]:
        cells = ""
        for n in names:
            f, tot = fooled(data[n], grp)
            cls = 'bad' if tot and f > tot / 2 else ''
            cells += f'<td class="num {cls}">{f}/{tot}</td>'
        frows += f'<tr><td class="grp">{lbl}</td>{cells}</tr>'

    # data-driven summary (no hand-written per-run prose)
    ranked = sorted(names, key=lambda n: allhon(data[n]), reverse=True)
    best = ranked[0]
    diff_order = sorted(cohorts, key=lambda c: (honest_stats(data[best], c)[0] or 0), reverse=True)
    summ = (f'<div class="kfind"><div class="ix">📈</div><div><b>{best}</b> leads on outcome '
            f'(honest mean {allhon(data[best]):.3f}). Full ranking: '
            + " · ".join(f"{n} {allhon(data[n]):.3f}" for n in ranked) + '.</div></div>'
            f'<div class="kfind"><div class="ix">🧬</div><div>Difficulty ordering (by {best}): '
            + " &gt; ".join(diff_order) + '.</div></div>')

    warn = ""
    if missing_ground:
        warn = (f'<div class="warn"><b>Grounding partial.</b> Support scores missing for: '
                f'<b>{", ".join(missing_ground)}</b>. Run <code>scripts/score_run.sh &lt;dir&gt;</code> '
                f'to fill them; outcome comparison is complete regardless.</div>')

    counts = " · ".join(f"{n} ({sum(1 for e in data[n] if e['grp'] in ('g0','g1','g2'))} honest eps)" for n in names)
    leg = "".join(f'<span><i style="background:{col}"></i>{n}</span>' for n, _, col in models)

    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title><style>{CSS}</style></head><body><div class="wrap">
<h1>{title}</h1>
<div class="meta">{counts} · outcome scorer (v3, neutral DeepSeek judge) · honest arms G0–G2</div>
{warn}
<h2>Summary</h2>
<div class="panel">{summ}</div>

<h2>Outcome by cohort (honest arms)</h2>
<div class="panel">
<div class="legend">{leg}</div>
<div class="chartbox"><canvas id="mc" role="img" aria-label="Grouped bar chart of outcome score by cohort per model, with error bars."></canvas></div>
<table><thead><tr><th>cohort</th>{mhead}</tr></thead><tbody>{crows}
<tr style="border-top:2px solid var(--line)"><td class="grp">ALL honest</td>{allrow}</tr>
{ground_row}</tbody></table>
<p class="lead">Error bars / ± = 1 SD across seeds. Grounding row = mean support (/5) over honest arms, shown when support scores exist.</p>
</div>

<h2>Fooling (G3 mislead arms)</h2>
<div class="panel">
<table><thead><tr><th>arm</th>{mhead}</tr></thead><tbody>{frows}</tbody></table>
<p class="lead">Cells = episodes committed to the wrong (mislead) cohort. Report the early(G3a)≫late(G3b) gradient per-model — it does not always generalize.</p>
</div>

<div class="foot">Outcome from <code>*_v3scores.json</code>, grounding from <code>*_supportscores.json</code>. Generated by <code>scripts/gen_report.py</code>. Chart is Chart.js (loads from cdnjs online).</div>
</div>
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.js"></script>
<script>{js}</script>
</body></html>"""


def main():
    ap = argparse.ArgumentParser(description="Parameterized TCGA benchmark comparison report.")
    ap.add_argument('--model', action='append', required=True, metavar='LABEL:DIR[:#COLOR]',
                    help='repeatable; e.g. "GPT-5.5:results/tcga/ladder/gpt55_20260707:#1D9E75"')
    ap.add_argument('--out', default='results/tcga/ladder/MODEL_COMPARISON.html')
    ap.add_argument('--title', default='TCGA Agent Benchmark — Model Comparison')
    ap.add_argument('--cohorts', default=','.join(COHORTS_DEFAULT))
    a = ap.parse_args()
    models = [parse_model(s, i) for i, s in enumerate(a.model)]
    cohorts = [c.strip() for c in a.cohorts.split(',') if c.strip()]
    html = build(models, cohorts, a.title)
    os.makedirs(os.path.dirname(a.out) or '.', exist_ok=True)
    open(a.out, 'w').write(html)
    print("wrote", a.out, len(html), "bytes")
    for lab, root, _ in models:
        ep = load(root)
        print(f"  {lab}: honest outcome {allhon(ep):.3f}"
              + (f" | grounding {ground_mean(ep):.2f}/5" if ground_mean(ep) is not None else " | grounding —"))


if __name__ == '__main__':
    main()
