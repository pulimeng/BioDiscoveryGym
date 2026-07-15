#!/usr/bin/env python3
"""Detailed 3-model report — outcome (v3) + support/grounding, with per-model cards,
per-episode tables, and the judge's evidence quotes. Judge: DeepSeek-v4-pro (neutral)."""
import glob, os, json, html as H, statistics as st
from collections import Counter

MODELS = [
    ('Sonnet 5', 'results/tcga/ladder/sonnet5_20260713', '#7F77DD'),
    ('GPT-5.5', 'results/tcga/ladder/gpt55_20260707', '#1D9E75'),
    ('Gemini 2.5', 'results/tcga/ladder/gemini25_', '#EF9F27'),
]
cohorts = ['BRCA', 'LIHC', 'LUAD', 'OV']

def load(root):
    R = []
    for sp in glob.glob(f"{root}/**/*_supportscores.json", recursive=True):
        lab = os.path.basename(sp).replace('_supportscores.json', '')
        d = json.load(open(sp)); L = d['levels']
        vd = json.load(open(sp.replace('_supportscores.json', '_v3scores.json')))
        e = json.load(open(sp.replace('_supportscores.json', '.json')))
        mech = (e.get('discovery') or {}).get('mechanism_hypothesis', '') or ''
        R.append(dict(lab=lab, arm=lab.split('_')[0], cohort=e.get('cohort'), seed=e.get('seed'),
            norm=vd['normalized'], verdict=vd.get('cohort_identity_verdict'), ss=d['support_score'],
            lvl={k: L[k] for k in ('d1_partition', 'd2_identity', 'd3_mechanism')}, mech=mech))
    return R

DATA = {name: load(root) for name, root, _ in MODELS}
COL = {name: col for name, _, col in MODELS}

def stats(R):
    hon = [x for x in R if x['arm'] in ('g0', 'g1', 'g2')]
    def ng(dk):
        c = Counter(x['lvl'][dk]['support'] for x in hon); t = sum(c.values())
        return (c.get('unsupported', 0) + c.get('anchored', 0)) / t
    return dict(outcome=st.mean([x['norm'] for x in hon]), osd=st.pstdev([x['norm'] for x in hon]),
        support=st.mean([x['ss'] for x in hon]),
        cby={c: st.mean([x['norm'] for x in hon if x['cohort'] == c]) for c in cohorts},
        csd={c: st.pstdev([x['norm'] for x in hon if x['cohort'] == c]) for c in cohorts},
        id_ng=ng('d2_identity'), d1_ng=ng('d1_partition'), d3_ng=ng('d3_mechanism'),
        fa=sum(1 for x in R if x['arm'] == 'g3a' and x['verdict'] == 'mislead_cohort'),
        fb=sum(1 for x in R if x['arm'] == 'g3b' and x['verdict'] == 'mislead_cohort'))
S = {m: stats(DATA[m]) for m in DATA}
ranked = sorted(S, key=lambda m: -S[m]['outcome'])
best, worst = ranked[0], ranked[-1]

CAV = {
 'Sonnet 5': "Strongest on both axes and the best-grounded identity caller ({id}%). Weakness: most susceptible to <b>early</b> mislead (g3a {fa}/6) — when the false frame lands before it forms its own read, it anchors; and it leans on recalled schemes for partition slightly more than the others.",
 'GPT-5.5': "The balanced all-rounder — middle on both axes, top on BRCA ({brca}). Always derives its partition and grounds mechanism. Weakness: moderate identity recall ({id}%) and symmetric fooling ({fa}/6 early, {fb}/6 late) — no standout strength or failure.",
 'Gemini 2.5': "Weakest on both axes, highest variance. Defining flaw is <b>identity</b>: it commits to a grouping without ever identifying the cancer type <b>{id}%</b> of the time (~{gap:.0f}× {best}); the only model with anchored mechanisms (D3 {d3}%). Most fooled <b>late</b> (g3b {fb}/6). An outcome-only leaderboard badly understates this gap.",
}
def cav(m):
    s = S[m]; gap = S[worst]['id_ng'] / max(S[best]['id_ng'], 0.01)
    return CAV[m].format(id=f"{s['id_ng']:.0%}", d3=f"{s['d3_ng']:.0%}", fa=s['fa'], fb=s['fb'],
                         brca=f"{s['cby']['BRCA']:.3f}", gap=gap, best=best)

def esc(t): return H.escape(str(t or ''))
CH = {'grounded': ('g', 'gr'), 'unsupported': ('m', 'un'), 'anchored': ('b', 'an')}
def chip(sup):
    c, ab = CH.get(sup, ('n', '?')); return f'<span class="chip {c}" title="{sup}">{ab}</span>'

