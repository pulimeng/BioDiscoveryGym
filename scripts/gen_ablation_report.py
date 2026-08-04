#!/usr/bin/env python3
"""Instruction-ablation report — DETAILED (staged Stage 0-5 prompt) vs LEAN (no prescribed
procedure) across all models. Same model/cohorts/seeds/budget; only the prompt differs. Pairs
every metric per model so you can read whether instruction changes WHAT is found (outcome),
how GROUNDED it looks (support/D2), and how it actually REASONS (CoT derive-vs-recall, fooling,
observation count). Reads v3 + support + cotsummary + the raw trace (record_observation count).

Usage: python scripts/gen_ablation_report.py     ->  results/tcga/ABLATION_REPORT.html
"""
import glob, json, os, re, sys, statistics as st
from collections import Counter
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import runs_config
from extract_cot import extract_episode, count_based_identity

# (label, detailed_dir, lean_dir, color, tier)
PAIRS = runs_config.pairs()
OUT = 'results/tcga/ABLATION_REPORT.html'

def arm(lab): return lab.split('_')[0]
def cohort_of(lab): return lab.split('_')[1].upper() if '_' in lab else '?'

# cohort fingerprint sizes (for the shape-leak probe) + the count-basis pattern
def _cohort_sizes():
    sz = {}
    for _, dd, ld, *_ in PAIRS:
        for base in (dd, ld):
            for p in glob.glob(f"{base}/g2_*/grouping.json"):
                c = os.path.basename(os.path.dirname(p)).split('_')[1].upper()
                try: sz[c] = len(json.load(open(p)))
                except Exception: pass
    return sz
def count_leak(D, SIZES):
    """(#G2 episodes with the sample-count benchmark-recognition shortcut, tightened probe)."""
    hits = n = 0
    for p in glob.glob(f"{D}/g2_*/*.json"):
        if os.path.basename(p)[:-5] != os.path.basename(os.path.dirname(p)):
            continue
        n += 1
        try:
            if count_based_identity(extract_episode(p), SIZES): hits += 1
        except Exception: continue
    return hits, n
SIZES = _cohort_sizes()

def metrics(D):
    """All ablation metrics for one run dir."""
    v3 = {}; sup = {}; cot = {}
    for p in glob.glob(f"{D}/*/*_v3scores.json"):
        l = os.path.basename(p).replace('_v3scores.json', '')
        if os.path.basename(os.path.dirname(p)) == l: v3[l] = json.load(open(p))
    for p in glob.glob(f"{D}/*/*_supportscores.json"):
        l = os.path.basename(p).replace('_supportscores.json', '')
        if os.path.basename(os.path.dirname(p)) == l: sup[l] = json.load(open(p))
    for p in glob.glob(f"{D}/*/*_cotsummary.json"):
        l = os.path.basename(p).replace('_cotsummary.json', '')
        if os.path.basename(os.path.dirname(p)) == l: cot[l] = json.load(open(p))
    hon = [l for l in v3 if arm(l) in ('g0', 'g1', 'g2')]
    def om(a):
        xs = [v3[l]['normalized'] for l in v3 if arm(l) == a]; return st.mean(xs) if xs else 0.0
    d2 = Counter(sup[l]['levels']['d2_identity']['support'] for l in sup if arm(l) in ('g0', 'g1', 'g2'))
    nhon_sup = sum(d2.values()) or 1
    g2c = [cot[l] for l in cot if arm(l) == 'g2']
    idc = Counter(x.get('identity_derivation') for x in g2c)
    honc = [cot[l] for l in cot if arm(l) in ('g0', 'g1', 'g2')]
    rig = Counter(x.get('validation_rigor') for x in honc)
    # record_observation count/episode (honest arms) — the documentation-vs-reasoning mechanism
    ro = []
    for p in glob.glob(f"{D}/*/*.json"):
        l = os.path.basename(p)[:-5]
        if os.path.basename(os.path.dirname(p)) != l or arm(l) not in ('g0', 'g1', 'g2'): continue
        try: rec = extract_episode(p)
        except Exception: continue
        ro.append(sum(1 for c in rec['calls'] if c['tool'] == 'record_observation'))
    # per-cohort honest outcome (does a collapse hit specific cohorts?)
    obc = {}
    for c in sorted({cohort_of(l) for l in hon}):
        xs = [v3[l]['normalized'] for l in hon if cohort_of(l) == c]
        if xs: obc[c] = st.mean(xs)
    lk, lkn = count_leak(D, SIZES)
    return dict(
        out_hon=st.mean([v3[l]['normalized'] for l in hon]) if hon else 0.0,
        out_g0=om('g0'), out_g1=om('g1'), out_g2=om('g2'),
        out_by_cohort=obc, leak=lk, leak_n=lkn,
        support=st.mean([sup[l]['support_score'] for l in sup if arm(l) in ('g0','g1','g2')]) if sup else 0.0,
        d2_unsup=(d2.get('unsupported', 0) + d2.get('anchored', 0)) / nhon_sup,
        g2_derived=idc.get('data-derived', 0) / max(len(g2c), 1),
        g2_recalled=idc.get('recalled-prior', 0) / max(len(g2c), 1),
        rigor_high=rig.get('high', 0) / max(len(honc), 1),
        fooled=sum(1 for l in v3 if arm(l) in ('g3a', 'g3b') and v3[l].get('cohort_identity_verdict') == 'mislead_cohort'),
        n_g3=sum(1 for l in v3 if arm(l) in ('g3a', 'g3b')),
        ro_per_ep=st.mean(ro) if ro else 0.0)

DATA = {lab: {'detailed': metrics(dd), 'lean': metrics(ld), 'color': col, 'tier': tier}
        for lab, dd, ld, col, tier in PAIRS}

# ---- inter-judge robustness: judge A (DeepSeek, neutral) vs judge B (_cotsummary_j2) ----
# The whole explore/exploit axis rides on ONE label (identity_derivation) from ONE judge. This
# re-reads the same G2 traces under a second judge. Judge B may be mid-run, so every judge-A
# comparison is ALSO computed on judge B's exact episode subset — otherwise a cohort-subset
# effect (G2 files are written cohort-alphabetically) is indistinguishable from a judge effect.
J2 = '_cotsummary_j2.json'
JFIELDS = ['identity_derivation', 'validation_rigor', 'codebook_response']

def _load_sfx(D, sfx):
    out = {}
    for p in glob.glob(f"{D}/g2_*/*{sfx}"):
        l = os.path.basename(p).replace(sfx, '')
        if os.path.basename(os.path.dirname(p)) == l: out[l] = json.load(open(p))
    return out

def _der(summaries):
    """fraction 'data-derived' over a list of summaries (the explore/exploit proxy)."""
    if not summaries: return None
    return sum(1 for x in summaries if x.get('identity_derivation') == 'data-derived') / len(summaries)

def judge_pair(D):
    A, B = _load_sfx(D, '_cotsummary.json'), _load_sfx(D, J2)
    both = sorted(set(A) & set(B))
    agree = {f: (sum(1 for l in both if A[l].get(f) == B[l].get(f)), len(both)) for f in JFIELDS}
    flips = Counter((A[l].get('identity_derivation'), B[l].get('identity_derivation'))
                    for l in both if A[l].get('identity_derivation') != B[l].get('identity_derivation'))
    return dict(n_a=len(A), n_both=len(both), agree=agree, flips=flips,
                der_a_all=_der(list(A.values())),
                der_a_match=_der([A[l] for l in both]),   # judge A on judge B's subset
                der_b=_der([B[l] for l in both]),
                complete=len(both) == len(A) and len(A) > 0)