# ---- per-model × arm table ----
arms = ['g0', 'g1', 'g2', 'g3a', 'g3b']
armtab = ""
for m in ranked:
    cells = ""
    for a in arms:
        es = [x for x in DATA[m] if x['arm'] == a]
        o = st.mean([x['norm'] for x in es]); ss = st.mean([x['ss'] for x in es])
        cells += f'<td class="num">{o:.3f}<span class="sub">s{ss:.1f}</span></td>'
    armtab += f'<tr><td class="grp" style="color:{COL[m]}">{m}</td>{cells}</tr>'

# ---- identity deep-dive: grounded vs unsupported evidence ----
def d2_examples(support, k=3):
    out = []
    for m in ranked:
        for x in DATA[m]:
            if x['arm'] in ('g0','g1','g2') and x['lvl']['d2_identity']['support'] == support:
                out.append((m, x))
    return out
uns = d2_examples('unsupported'); grd = d2_examples('grounded')
# prefer the same-episode contrast + a spread of models
def pick(lst, want_models, n):
    seen=set(); res=[]
    for m,x in lst:
        if m in want_models and m not in seen:
            res.append((m,x)); seen.add(m)
        if len(res)>=n: break
    for m,x in lst:
        if len(res)>=n: break
        res.append((m,x))
    return res[:n]
uns_pick = pick(uns, ['Gemini 2.5','GPT-5.5','Sonnet 5'], 3)
grd_pick = pick(grd, ['Sonnet 5','GPT-5.5','Gemini 2.5'], 2)
def ev_card(m, x, kind):
    d2 = x['lvl']['d2_identity']
    return (f'<div class="ev {kind}"><div class="evh"><b style="color:{COL[m]}">{m}</b> · <code>{x["lab"]}</code> '
            f'<span class="chip {CH[d2["support"]][0]}">{d2["support"]}</span></div>'
            f'<div class="evq">“{esc(d2.get("evidence"))}”</div></div>')
uns_html = "".join(ev_card(m, x, 'bad') for m, x in uns_pick)
grd_html = "".join(ev_card(m, x, 'good') for m, x in grd_pick)

# ---- per-episode collapsible tables ----
def ep_rows(R):
    rows = ""
    for x in sorted(R, key=lambda z: (z['arm'], str(z['cohort']), str(z['seed']))):
        L = x['lvl']; fooled = ' 🎣' if x['verdict'] == 'mislead_cohort' else ''
        rows += (f'<tr><td>{x["arm"]}{fooled}</td><td>{x["cohort"]}</td><td class="num">{x["seed"]}</td>'
                 f'<td class="num">{x["norm"]:.3f}</td><td class="num">{x["ss"]:.1f}</td>'
                 f'<td>{chip(L["d1_partition"]["support"])}{chip(L["d2_identity"]["support"])}{chip(L["d3_mechanism"]["support"])}</td>'
                 f'<td class="evq2">{esc(L["d2_identity"].get("evidence"))[:160]}</td></tr>')
    return rows
epsections = ""
for m in ranked:
    epsections += (f'<details><summary><b style="color:{COL[m]}">{m}</b> — 48 episodes '
        f'(outcome {S[m]["outcome"]:.3f} · identity-unsupported {S[m]["id_ng"]:.0%})</summary>'
        f'<div class="tblwrap"><table class="ep"><thead><tr><th>arm</th><th>cohort</th><th class="num">seed</th>'
        f'<th class="num">outcome</th><th class="num">support</th><th>D1·D2·D3</th><th>D2 identity — judge evidence</th></tr></thead>'
        f'<tbody>{ep_rows(DATA[m])}</tbody></table></div></details>')

# ---- charts data ----
out_ds = [{'label': m, 'color': COL[m], 'data': [round(S[m]['cby'][c], 3) for c in cohorts], 'errors': [round(S[m]['csd'][c], 3) for c in cohorts]} for m in ranked]
id_data = {'labels': ranked, 'colors': [COL[m] for m in ranked], 'vals': [round(S[m]['id_ng'], 3) for m in ranked]}

# ---- radar / capability profile (6 axes, outcome-visible -> process-hidden) ----
def clamp(v): return max(0.0, min(1.0, v))
RAX = ['Faithfulness', 'Hard-cohort (OV)', 'Consistency', 'Support score', 'Fooling resist.', 'Identity grounding']
def radar_vals(m):
    s = S[m]
    return [round(clamp(s['outcome']/0.65), 3), round(clamp(s['cby']['OV']/0.5), 3),
            round(clamp(1 - s['osd']/0.15), 3), round(clamp(s['support']/5), 3),
            round(clamp(1 - (s['fa']+s['fb'])/12), 3), round(clamp(1 - s['id_ng']), 3)]