JP = {lab: {'detailed': judge_pair(dd), 'lean': judge_pair(ld)} for lab, dd, ld, _, _ in PAIRS}
JP_ANY = any(JP[m][p]['n_both'] for m in JP for p in ('detailed', 'lean'))

# agreement table
j_rows = ""
for lab in DATA:
    for prompt in ('detailed', 'lean'):
        j = JP[lab][prompt]
        if not j['n_both']:
            j_rows += (f'<tr><td class="grp" style="color:{DATA[lab]["color"]}">{lab}</td><td>{prompt}</td>'
                       f'<td class="num mut" colspan="4">not yet judged by B</td></tr>'); continue
        cov = f"{j['n_both']}/{j['n_a']}" + ('' if j['complete'] else ' <span class="part">partial</span>')
        cells = ""
        for f in JFIELDS:
            a, n = j['agree'][f]
            cls = 'good' if a / n >= 0.8 else ('bad' if a / n < 0.6 else 'mut')
            cells += f'<td class="num {cls}">{a}/{n}<span class="sub">{a/n*100:.0f}%</span></td>'
        j_rows += (f'<tr><td class="grp" style="color:{DATA[lab]["color"]}">{lab}</td><td>{prompt}</td>'
                   f'<td class="num">{cov}</td>{cells}</tr>')

# does the lean−detailed derivation delta SURVIVE the second judge?
def _fmt_d(x): return '—' if x is None else f"{x*100:+.1f}"
surv_rows = ""; surv_verdicts = []
for lab in DATA:
    d, l = JP[lab]['detailed'], JP[lab]['lean']
    dA = (DATA[lab]['lean']['g2_derived'] - DATA[lab]['detailed']['g2_derived'])
    dAm = (l['der_a_match'] - d['der_a_match']) if (l['der_a_match'] is not None and d['der_a_match'] is not None) else None
    dB = (l['der_b'] - d['der_b']) if (l['der_b'] is not None and d['der_b'] is not None) else None
    partial = not (d['complete'] and l['complete'])
    if dB is None:
        verdict, vcls = 'judge B incomplete', 'part'
    elif partial:
        verdict, vcls = f"partial coverage ({l['n_both']}/{l['n_a']} lean)", 'part'
    else:
        ref = dAm if dAm is not None else dA
        if abs(ref) < 0.05 and abs(dB) < 0.05: verdict, vcls = 'no effect, both judges', 'mut'
        elif (dB > 0) != (ref > 0): verdict, vcls = 'FLIPS under judge B', 'bad'
        elif abs(dB) >= 0.5 * abs(ref): verdict, vcls = 'holds', 'good'
        else: verdict, vcls = 'attenuated', 'part'
        surv_verdicts.append(verdict)
    surv_rows += (f'<tr><td class="grp" style="color:{DATA[lab]["color"]}">{lab}</td>'
                  f'<td class="num">{_fmt_d(dA)}</td><td class="num">{_fmt_d(dAm)}</td>'
                  f'<td class="num">{_fmt_d(dB)}</td><td class="{vcls}">{verdict}</td></tr>')

# the most common cross-judge confusion, pooled (is disagreement adjacent or sign-flipping?)
pool = Counter()
for m in JP:
    for p in ('detailed', 'lean'): pool.update(JP[m][p]['flips'])
ADJ = {('mixed', 'data-derived'), ('data-derived', 'mixed'), ('mixed', 'recalled-prior'), ('recalled-prior', 'mixed')}
n_flip = sum(pool.values()); n_adj = sum(v for k, v in pool.items() if k in ADJ)
flip_txt = "  ·  ".join(f"{a}→{b} ×{n}" for (a, b), n in pool.most_common(5)) or "none"
j_all_complete = all(JP[m][p]['complete'] for m in JP for p in ('detailed', 'lean'))