radar_models = [{'label': m, 'color': COL[m], 'vals': radar_vals(m)} for m in ranked]
# companion raw-value table
raw_axis = [
    ('Faithfulness', lambda s: f"{s['outcome']:.3f}"),
    ('Hard-cohort (OV)', lambda s: f"{s['cby']['OV']:.3f}"),
    ('Consistency (SD, ↓)', lambda s: f"{s['osd']:.3f}"),
    ('Support score /5', lambda s: f"{s['support']:.2f}"),
    ('Fooling resist. (fooled/12, ↓)', lambda s: f"{s['fa']+s['fb']}/12"),
    ('Identity grounding (unsupp, ↓)', lambda s: f"{s['id_ng']:.0%}"),
]
radrows = ""
for lbl, fn in raw_axis:
    radrows += f'<tr><td>{lbl}</td>' + "".join(f'<td class="num">{fn(S[m])}</td>' for m in ranked) + '</tr>'

# ---- what 'outcome' measures: the 7 v3 components ----
COMP = [
    ('clinical_signal', 3, 'Survival separation across the subtypes (Cox / log-rank)'),
    ('structure_validity', 2, 'Cluster compactness &amp; stability (silhouette, bootstrap ARI)'),
    ('genomic_coherence_drivers', 2, 'Driver-mutation association with the subtypes'),
    ('reference_concordance', 2, 'Agreement with canonical TCGA subtypes (NMI)'),
    ('marker_evidence', 2, 'Submitted markers are real &amp; discriminative (OvR AUC, OncoKB)'),
    ('mechanism_grounding', 2, 'Hypothesis coherence &amp; data-grounding (LLM-judged)'),
    ('pathway_validity', 1, 'Submitted pathways valid &amp; enriched (ORA)'),
]
# per-component means (honest) from v3scores
comp_vals = {m: {} for m in ranked}
for name, root, _ in MODELS:
    acc = {k: [] for k, _, _ in COMP}
    for sp in glob.glob(f"{root}/**/*_v3scores.json", recursive=True):
        lab = os.path.basename(sp)
        if lab.split('_')[0] not in ('g0', 'g1', 'g2'): continue
        rs = json.load(open(sp))['raw_scores']
        for k, _, _ in COMP:
            if k in rs: acc[k].append(rs[k])
    for k, _, _ in COMP:
        comp_vals[name][k] = st.mean(acc[k]) if acc[k] else 0.0
comprows = ""
for key, wt, desc in COMP:
    cells = ""
    for m in ranked:
        v = comp_vals[m][key]
        lo = v < 0.75 * max(comp_vals[mm][key] for mm in ranked)  # flag notably-below-peer
        cells += f'<td class="num{" mis" if lo else ""}">{v:.2f}</td>'
    comprows += f'<tr><td class="grp">{key.replace("_", " ")}</td><td class="num">{wt}×</td><td class="lead" style="margin:0">{desc}</td>{cells}</tr>'

# ---- cohort difficulty decomposition (pooled across models, honest) ----
DIFF_COMP = ['clinical_signal', 'genomic_coherence_drivers', 'reference_concordance', 'structure_validity', 'pathway_validity']
coh_norm = {c: [] for c in cohorts}; coh_comp = {c: {k: [] for k in DIFF_COMP} for c in cohorts}
for name, root, _ in MODELS:
    for sp in glob.glob(f"{root}/**/*_v3scores.json", recursive=True):
        lab = os.path.basename(sp)
        if lab.split('_')[0] not in ('g0', 'g1', 'g2'): continue
        e = json.load(open(sp.replace('_v3scores.json', '.json'))); c = e.get('cohort')
        if c not in cohorts: continue
        d = json.load(open(sp)); coh_norm[c].append(d['normalized'])
        for k in DIFF_COMP:
            if k in d['raw_scores']: coh_comp[c][k].append(d['raw_scores'][k])
coh_order = sorted(cohorts, key=lambda c: -st.mean(coh_norm[c]))
diffrows = ""
for c in coh_order:
    cells = ""
    for k in DIFF_COMP:
        v = st.mean(coh_comp[c][k]); lo = v < 0.6 * max(st.mean(coh_comp[cc][k]) for cc in cohorts)
        cells += f'<td class="num{" bad" if v < 0.05 else (" mis" if lo else "")}">{v:.2f}</td>'
    diffrows += f'<tr><td class="grp">{c}</td><td class="num"><b>{st.mean(coh_norm[c]):.3f}</b></td>{cells}</tr>'
diffhead = "".join(f'<th class="num">{k.split("_")[0][:6]}{"·"+k.split("_")[-1][:3] if "_" in k else ""}</th>' for k in DIFF_COMP)

# ---- literature volume vs identity grounding ----
PAPERS = {'BRCA': 13305, 'LUAD': 2091, 'OV': 1982, 'LIHC': 1159}  # PubMed "<cancer> molecular subtypes", 2026-07
id_grounded = {m: {} for m in ranked}
for name, root, _ in MODELS:
    for c in cohorts:
        vs = []
        for sp in glob.glob(f"{root}/**/*_supportscores.json", recursive=True):
            lab = os.path.basename(sp)
            if lab.split('_')[0] not in ('g0', 'g1', 'g2'): continue
            e = json.load(open(sp.replace('_supportscores.json', '.json')))
            if e.get('cohort') != c: continue
            vs.append(1 if json.load(open(sp))['levels']['d2_identity']['support'] == 'grounded' else 0)
        id_grounded[name][c] = round(st.mean(vs), 3) if vs else None
lit_order = sorted(cohorts, key=lambda c: PAPERS[c])
scat_ds = [{'label': m, 'color': COL[m],
            'points': [{'x': PAPERS[c], 'y': id_grounded[m][c], 'c': c} for c in lit_order]} for m in ranked]

# ---- tiles + cards ----
tiles = ""
for m in ranked:
    s = S[m]
    tiles += (f'<div class="tile" style="border-left:3px solid {COL[m]}"><div class="tl">{m}</div>'
        f'<div class="tg"><span>outcome</span><b>{s["outcome"]:.3f}</b></div>'
        f'<div class="tg"><span>support/5</span><b>{s["support"]:.2f}</b></div>'
        f'<div class="tg"><span>id-unsupported</span><b class="{"bad" if s["id_ng"]>=.4 else ("mis" if s["id_ng"]>=.25 else "good")}">{s["id_ng"]:.0%}</b></div></div>')

cards = ""
for i, m in enumerate(ranked):
    s = S[m]; cb = ""
    for c in cohorts:
        w = int(s['cby'][c]/0.65*100)
        cb += f'<div class="cbar"><span class="cl">{c}</span><div class="ct"><div style="width:{w}%;background:{COL[m]}"></div></div><span class="cv">{s["cby"][c]:.3f}</span></div>'
    idc = 'bad' if s['id_ng'] >= .4 else ('mis' if s['id_ng'] >= .25 else 'good')
    cards += (f'<div class="card" style="border-top:3px solid {COL[m]}"><div class="chd"><span class="rank">#{i+1}</span><h3>{m}</h3></div>'
        f'<div class="idbox {idc}"><span>identity recall unsupported</span><b>{s["id_ng"]:.0%}</b></div>'
        f'<div class="cbars">{cb}</div>'
        f'<div class="mini">fooled g3a {s["fa"]}/6 · g3b {s["fb"]}/6 · D1/D3 not-grounded {s["d1_ng"]:.0%}/{s["d3_ng"]:.0%}</div>'
        f'<div class="cav"><b>Caveat.</b> {cav(m)}</div></div>')