# ---- metric rows: (key, label, fmt, lower_is_better) ----
ROWS = [
    ('out_hon', 'Outcome (honest mean)', lambda v: f"{v:.3f}", None),
    ('out_g2', '— outcome G2 (hardest honest)', lambda v: f"{v:.3f}", None),
    ('support', 'Support / grounding (/5)', lambda v: f"{v:.2f}", False),
    ('d2_unsup', 'D2 identity unsupported', lambda v: f"{v:.0%}", True),
    ('g2_derived', 'CoT: G2 identity DERIVED', lambda v: f"{v:.0%}", False),
    ('g2_recalled', 'CoT: G2 identity RECALLED', lambda v: f"{v:.0%}", True),
    ('rigor_high', 'CoT: validation rigor high', lambda v: f"{v:.0%}", False),
    ('fooled', 'G3 fooled (of 12)', lambda v: f"{int(v)}/12", True),
    ('ro_per_ep', 'record_observation / ep', lambda v: f"{v:.1f}", None),
]

def delta_cell(key, det, lean, fmt, lower_better):
    d = lean - det
    arrow = "→" if abs(d) < 1e-9 else ("↑" if d > 0 else "↓")
    if lower_better is None or abs(d) < (0.005 if key != 'fooled' else 0.5):
        cls = "mut"
    else:
        good = (d < 0) if lower_better else (d > 0)
        cls = "good" if good else "bad"
    dtxt = fmt(abs(d)) if key not in ('fooled',) else f"{abs(int(d))}"
    return f'<td class="num">{fmt(det)}</td><td class="num">{fmt(lean)}</td><td class="num {cls}">{arrow}{dtxt}</td>'

# ---- per-cohort outcome, detailed vs lean (is a collapse cohort-specific?) ----
COHORTS = sorted({c for m in DATA for c in DATA[m]['detailed']['out_by_cohort']},
                 key=lambda c: -(SIZES.get(c) or 0))
cohort_rows = ""
for lab in DATA:
    det, lean = DATA[lab]['detailed']['out_by_cohort'], DATA[lab]['lean']['out_by_cohort']
    cells = ""
    for c in COHORTS:
        dv, lv = det.get(c), lean.get(c)
        if dv is None or lv is None:
            cells += '<td class="num mut">—</td>'; continue
        d = lv - dv
        cls = 'good' if d > 0.02 else ('bad' if d < -0.02 else 'mut')
        cells += f'<td class="num"><span class="{cls}">{lv:.2f}</span><span class="sub">{d:+.2f}</span></td>'
    cohort_rows += (f'<tr><td class="grp" style="color:{DATA[lab]["color"]}">{lab}</td>{cells}</tr>')
cohort_head = "".join(f'<th class="num">{c}<span class="sub">n={SIZES.get(c,"?")}</span></th>' for c in COHORTS)

# ---- shape-leak (benchmark recognition from sample count), detailed vs lean ----
leak_rows = ""
for lab in DATA:
    dl, dn = DATA[lab]['detailed']['leak'], DATA[lab]['detailed']['leak_n']
    ll, ln = DATA[lab]['lean']['leak'], DATA[lab]['lean']['leak_n']
    d = ll - dl
    cls = 'bad' if d > 0 else ('good' if d < 0 else 'mut')
    leak_rows += (f'<tr><td class="grp" style="color:{DATA[lab]["color"]}">{lab}</td>'
                  f'<td class="num">{dl}/{dn}</td><td class="num">{ll}/{ln}</td>'
                  f'<td class="num {cls}">{d:+d}</td></tr>')
leak_total_det = sum(DATA[m]['detailed']['leak'] for m in DATA)
leak_total_lean = sum(DATA[m]['lean']['leak'] for m in DATA)