CSS = """
:root{--bg:#0d1117;--panel:#161b22;--line:#283041;--ink:#e6edf3;--mut:#9aa7b4;--acc:#58a6ff;--good:#3fb950;--bad:#f85149;--mis:#d29922}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.55 -apple-system,Segoe UI,Roboto,Arial,sans-serif;padding:30px}
.wrap{max-width:1040px;margin:0 auto}h1{font-size:24px;margin:0 0 2px}h3{margin:0;font-size:16px}
h2{font-size:17px;margin:30px 0 8px;border-left:3px solid var(--acc);padding-left:10px}
.meta{color:var(--mut);font-size:13px;margin-bottom:6px}.lead{color:var(--mut);font-size:13px;margin:2px 0 10px}
.panel{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:14px 18px;margin:12px 0}
.tiles{display:grid;grid-template-columns:1fr 1fr 1fr;gap:12px;margin:12px 0}
.tile{background:var(--panel);border:1px solid var(--line);border-radius:9px;padding:10px 12px}.tl{font-size:13px;font-weight:600;margin-bottom:6px}
.tg{display:flex;justify-content:space-between;font-size:12px;color:var(--mut);margin:2px 0}.tg b{color:var(--ink);font-size:14px}
.legend{display:flex;gap:16px;margin:4px 0 8px;font-size:12px;color:var(--mut)}.legend span{display:flex;align-items:center;gap:5px}.legend i{width:11px;height:11px;border-radius:2px;display:inline-block}
.chartbox{position:relative;width:100%;height:290px}
.kfind{display:grid;grid-template-columns:26px 1fr;gap:10px;margin:9px 0}.kfind .ix{font-size:19px}
.cards{display:grid;grid-template-columns:1fr 1fr 1fr;gap:14px}@media(max-width:820px){.cards,.tiles{grid-template-columns:1fr}}
.card{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:14px}
.chd{display:flex;align-items:center;gap:8px;margin-bottom:10px}.rank{font-size:12px;font-weight:700;color:var(--mut);background:#0b1220;padding:2px 7px;border-radius:6px}
.idbox{display:flex;justify-content:space-between;align-items:center;border-radius:7px;padding:7px 10px;font-size:12px;margin-bottom:10px}.idbox b{font-size:17px}
.idbox.good{background:#13322b;color:var(--good)}.idbox.mis{background:#3a2d10;color:var(--mis)}.idbox.bad{background:#3a1414;color:var(--bad)}
.cbars{margin-bottom:10px}.cbar{display:flex;align-items:center;gap:6px;margin:3px 0;font-size:11px}
.cl{width:34px;color:var(--mut)}.ct{flex:1;height:9px;background:#0b1220;border-radius:4px;overflow:hidden}.ct div{height:100%}.cv{width:38px;text-align:right;font-variant-numeric:tabular-nums}
.mini{font-size:11px;color:var(--mut);border-top:1px solid var(--line);padding-top:8px;margin-bottom:8px}.cav{font-size:12px;line-height:1.5}
table{border-collapse:collapse;width:100%;font-size:12.5px}th,td{padding:6px 8px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}
th{color:var(--mut);font-weight:600;font-size:11.5px}td.num,th.num{text-align:center;font-variant-numeric:tabular-nums}.grp{font-weight:700}.sub{display:block;font-size:9px;color:var(--mut)}
.chip{display:inline-block;min-width:20px;text-align:center;font-size:9.5px;font-weight:700;border-radius:4px;padding:1px 3px;margin-right:2px}
.chip.g{background:#13322b;color:var(--good)}.chip.m{background:#3a2d10;color:var(--mis)}.chip.b{background:#3a1414;color:var(--bad)}.chip.n{background:#222;color:var(--mut)}
.ev{border-radius:8px;padding:10px 12px;margin:8px 0;border-left:3px solid var(--line)}.ev.bad{border-left-color:var(--bad)}.ev.good{border-left-color:var(--good)}
.evh{font-size:12px;margin-bottom:4px}.evq{font-size:12.5px;color:var(--ink);font-style:italic}.evq2{color:var(--mut);font-size:11px;font-style:italic;max-width:340px}
details{background:var(--panel);border:1px solid var(--line);border-radius:9px;margin:8px 0;padding:0 14px}
summary{cursor:pointer;padding:11px 0;font-size:13.5px}.tblwrap{overflow-x:auto;padding-bottom:10px}table.ep{min-width:640px}
.warn{background:#2a2410;border:1px solid #5c4a12;border-radius:8px;padding:12px 16px;margin:12px 0;color:#e8d48a;font-size:13px}
.foot{color:var(--mut);font-size:11.5px;margin-top:26px;border-top:1px solid var(--line);padding-top:12px}
code{background:#0b1220;padding:1px 5px;border-radius:4px;font-size:11.5px}.bad{color:var(--bad)}.good{color:var(--good)}.mis{color:var(--mis)}
"""

JS = """
var ink='#e6edf3',grid='rgba(255,255,255,0.10)';var OUT=__OUT__,ID=__ID__;
var errP={id:'err',afterDatasetsDraw:function(chart){var ctx=chart.ctx,y=chart.scales.y;ctx.save();ctx.strokeStyle=ink;ctx.lineWidth=1.2;chart.data.datasets.forEach(function(dset,di){if(!dset.errors)return;var meta=chart.getDatasetMeta(di);meta.data.forEach(function(bar,i){var e=dset.errors[i],m=dset.data[i];if(e==null||m==null||e===0)return;var x=bar.x,yt=y.getPixelForValue(m+e),yb=y.getPixelForValue(m-e),cap=3;ctx.beginPath();ctx.moveTo(x,yt);ctx.lineTo(x,yb);ctx.moveTo(x-cap,yt);ctx.lineTo(x+cap,yt);ctx.moveTo(x-cap,yb);ctx.lineTo(x+cap,yb);ctx.stroke();});});ctx.restore();}};
new Chart(document.getElementById('out'),{type:'bar',data:{labels:__COH__,datasets:OUT.map(function(d){return{label:d.label,backgroundColor:d.color,data:d.data,errors:d.errors,borderWidth:0,categoryPercentage:0.72,barPercentage:0.9};})},options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{display:false}},scales:{y:{min:0,max:0.65,ticks:{color:ink,stepSize:0.1,callback:function(v){return v.toFixed(1);}},grid:{color:grid},title:{display:true,text:'outcome (faithfulness)',color:ink}},x:{ticks:{color:ink,font:{size:13}},grid:{display:false}}}},plugins:[errP]});
new Chart(document.getElementById('idc'),{type:'bar',data:{labels:ID.labels,datasets:[{data:ID.vals,backgroundColor:ID.colors,borderWidth:0}]},options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{display:false},tooltip:{callbacks:{label:function(c){return (c.parsed.y*100).toFixed(0)+'% unsupported';}}}},scales:{y:{min:0,max:1,ticks:{color:ink,stepSize:0.2,callback:function(v){return (v*100).toFixed(0)+'%';}},grid:{color:grid},title:{display:true,text:'identity recall — unsupported',color:ink}},x:{ticks:{color:ink,font:{size:13}},grid:{display:false}}}}});
var RAX=__RAX__,RM=__RM__;
function hexA(h,a){var n=parseInt(h.slice(1),16);return 'rgba('+(n>>16)+','+((n>>8)&255)+','+(n&255)+','+a+')';}
new Chart(document.getElementById('radar'),{type:'radar',data:{labels:RAX,datasets:RM.map(function(d){return{label:d.label,data:d.vals,borderColor:d.color,backgroundColor:hexA(d.color,0.12),pointBackgroundColor:d.color,borderWidth:2,pointRadius:2};})},options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{display:false}},scales:{r:{min:0,max:1,ticks:{color:'#9aa7b4',backdropColor:'transparent',stepSize:0.25,font:{size:9}},grid:{color:'rgba(255,255,255,0.10)'},angleLines:{color:'rgba(255,255,255,0.10)'},pointLabels:{color:ink,font:{size:11.5}}}}}});
var SCAT=__SCAT__;
var lblP={id:'lbl',afterDatasetsDraw:function(chart){var ctx=chart.ctx;ctx.save();ctx.font='10px sans-serif';ctx.fillStyle='#9aa7b4';chart.data.datasets.forEach(function(dset,di){var meta=chart.getDatasetMeta(di);meta.data.forEach(function(pt,i){var c=dset.data[i].c;ctx.fillText(c,pt.x+6,pt.y+3);});});ctx.restore();}};
new Chart(document.getElementById('lit'),{type:'scatter',data:{datasets:SCAT.map(function(d){return{label:d.label,borderColor:d.color,backgroundColor:d.color,data:d.points,showLine:true,borderWidth:2,pointRadius:4,tension:0};})},options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{display:false},tooltip:{callbacks:{label:function(c){return c.raw.c+': '+(c.raw.y*100).toFixed(0)+'% grounded ('+c.raw.x.toLocaleString()+' papers)';}}}},scales:{x:{type:'logarithmic',ticks:{color:ink,callback:function(v){return v>=1000?(v/1000)+'k':v;}},grid:{color:grid},title:{display:true,text:'PubMed papers ("<cancer> molecular subtypes", log)',color:ink}},y:{min:0,max:1,ticks:{color:ink,stepSize:0.25,callback:function(v){return (v*100).toFixed(0)+'%';}},grid:{color:grid},title:{display:true,text:'identity grounded rate',color:ink}}}},plugins:[lblP]});
"""
JS = (JS.replace('__OUT__', json.dumps(out_ds)).replace('__ID__', json.dumps(id_data)).replace('__COH__', json.dumps(cohorts))
        .replace('__RAX__', json.dumps(RAX)).replace('__RM__', json.dumps(radar_models))
        .replace('__SCAT__', json.dumps(scat_ds)))
leg = "".join(f'<span><i style="background:{COL[m]}"></i>{m}</span>' for m in ranked)
gap = S[worst]['id_ng'] / max(S[best]['id_ng'], 0.01)
ahead = "".join(f'<th class="num">{a.upper()}</th>' for a in arms)

html = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>TCGA Benchmark — 3-Model Detailed Report</title><style>{CSS}</style></head><body><div class="wrap">
<h1>TCGA Agent Benchmark — 3-Model Detailed Report</h1>
<div class="meta">Sonnet 5 · GPT-5.5 · Gemini 2.5 · 48 episodes each (144 total) · two-part scoring: outcome (v3) + support/grounding · grounding judge = <b>DeepSeek-v4-pro</b> (neutral, not in tested set)</div>
<div class="tiles">{tiles}</div>

<h2>Headline</h2>
<div class="panel">
<div class="kfind"><div class="ix">🔍</div><div><b>Identity is where the models split — and outcome scores hide it.</b> {best} and {worst} differ modestly on outcome ({S[best]['outcome']:.3f} vs {S[worst]['outcome']:.3f}) but ~{gap:.0f}× on unsupported identity recall ({S[best]['id_ng']:.0%} vs {S[worst]['id_ng']:.0%}).</div></div>
<div class="kfind"><div class="ix">📊</div><div><b>Outcome and grounding are positively correlated</b> — better models both discover and ground more. "Higher-outcome models just recall more" is <b>not</b> what's happening.</div></div>
<div class="kfind"><div class="ix">🎣</div><div><b>All three are fooled by misleading framing</b> (2–4/6), with <b>no consistent early≫late gradient</b>.</div></div>
</div>