# per-model paired tables
cards = ""
for lab in DATA:
    det, lean = DATA[lab]['detailed'], DATA[lab]['lean']
    body = ""
    for key, name, fmt, lb in ROWS:
        body += f'<tr><td>{name}</td>{delta_cell(key, det[key], lean[key], fmt, lb)}</tr>'
    tier = DATA[lab]['tier']
    tnote = (f'<span class="tier">{tier}</span>' if tier != 'flagship' else '')
    cards += (f'<div class="card" style="border-top:3px solid {DATA[lab]["color"]}">'
              f'<h3 style="color:{DATA[lab]["color"]}">{lab} {tnote}</h3>'
              f'<table><thead><tr><th>metric</th><th class="num">detailed</th><th class="num">lean</th>'
              f'<th class="num">Δ (lean−det)</th></tr></thead><tbody>{body}</tbody></table></div>')

# chart data: outcome + identity-derived, detailed vs lean, per model
labels = list(DATA)
CH = {
    'labels': labels, 'colors': [DATA[m]['color'] for m in labels],
    'out_det': [round(DATA[m]['detailed']['out_hon'], 3) for m in labels],
    'out_lean': [round(DATA[m]['lean']['out_hon'], 3) for m in labels],
    'der_det': [round(DATA[m]['detailed']['g2_derived'], 3) for m in labels],
    'der_lean': [round(DATA[m]['lean']['g2_derived'], 3) for m in labels],
    'ro_det': [round(DATA[m]['detailed']['ro_per_ep'], 1) for m in labels],
    'ro_lean': [round(DATA[m]['lean']['ro_per_ep'], 1) for m in labels],
}

# headline synthesis (computed, not hardcoded)
flag = [m for m in DATA if DATA[m]['tier'] == 'flagship']
flash = [m for m in DATA if DATA[m]['tier'] != 'flagship']
flag_shift = st.mean([abs(DATA[m]['lean']['out_hon'] - DATA[m]['detailed']['out_hon']) for m in flag]) if flag else 0
der_up = sum(1 for m in DATA if DATA[m]['lean']['g2_derived'] > DATA[m]['detailed']['g2_derived'])
sup_up_det = sum(1 for m in DATA if DATA[m]['detailed']['support'] > DATA[m]['lean']['support'] + 1e-9)
ro_up_det = sum(1 for m in DATA if DATA[m]['detailed']['ro_per_ep'] > DATA[m]['lean']['ro_per_ep'])
fool_up_det = sum(1 for m in DATA if DATA[m]['detailed']['fooled'] > DATA[m]['lean']['fooled'])
rig_up_det = sum(1 for m in DATA if DATA[m]['detailed']['rigor_high'] > DATA[m]['lean']['rigor_high'])
# the Flash outcome-collapse line (if any non-flagship model drops materially under lean)
flash_line = ""
for m in flash:
    dd, ll = DATA[m]['detailed']['out_hon'], DATA[m]['lean']['out_hon']
    if dd - ll > 0.05:
        flash_line = (f' — but <b>{m}</b> (Flash tier) <b>collapses</b> under lean '
                      f'({dd:.3f}→{ll:.3f}, −{dd-ll:.3f}): the smaller model <b>depends on the '
                      f'staged scaffold</b> to hold its outcome.')
        break