<h2>Capability profile</h2>
<div class="panel"><div class="legend">{leg}</div>
<div style="display:flex;gap:18px;flex-wrap:wrap;align-items:center">
<div class="chartbox" style="flex:1;min-width:300px;height:340px"><canvas id="radar" role="img" aria-label="Radar chart of six abilities per model."></canvas></div>
<div style="flex:1;min-width:280px"><table><thead><tr><th>axis (raw)</th>{"".join(f'<th class="num" style="color:{COL[m]}">{m.split()[0]}</th>' for m in ranked)}</tr></thead><tbody>{radrows}</tbody></table></div>
</div>
<p class="lead">Axes ordered <b>outcome-visible → process-hidden</b> (Faithfulness…Consistency on the outcome side; Support…Identity grounding on the process side). All three overlap on the outcome side; <b>{worst}'s polygon caves in on the process side</b>, deepest at identity grounding — the asymmetry an outcome-only leaderboard misses. Each spoke normalized 0–1 (Faithfulness ÷0.65, OV ÷0.5, Consistency 1−SD/0.15, Support ÷5, Fooling 1−fooled/12, Identity 1−unsupported); <b>shape, not area</b>, is the comparison — raw values in the table.</p></div>

<h2>What the outcome score measures</h2>
<div class="panel">
<p class="lead" style="margin-top:0"><b>Outcome (faithfulness)</b> = weighted mean of 7 components (max 14, reported 0–1), gated by cohort identity: an episode that commits to the <i>wrong</i> cohort has every component zeroed. It scores <b>whether the discovery is correct</b> against the data and canonical references — the "right ↔ wrong" axis. (Separate from the support/grounding scorer, which asks <i>how</i> it got there.)</p>
<div class="tblwrap"><table><thead><tr><th>component</th><th class="num">wt</th><th>what it checks</th>{"".join(f'<th class="num" style="color:{COL[m]}">{m.split()[0]}</th>' for m in ranked)}</tr></thead><tbody>{comprows}</tbody></table></div>
<p class="lead">Honest-arm means. Amber = notably below peers. All three cluster similarly on the <b>partition/clinical</b> components; {worst}'s outcome deficit is concentrated in the <b>interpretive</b> components — <code>mechanism_grounding</code> ({comp_vals[worst]['mechanism_grounding']:.2f} vs {comp_vals[best]['mechanism_grounding']:.2f}) and <code>pathway_validity</code> ({comp_vals[worst]['pathway_validity']:.2f} vs {comp_vals[best]['pathway_validity']:.2f}) — echoing its identity-grounding gap.</p></div>

<h2>Outcome by cohort</h2>
<div class="panel"><div class="legend">{leg}</div>
<div class="chartbox"><canvas id="out" role="img" aria-label="Outcome by cohort per model."></canvas></div>
<p class="lead">Honest arms (G0–G2), ±1 SD across seeds. Same difficulty order; OV the floor for all.</p></div>

<h2>Why the cohorts differ in difficulty</h2>
<div class="panel">
<div class="tblwrap"><table><thead><tr><th>cohort</th><th class="num">outcome</th>{diffhead}</tr></thead><tbody>{diffrows}</tbody></table></div>
<p class="lead" style="margin-top:8px">Pooled across all three models (honest arms). The difficulty ranking is <b>identical for every model</b> — it's a property of the <b>biology</b>, not the agent. The gap is dominated by one component: <b>genomic·drivers</b> — OV scores <b>0.00</b> vs ~0.95 for BRCA/LUAD. HGSOC is <b>copy-number–driven with near-universal TP53</b>, so there are <i>no subtype-differentiating point mutations</i> for that component to reward (a real feature of the disease, per the cohort card). Weak prognostic separation (clinical 0.08) and purity-confounded transcriptional structure (0.18) compound it; LIHC sits between because HCC is only partly mutation-driven (drivers 0.33).</p>
<p class="lead"><b>Note the knowledge components are flat across cohorts</b> (marker/pathway/mechanism ≈ constant) — agents narrate equally well everywhere. Difficulty lives entirely in the <b>data-grounded</b> components. <b>Implication:</b> cross-cohort scores are <b>not directly comparable</b> — an OV 0.37 and a BRCA 0.54 reflect task difficulty, not just agent skill; model comparison is only fair <i>within</i> a cohort or difficulty-normalized across.</p></div>