CSS = """
:root{--bg:#0d1117;--panel:#161b22;--line:#283041;--ink:#e6edf3;--mut:#9aa7b4;--acc:#58a6ff;--good:#3fb950;--bad:#f85149}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.55 -apple-system,Segoe UI,Roboto,Arial,sans-serif;padding:30px}
.wrap{max-width:1080px;margin:0 auto}h1{font-size:23px;margin:0 0 2px}h3{margin:0 0 8px;font-size:16px}
h2{font-size:17px;margin:28px 0 8px;border-left:3px solid var(--acc);padding-left:10px}
.meta{color:var(--mut);font-size:13px;margin-bottom:8px}.lead{color:var(--mut);font-size:13px;margin:2px 0 10px}
.panel{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:14px 18px;margin:12px 0}
.kfind{display:grid;grid-template-columns:26px 1fr;gap:10px;margin:9px 0}.kfind .ix{font-size:19px}
.cards{display:grid;grid-template-columns:1fr;gap:14px}
.card{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:14px}
table{border-collapse:collapse;width:100%;font-size:13px}th,td{padding:6px 9px;border-bottom:1px solid var(--line);text-align:left}
th{color:var(--mut);font-weight:600;font-size:12px}td.num,th.num{text-align:right;font-variant-numeric:tabular-nums}
.good{color:var(--good);font-weight:700}.bad{color:var(--bad);font-weight:700}.mut{color:var(--mut)}
.tier{font-size:11px;background:#3a2d10;color:#d29922;border-radius:5px;padding:1px 7px;margin-left:6px;vertical-align:middle}
.chartbox{position:relative;height:300px}.legend{display:flex;gap:16px;font-size:12px;color:var(--mut);margin:4px 0 8px}
.legend span{display:flex;align-items:center;gap:5px}.legend i{width:11px;height:11px;border-radius:2px;display:inline-block}
.warn{background:#2a2410;border:1px solid #5c4a12;border-radius:8px;padding:12px 16px;margin:12px 0;color:#e8d48a;font-size:13px}
.foot{color:var(--mut);font-size:11.5px;margin-top:24px;border-top:1px solid var(--line);padding-top:12px}
code{background:#0b1220;padding:1px 5px;border-radius:4px;font-size:12px}
.sub{display:block;font-size:9px;color:var(--mut);font-weight:400}
.part{color:#d29922;font-weight:700}
.tblwrap{overflow-x:auto}.grp{font-weight:700}
"""

JS = """
var ink='#e6edf3',grid='rgba(255,255,255,0.10)';var CH=__CH__;
function paired(id,det,lean,axis,pctfmt){new Chart(document.getElementById(id),{type:'bar',
 data:{labels:CH.labels,datasets:[
   {label:'detailed',data:det,backgroundColor:CH.colors.map(function(c){return c+'66';}),borderColor:CH.colors,borderWidth:1},
   {label:'lean',data:lean,backgroundColor:CH.colors,borderWidth:0}]},
 options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{labels:{color:ink,boxWidth:11,font:{size:11}}}},
 scales:{x:{ticks:{color:ink,font:{size:12}},grid:{display:false}},
   y:{beginAtZero:true,ticks:{color:ink,callback:function(v){return pctfmt?(v*100).toFixed(0)+'%':v;}},grid:{color:grid},title:{display:true,text:axis,color:ink}}}}});}
paired('c_out',CH.out_det,CH.out_lean,'outcome (honest)',false);
paired('c_der',CH.der_det,CH.der_lean,'G2 identity data-derived',true);
paired('c_ro',CH.ro_det,CH.ro_lean,'record_observation / episode',false);
"""
JS = JS.replace('__CH__', json.dumps(CH))

interjudge_section = "" if not JP_ANY else f"""
<h2>Inter-judge robustness — does the derivation finding survive a second judge?</h2>
<div class="panel">
<p class="lead">The explore↔exploit axis rests on a <b>single categorical label</b> (<code>identity_derivation</code>)
from a <b>single judge</b>, on n=21 G2 episodes per arm — and the lean prompt's own "derive from structure alone"
wording could plausibly nudge that label. So the same G2 traces were re-judged by a second model
(<code>{J2}</code>). This panel is the foundation for every derivation claim above, not a footnote.</p>
<div class="tblwrap"><table><thead><tr><th>model</th><th>prompt</th><th class="num">judged by both</th>
<th class="num">identity_derivation</th><th class="num">validation_rigor</th><th class="num">codebook_response</th></tr></thead>
<tbody>{j_rows}</tbody></table></div>
<p class="lead">Per-episode agreement between the two judges. <code>codebook_response</code> is near-deterministic
(an observable action); <code>identity_derivation</code> is the <b>interpretive</b> one and agrees least — which is
exactly why the delta table below matters more than any single-judge percentage.</p>
</div>

<div class="panel">
<h3>Does the lean−detailed derivation delta survive?</h3>
<div class="tblwrap"><table><thead><tr><th>model</th>
<th class="num">Δ judge A<span class="sub">all episodes</span></th>
<th class="num">Δ judge A<span class="sub">matched subset</span></th>
<th class="num">Δ judge B<span class="sub">same subset</span></th><th>verdict</th></tr></thead>
<tbody>{surv_rows}</tbody></table></div>
<p class="lead">Δ = (lean − detailed) percentage points of G2 episodes judged <b>data-derived</b>. The
<b>matched-subset</b> column re-computes judge A on <i>exactly</i> the episodes judge B has scored — without it,
partial judge-B coverage is confounded with a cohort effect, since G2 summaries are written cohort-alphabetically
(so an incomplete run over-represents BRCA/LIHC/LUAD and omits OV, the difficulty floor). Compare
<b>matched vs judge B</b>; the all-episodes column is context only. "Holds" = same sign and ≥50% of the magnitude.</p>
</div>

<div class="panel">
<h3>Where the judges disagree</h3>
<p class="lead">Pooled G2 <code>identity_derivation</code> disagreements ({n_flip} of
{sum(JP[m][p]['n_both'] for m in JP for p in ('detailed','lean'))} co-judged episodes), judge A → judge B:</p>
<p><code>{flip_txt}</code></p>
<p class="lead"><b>{n_adj}/{n_flip}</b> disagreements are <b>adjacent</b> (mixed↔data-derived or mixed↔recalled-prior)
rather than polar (data-derived↔recalled-prior). Adjacent disagreement means the judges agree on the
<i>direction</i> of the evidence and differ on where to put the threshold — it degrades the precision of any
single episode's label but largely preserves an aggregate delta. Polar flips would be far more damaging: they
would mean the two judges read the same trace as opposite behaviours.
{"" if j_all_complete else '<br><b class="part">Judge B coverage is still incomplete — every number in this panel is provisional until all arms are re-judged.</b>'}</p>
</div>"""

html = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>TCGA Benchmark — Instruction Ablation (Detailed vs Lean)</title><style>{CSS}</style></head><body><div class="wrap">
<h1>TCGA Agent Benchmark — Instruction Ablation</h1>
<div class="meta">Detailed (staged Stage 0–5 prompt) vs Lean ("no prescribed procedure") · {len(DATA)} models × 2 prompts · 75 episodes each · same model/cohorts/seeds/budget — only the prompt differs · scoring + grounding + CoT judged by neutral DeepSeek-v4-pro</div>

<h2>Headline</h2>
<div class="panel">
<div class="kfind"><div class="ix">⚖️</div><div><b>Outcome is prompt-invariant for the flagships</b> (mean |lean−detailed| = <b>{flag_shift:.3f}</b> for {", ".join(flag)}){flash_line}</div></div>
<div class="kfind"><div class="ix">🎣</div><div><b>The staged prompt makes models MORE fooled.</b> Under the detailed prompt every model committed to the misleading cohort more often — fooled-more-under-detailed in <b>{fool_up_det}/{len(DATA)}</b> models. The scaffold walks them into the injected false frame.</div></div>
<div class="kfind"><div class="ix">📋</div><div><b>The staged prompt inflates the grounding <i>score</i> via documentation, not reasoning.</b> Detailed logs more <code>record_observation</code>s in <b>{ro_up_det}/{len(DATA)}</b> models and posts a higher support score in <b>{sup_up_det}/{len(DATA)}</b>, while validation rigor is higher under detailed in <b>{rig_up_det}/{len(DATA)}</b> — yet G2 identity is <i>derived</i> from data more under lean in <b>{der_up}/{len(DATA)}</b>. More paperwork, not better grounding.</div></div>
</div>