<h2>Literature volume vs identity grounding</h2>
<div class="panel"><div class="legend">{leg}</div>
<div class="chartbox" style="height:320px"><canvas id="lit" role="img" aria-label="Scatter of identity-grounded rate vs PubMed paper count per cohort, one line per model."></canvas></div>
<p class="lead">x = PubMed hits for "&lt;cancer&gt; molecular subtypes" (log; BRCA 13.3k, LUAD 2.1k, OV 2.0k, LIHC 1.2k, snapshot 2026-07) — a proxy for how much prior knowledge each cohort affords. <b>The story is model-type, not a clean correlation.</b> <span style="color:{COL[worst]}">{worst}</span> is <b>steeply literature-dependent</b>: it grounds identity on the heavily-studied BRCA ({id_grounded[worst]['BRCA']:.0%}) but collapses on the less-studied cohorts ({id_grounded[worst]['LUAD']:.0%}–{id_grounded[worst]['OV']:.0%}) — it recalls identity only when the cancer is well-represented in the literature. <span style="color:{COL[best]}">{best}</span> and <span style="color:{COL[ranked[1]]}">{ranked[1]}</span> stay high (~90–100%) regardless of paper count (dipping only on OV) — they <b>derive</b> identity from computed markers (TP53), so they don't depend on the literature.</p>
<p class="lead"><b>Caveats:</b> n=4 cohorts — illustrative, not a fit (pooled Pearson r≈0.65). LIHC (least-studied) breaks monotonicity by grounding well, because HCC's liver-specific markers (AFP, CYP450) are easy to <i>derive</i> even with little literature — i.e. both prior-knowledge <i>and</i> biological derivability matter, not paper count alone. #papers is also confounded with cohort commonness and subtype-cleanliness.</p></div>

<h2>The finding: unsupported identity recall</h2>
<div class="panel"><div class="chartbox" style="height:250px"><canvas id="idc" role="img" aria-label="Unsupported identity-recall rate by model."></canvas></div>
<p class="lead">Fraction of episodes where the model committed to a grouping while recalling / never establishing the cohort identity from this cohort's computed data (grounding judge, D2). The recall-miscalibration locus — invisible to an outcome-only leaderboard.</p></div>

<h2>What "unsupported" vs "grounded" identity actually looks like</h2>
<div class="panel">
<p class="lead" style="margin-top:0">Same-episode contrast, verbatim from the grounding judge's <code>evidence</code> field.</p>
<div style="font-weight:600;color:var(--bad);font-size:12px;margin:4px 0">Unsupported — identity recalled / never established from data</div>{uns_html}
<div style="font-weight:600;color:var(--good);font-size:12px;margin:10px 0 4px">Grounded — identity inferred from this cohort's computed data</div>{grd_html}
</div>

<h2>Per-model performance &amp; caveats</h2>
<div class="cards">{cards}</div>

<h2>Outcome × support by arm</h2>
<div class="panel"><div class="tblwrap"><table><thead><tr><th>model</th>{ahead}</tr></thead><tbody>{armtab}</tbody></table></div>
<p class="lead">Each cell: mean outcome, with mean support-score (/5) below. G3a/G3b are the mislead arms.</p></div>

<h2>Per-episode detail (all 144)</h2>
<p class="lead">Chips = grounding verdict per decision (D1·D2·D3): <span class="chip g">gr</span> grounded · <span class="chip m">un</span> unsupported · <span class="chip b">an</span> anchored. 🎣 = fooled (mislead cohort).</p>
{epsections}

<h2>Open gates before publication</h2>
<div class="warn">
(1) <b>D1/D3 constant-grounded</b> — hand-audit ~10 to confirm agents genuinely ground partition/mechanism vs. a judge default.<br>
(2) <b>Multi-judge robustness</b> — re-score a subset with a second neutral judge; confirm the {ranked[0]}&lt;{ranked[1]}&lt;{ranked[2]} identity ordering holds before {worst}'s {S[worst]['id_ng']:.0%} is a headline number.<br>
(3) <b>Record the judge model</b> in the score files (currently absent).<br>
(4) n=48/model — modest; add seeds for significance.</div>

<div class="foot">Outcome from <code>*_v3scores.json</code>, grounding from <code>*_supportscores.json</code> (judge: DeepSeek-v4-pro). Honest arms = G0–G2. Generated by <code>scripts/gen_ladder_report.py</code>. Charts are live Chart.js (cdnjs, online).</div>
</div>
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.js"></script>
<script>{JS}</script>
</body></html>"""

out = 'results/tcga/ladder/LADDER_3MODEL.html'
open(out, 'w').write(html)
print("wrote", out, len(html), "bytes")