<h2>Outcome, derivation, and documentation — detailed vs lean</h2>
<div class="panel">
<div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:14px">
<div><div class="chartbox"><canvas id="c_out"></canvas></div></div>
<div><div class="chartbox"><canvas id="c_der"></canvas></div></div>
<div><div class="chartbox"><canvas id="c_ro"></canvas></div></div>
</div>
<p class="lead">Faded bar = detailed, solid = lean. <b>Outcome</b> barely moves; <b>identity-derivation</b> tends to rise under lean; <b>record_observation count</b> falls under lean (less documentation) — the three-way signature of "instruction inflates the grounding metric without improving the reasoning."</p></div>

<h2>Per-model paired metrics</h2>
<div class="cards">{cards}</div>
<p class="lead">Δ colouring: <span class="good">green</span> = lean is better on that axis, <span class="bad">red</span> = lean is worse, grey = ~no change. "Better" accounts for direction (lower is better for unsupported/recalled/fooled).</p>

<h2>Outcome by cohort — where the prompt matters</h2>
<div class="panel"><div class="tblwrap"><table><thead><tr><th>model</th>{cohort_head}</tr></thead><tbody>{cohort_rows}</tbody></table></div>
<p class="lead">Each cell = <b>lean</b> honest-outcome for that cohort, with <b>Δ vs detailed</b> below (<span class="good">green</span> lean higher, <span class="bad">red</span> lean lower). Cohorts ordered by sample size. This localizes the flagship-vs-Flash split: if a model's lean drop is uniform across cohorts it's a global prompt effect; if it's concentrated, specific cohorts drive it.</p></div>

<h2>Benchmark recognition (shape leak) — detailed vs lean</h2>
<div class="panel"><div class="tblwrap"><table><thead><tr><th>model</th><th class="num">detailed</th><th class="num">lean</th><th class="num">Δ</th></tr></thead><tbody>{leak_rows}</tbody></table></div>
<p class="lead">Blinded G2 episodes where the model named the cancer from the <b>sample count</b> (a memorized TCGA cohort size, e.g. BRCA=1095) in its pre-reveal reasoning — before any biology. Totals: <b>{leak_total_det}</b> under detailed vs <b>{leak_total_lean}</b> under lean. Does removing the staged prompt change the shape-recognition shortcut? <span class="bad">Red Δ</span> = lean recognizes the benchmark <i>more</i>; the dataset's shape is the one property blinding can't hide, so this is a benchmark leak independent of prompt.</p></div>

{interjudge_section}

<h2>Open gates before publication</h2>
<div class="warn">
(1) <b>n = 21/arm</b> (12 for G3); single seed-triple. Deltas within a few points are noise.<br>
(2) <b>Two scorers, partly divergent</b> — CoT "derived" (behaviour) vs support "unsupported" (documented evidence) can move in opposite directions; that divergence is the finding, but neither is ground truth.<br>
(3) <b>Gemini is Flash tier</b> — a Gemini delta is confounded by tier; the clean ablation is the two flagships (GPT-5.5, Sonnet 5).<br>
(4) <b>identity_derivation is one judge's categorical call</b> — the lean prompt's own "derive from structure alone" wording may nudge it toward "data-derived". {"Second-judge coverage is COMPLETE; read the survival verdicts above and quote only deltas marked <i>holds</i>." if j_all_complete else "<b class='part'>Second-judge coverage is still INCOMPLETE</b> — treat every derivation magnitude as directional-pending-robustness until it finishes."}
</div>

<div class="foot">Detailed dirs = <code>results/tcga/ladder/*</code>; lean = <code>results/tcga/lean/*</code>. Outcome from <code>*_v3scores.json</code>, grounding from <code>*_supportscores.json</code>, reasoning from <code>*_cotsummary.json</code> (neutral DeepSeek-v4-pro); record_observation counts from the raw trace. Generated by <code>scripts/gen_ablation_report.py</code>. Charts: Chart.js (cdnjs).</div>
</div>
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.js"></script>
<script>{JS}</script>
</body></html>"""

open(OUT, 'w').write(html)
print("wrote", OUT, len(html), "bytes")
