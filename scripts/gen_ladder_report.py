#!/usr/bin/env python3
"""Detailed 3-model report — outcome (v3) + support/grounding, with per-model cards,
per-episode tables, and the judge's evidence quotes. Judge: DeepSeek-v4-pro (neutral)."""
import argparse, glob, math, os, json, re, sys, html as H, statistics as st
from collections import Counter
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from extract_cot import extract_episode, DISEASE_PAT   # deterministic, no LLM — for the sample-count leak probe

# PubMed hits for "<cancer> molecular subtypes" — proxy for prior-knowledge volume.
# ONLY the first four are verified (snapshot 2026-07). LUSC/PRAD/UCEC are NOT filled in:
# leave them out rather than fabricate a count. A cohort absent here is dropped from the
# literature-vs-grounding scatter only (never from the main aggregates), with a visible note.
# To include a new cohort in that panel, add its real PubMed count here.
PAPERS = {'BRCA': 13305, 'LUAD': 2091, 'OV': 1982, 'LIHC': 1159}

# (label, results_dir, color, tier). tier ∈ {'flagship','flash',...} — drives the tier caveat.
# The tier field is REQUIRED for honest reporting: Gemini runs a Flash tier while the others
# run flagship, so a Gemini deficit is confounded by tier (see docs/MODEL_LADDER.md §2).
MODELS = [
    ('Sonnet 5', 'results/tcga/ladder/sonnet5_20260713', '#7F77DD', 'flagship'),
    ('GPT-5.5', 'results/tcga/ladder/gpt55_20260707', '#1D9E75', 'flagship'),
    ('Gemini 3.5 Flash', 'results/tcga/ladder/gemini35flash_20260716', '#EF9F27', 'flash'),
]
OUT_PATH = 'results/tcga/ladder/LADDER_3MODEL.html'

_ap = argparse.ArgumentParser(description=__doc__)
_ap.add_argument('--model', action='append', metavar='LABEL:DIR:#COLOR:TIER',
                 help='override a model (repeatable); replaces the built-in list on first use')
_ap.add_argument('--cohorts', default=None, help='comma-separated; default = auto-derive from the data')
_ap.add_argument('--out', default=None, help=f'output HTML path (default {OUT_PATH})')
_args = _ap.parse_args()
if _args.model:
    MODELS = []
    for spec in _args.model:
        parts = spec.split(':')
        lab, d = parts[0], parts[1]
        col = next((p for p in parts[2:] if p.startswith('#')), '#888')
        tier = next((p for p in parts[2:] if not p.startswith('#')), 'flagship')
        MODELS.append((lab, d, col, tier))
if _args.out:
    OUT_PATH = _args.out
cohorts = [c.strip().upper() for c in _args.cohorts.split(',')] if _args.cohorts else None  # None → derive post-load

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

DATA = {name: load(root) for name, root, *_ in MODELS}
COL = {t[0]: t[2] for t in MODELS}
TIER = {t[0]: t[3] for t in MODELS}
ROOT = {t[0]: t[1] for t in MODELS}

# Cohorts: derive from the data unless pinned on the CLI. Ordering = most-studied first
# (PAPERS desc), unknown-paper cohorts alphabetical after — so a 4- or 7-cohort run both work.
if cohorts is None:
    seen = {x['cohort'] for R in DATA.values() for x in R
            if x['arm'] in ('g0', 'g1', 'g2') and x['cohort']}
    cohorts = sorted(seen, key=lambda c: (-(PAPERS.get(c) or 0), c))
LIT_COHORTS = [c for c in cohorts if c in PAPERS]          # only these appear in the literature panel
LIT_MISSING = [c for c in cohorts if c not in PAPERS]      # noted, not fabricated

def stats(R):
    hon = [x for x in R if x['arm'] in ('g0', 'g1', 'g2')]
    def ng(dk):
        c = Counter(x['lvl'][dk]['support'] for x in hon); t = sum(c.values())
        return (c.get('unsupported', 0) + c.get('anchored', 0)) / t
    hv = [x['norm'] for x in hon]
    n = len(hv)
    # 95% CI half-width on the honest-arm outcome mean (t-approx; ~1.96 at these n).
    ci = (_tcrit(n - 1) * st.stdev(hv) / math.sqrt(n)) if n > 1 else 0.0
    return dict(outcome=st.mean(hv), osd=st.pstdev(hv), n_honest=n, ci=ci,
        support=st.mean([x['ss'] for x in hon]),
        cby={c: st.mean([x['norm'] for x in hon if x['cohort'] == c] or [0]) for c in cohorts},
        csd={c: st.pstdev([x['norm'] for x in hon if x['cohort'] == c] or [0]) for c in cohorts},
        id_ng=ng('d2_identity'), d1_ng=ng('d1_partition'), d3_ng=ng('d3_mechanism'),
        fa=sum(1 for x in R if x['arm'] == 'g3a' and x['verdict'] == 'mislead_cohort'),
        fb=sum(1 for x in R if x['arm'] == 'g3b' and x['verdict'] == 'mislead_cohort'))

def _tcrit(df):
    # two-sided 95% t critical, small table + normal floor — avoids a scipy dependency.
    T = {1:12.71,2:4.30,3:3.18,4:2.78,5:2.57,6:2.45,8:2.31,10:2.23,15:2.13,20:2.09,30:2.04,60:2.00}
    if df <= 0: return 0.0
    for k in sorted(T):
        if df <= k: return T[k]
    return 1.96

S = {m: stats(DATA[m]) for m in DATA}
ranked = sorted(S, key=lambda m: -S[m]['outcome'])
best, worst = ranked[0], ranked[-1]

# ---- Chain-of-thought layer (from summarize_cot.py's _cotsummary.json, neutral DeepSeek) ----
# The outcome scores tie; the CoT summary shows HOW the models diverge. Key signal =
# identity_derivation on the BLINDED G2 arm (derive the cancer from anonymized data vs recall it).
ID_ORDER = ['data-derived', 'mixed', 'recalled-prior', 'not-established']
def load_cot(root):
    out = []
    for p in glob.glob(f"{root}/**/*_cotsummary.json", recursive=True):
        try: j = json.load(open(p))
        except Exception: continue
        j['arm'] = os.path.basename(p).split('_')[0]
        out.append(j)
    return out
COT = {m: load_cot(ROOT[m]) for m in ranked}
HAS_COT = any(COT.values())
def cot_stats(R):
    g2  = [x for x in R if x['arm'] == 'g2']
    hon = [x for x in R if x['arm'] in ('g0', 'g1', 'g2')]
    idc = Counter(x.get('identity_derivation') for x in g2)
    return dict(
        n_g2=len(g2), g2_id=idc,
        g2_derived=idc.get('data-derived', 0) / max(len(g2), 1),
        g2_recalled=(idc.get('recalled-prior', 0)) / max(len(g2), 1),
        rigor_high=Counter(x.get('validation_rigor') for x in hon).get('high', 0) / max(len(hon), 1),
        pivots=st.mean([x.get('num_pivots', 0) for x in R]) if R else 0.0)
CS = {m: cot_stats(COT[m]) for m in ranked} if HAS_COT else {}
# rank models by how much they DERIVE identity on G2 (the CoT thesis axis)
cot_ranked = sorted(ranked, key=lambda m: -CS[m]['g2_derived']) if HAS_COT else ranked
cot_best, cot_worst = (cot_ranked[0], cot_ranked[-1]) if HAS_COT else (best, worst)

# ---- Benchmark-recognition probe: count-based pre-codebook cohort identity ----
# Dataset SHAPE is the one property blinding can't remove. A memorized cohort size (BRCA=1095,
# LUAD=518, …) lets a model name the cancer from the ROW COUNT before any biology — a benchmark
# leak invisible to every score, visible only in the pre-reveal reasoning (WHY + observations).
_COUNT_PAT = re.compile(r'\b(sample size|n\s*=\s*\d{3,4}|\d{3,4}\s+(?:samples|tumou?rs|patients|'
                        r'cases)|typical of|number of samples|cohort of \d{3,4})\b', re.I)
def _cohort_sizes():
    sz = {}
    for m in ranked:
        for p in glob.glob(f"{ROOT[m]}/g2_*/grouping.json"):
            coh = os.path.basename(os.path.dirname(p)).split('_')[1].upper()
            try: sz[coh] = len(json.load(open(p)))
            except Exception: pass
    return sz
SIZES = _cohort_sizes()
def _count_leak(root):
    """(n_count_based_identity, n_g2, best_verbatim_quote) over blinded G2 episodes."""
    n = hits = 0; quote = None; quote_has_size = False
    for p in glob.glob(f"{root}/g2_*/*.json"):
        if os.path.basename(p)[:-5] != os.path.basename(os.path.dirname(p)):
            continue
        n += 1
        try: rec = extract_episode(p)
        except Exception: continue
        coh, cbk = rec['cohort'], rec['codebook_at']
        for c in rec['calls']:
            if cbk and cbk > 0 and c['idx'] >= cbk:  # only PRE-reveal
                continue
            ch = (c['obs'].get('current_hypothesis') if c.get('obs') else "") or ""
            t = (c.get('why', '') + ' ' + c.get('expects', '') + ' ' + ch)
            if DISEASE_PAT.search(t) and (_COUNT_PAT.search(t) or str(SIZES.get(coh, '')) in t):
                hits += 1
                # prefer a quote that literally contains the cohort's size (most damning)
                cand = ch.strip() or t.strip()
                if quote is None or (str(SIZES.get(coh, '')) in cand and not quote_has_size):
                    quote = cand; quote_has_size = str(SIZES.get(coh, '')) in cand
                break
    return hits, n, quote
LEAK = {m: _count_leak(ROOT[m]) for m in ranked} if HAS_COT else {}
LEAK_MODEL = max(LEAK, key=lambda m: LEAK[m][0]) if LEAK else None  # the model that does it most
NEP = {m: len(DATA[m]) for m in DATA}                 # episodes per model (any arm)
N_TOTAL = sum(NEP.values())
N_TYP = Counter(NEP.values()).most_common(1)[0][0] if NEP else 0  # typical eps/model
SEEDS = sorted({x['seed'] for R in DATA.values() for x in R if x['seed'] is not None})

# Outcome-ranking significance: do the top-two models' honest-outcome CIs overlap?
# If so, the *outcome* leaderboard is not statistically separated — which is precisely
# this report's thesis (the split is on identity grounding, not outcome). Report it plainly.
def _sep(a, b):
    sa, sb = S[a], S[b]
    se = math.sqrt((sa['ci'] / max(_tcrit(sa['n_honest'] - 1), 1e-9)) ** 2
                   + (sb['ci'] / max(_tcrit(sb['n_honest'] - 1), 1e-9)) ** 2)
    if se == 0: return None
    return abs(sa['outcome'] - sb['outcome']) / se          # z-like separation
OUT_Z = _sep(ranked[0], ranked[1]) if len(ranked) > 1 else None
OUT_SIG = (OUT_Z is not None and OUT_Z >= 1.96)
sig_txt = (f"the top-two outcome means are separated ({ranked[0]} vs {ranked[1]}, z≈{OUT_Z:.1f})"
           if OUT_SIG else
           f"the top outcome means are <b>within noise</b> (95% CIs overlap"
           + (f", {ranked[0]} vs {ranked[1]} z≈{OUT_Z:.1f}" if OUT_Z is not None else "") + ")")

# Caveats are generated from each model's stats by RANK (best / middle / worst on outcome),
# not keyed by model name — so renaming or swapping a model can never KeyError, and the prose
# always tracks the actual numbers. n3 = G3 arm denominator (episodes per mislead sub-arm).
def cav(m):
    s = S[m]; rank = ranked.index(m)
    gap = s['id_ng'] / max(S[best]['id_ng'], 0.01)
    n3 = max(sum(1 for x in DATA[m] if x['arm'] == 'g3a'), 1)
    tier_note = (f" <b>Tier:</b> {TIER[m]} — a lighter tier than the flagship models here, so any "
                 f"deficit is <b>confounded by tier</b>, not attributable to the model family."
                 if TIER.get(m) != 'flagship' else "")
    id_s = f"{s['id_ng']:.0%}"
    fool = f"fooled g3a {s['fa']}/{n3} · g3b {s['fb']}/{n3}"
    if rank == 0:
        body = (f"Top outcome ({s['outcome']:.3f}) and best-grounded identity caller "
                f"(unsupported {id_s}). Watch: early-mislead susceptibility ({fool}) and any lean "
                f"on recalled partitions.")
    elif rank == len(ranked) - 1:
        body = (f"Lowest outcome ({s['outcome']:.3f}), highest variance (SD {s['osd']:.3f}). "
                f"Defining gap is <b>identity</b>: commits to a grouping without grounding the "
                f"cancer type <b>{id_s}</b> of the time (~{gap:.0f}× {best}); {fool}. An "
                f"outcome-only leaderboard understates this.")
    else:
        body = (f"Mid-pack on outcome ({s['outcome']:.3f}); top on BRCA ({s['cby'].get('BRCA', 0):.3f}). "
                f"Identity unsupported {id_s}; {fool} — no standout strength or failure.")
    return body + tier_note

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
    epsections += (f'<details><summary><b style="color:{COL[m]}">{m}</b> — {NEP[m]} episodes '
        f'(outcome {S[m]["outcome"]:.3f} · identity-unsupported {S[m]["id_ng"]:.0%})</summary>'
        f'<div class="tblwrap"><table class="ep"><thead><tr><th>arm</th><th>cohort</th><th class="num">seed</th>'
        f'<th class="num">outcome</th><th class="num">support</th><th>D1·D2·D3</th><th>D2 identity — judge evidence</th></tr></thead>'
        f'<tbody>{ep_rows(DATA[m])}</tbody></table></div></details>')

# ---- charts data ----
out_ds = [{'label': m, 'color': COL[m], 'data': [round(S[m]['cby'][c], 3) for c in cohorts], 'errors': [round(S[m]['csd'][c], 3) for c in cohorts]} for m in ranked]
id_data = {'labels': ranked, 'colors': [COL[m] for m in ranked], 'vals': [round(S[m]['id_ng'], 3) for m in ranked]}
# CoT: G2 identity-derivation composition (stacked), ordered by % derived
cot_stack = {'labels': cot_ranked,
    'derived':  [CS[m]['g2_id'].get('data-derived', 0) for m in cot_ranked],
    'mixed':    [CS[m]['g2_id'].get('mixed', 0) for m in cot_ranked],
    'recalled': [CS[m]['g2_id'].get('recalled-prior', 0) + CS[m]['g2_id'].get('not-established', 0)
                 for m in cot_ranked]} if HAS_COT else {'labels': [], 'derived': [], 'mixed': [], 'recalled': []}

# ---- radar / capability profile (6 axes, outcome-visible -> process-hidden) ----
def clamp(v): return max(0.0, min(1.0, v))
# Hardest cohort = lowest pooled outcome across models (was hardcoded 'OV'). Fooling denominator
# = actual #G3 episodes/model (was hardcoded 12), so 4- and 7-cohort runs both normalize right.
HARD_COH = min(cohorts, key=lambda c: st.mean([S[m]['cby'][c] for m in ranked])) if cohorts else 'OV'
G3N = {m: max(sum(1 for x in DATA[m] if x['arm'] in ('g3a', 'g3b')), 1) for m in ranked}
RAX = ['Faithfulness', f'Hard-cohort ({HARD_COH})', 'Consistency', 'Support score', 'Fooling resist.', 'Identity grounding']
def radar_vals(m):
    s = S[m]
    return [round(clamp(s['outcome']/0.65), 3), round(clamp(s['cby'][HARD_COH]/0.5), 3),
            round(clamp(1 - s['osd']/0.15), 3), round(clamp(s['support']/5), 3),
            round(clamp(1 - (s['fa']+s['fb'])/G3N[m]), 3), round(clamp(1 - s['id_ng']), 3)]
radar_models = [{'label': m, 'color': COL[m], 'vals': radar_vals(m)} for m in ranked]
# companion raw-value table
raw_axis = [
    ('Faithfulness', lambda s: f"{s['outcome']:.3f}"),
    (f'Hard-cohort ({HARD_COH})', lambda s: f"{s['cby'][HARD_COH]:.3f}"),
    ('Consistency (SD, ↓)', lambda s: f"{s['osd']:.3f}"),
    ('Support score /5', lambda s: f"{s['support']:.2f}"),
    ('Fooling resist. (# fooled, ↓)', lambda s: f"{s['fa']+s['fb']} fooled"),
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
for name, root, *_ in MODELS:
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
for name, root, *_ in MODELS:
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

# ---- literature volume vs identity grounding ---- (PAPERS defined at top; extend it there)
id_grounded = {m: {} for m in ranked}
for name, root, *_ in MODELS:
    for c in cohorts:
        vs = []
        for sp in glob.glob(f"{root}/**/*_supportscores.json", recursive=True):
            lab = os.path.basename(sp)
            if lab.split('_')[0] not in ('g0', 'g1', 'g2'): continue
            e = json.load(open(sp.replace('_supportscores.json', '.json')))
            if e.get('cohort') != c: continue
            vs.append(1 if json.load(open(sp))['levels']['d2_identity']['support'] == 'grounded' else 0)
        id_grounded[name][c] = round(st.mean(vs), 3) if vs else None
# Only cohorts with a known PubMed count go in the scatter (no fabricated x-values).
lit_order = sorted(LIT_COHORTS, key=lambda c: PAPERS[c])
scat_ds = [{'label': m, 'color': COL[m],
            'points': [{'x': PAPERS[c], 'y': id_grounded[m][c], 'c': c} for c in lit_order]} for m in ranked]
lit_note = (f' <b>Not shown</b> (no PubMed count on file): {", ".join(LIT_MISSING)} — add their counts '
            f'to <code>PAPERS</code> to include them.' if LIT_MISSING else '')

# ---- CNA modality engagement (proxy) ----
# The 7-cohort benchmark added a third modality (expression + mutation + CNA). There is no
# scored "did it use CNA" field, so this is a PROXY: mean # of run_code calls per honest
# episode whose code references copy-number, read from the episode trace. It measures
# engagement, NOT correctness. Fully guarded — any parse failure yields None (panel omitted),
# and it reads ~0 for pre-CNA runs (e.g. the old 4-cohort ladder), which is correct.
def _cna_engagement(root):
    per_ep = []
    for sp in glob.glob(f"{root}/**/*_supportscores.json", recursive=True):
        if os.path.basename(sp).split('_')[0] not in ('g0', 'g1', 'g2'):
            continue
        try:
            e = json.load(open(sp.replace('_supportscores.json', '.json')))
            hits = 0
            for msg in e.get('messages', []):
                content = msg.get('content')
                blocks = content if isinstance(content, list) else []
                for b in blocks:
                    if isinstance(b, dict) and b.get('type') == 'tool_use' and b.get('name') == 'run_code':
                        code = (b.get('input') or {}).get('code', '') or ''
                        if 'cna' in code.lower() or 'copy number' in code.lower() or 'copy_number' in code.lower():
                            hits += 1
            per_ep.append(hits)
        except Exception:
            continue
    return round(st.mean(per_ep), 1) if per_ep else None
CNA_ENG = {m: _cna_engagement(root) for m, root, *_ in MODELS}
HAS_CNA = any(v for v in CNA_ENG.values())  # any model actually touched CNA → show the panel

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
        f'<div class="mini">fooled g3a {s["fa"]}/{max(sum(1 for x in DATA[m] if x["arm"]=="g3a"),1)} · g3b {s["fb"]}/{max(sum(1 for x in DATA[m] if x["arm"]=="g3b"),1)} · D1/D3 not-grounded {s["d1_ng"]:.0%}/{s["d3_ng"]:.0%}</div>'
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
var COTS=__COTS__;
if(COTS.labels.length){var mk=function(lab,key,c){return{label:lab,data:COTS[key],backgroundColor:c,borderWidth:0};};
new Chart(document.getElementById('cotid'),{type:'bar',
 data:{labels:COTS.labels,datasets:[mk('data-derived','derived','#3fb950'),mk('mixed','mixed','#d29922'),mk('recalled/none','recalled','#f85149')]},
 options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{display:true,labels:{color:ink,boxWidth:11,font:{size:11}}}},
 scales:{x:{stacked:true,ticks:{color:ink,font:{size:12}},grid:{display:false}},y:{stacked:true,ticks:{color:ink},grid:{color:grid},title:{display:true,text:'G2 episodes (blinded)',color:ink}}}});}
var SCAT=__SCAT__;
var lblP={id:'lbl',afterDatasetsDraw:function(chart){var ctx=chart.ctx;ctx.save();ctx.font='10px sans-serif';ctx.fillStyle='#9aa7b4';chart.data.datasets.forEach(function(dset,di){var meta=chart.getDatasetMeta(di);meta.data.forEach(function(pt,i){var c=dset.data[i].c;ctx.fillText(c,pt.x+6,pt.y+3);});});ctx.restore();}};
new Chart(document.getElementById('lit'),{type:'scatter',data:{datasets:SCAT.map(function(d){return{label:d.label,borderColor:d.color,backgroundColor:d.color,data:d.points,showLine:true,borderWidth:2,pointRadius:4,tension:0};})},options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{display:false},tooltip:{callbacks:{label:function(c){return c.raw.c+': '+(c.raw.y*100).toFixed(0)+'% grounded ('+c.raw.x.toLocaleString()+' papers)';}}}},scales:{x:{type:'logarithmic',ticks:{color:ink,callback:function(v){return v>=1000?(v/1000)+'k':v;}},grid:{color:grid},title:{display:true,text:'PubMed papers ("<cancer> molecular subtypes", log)',color:ink}},y:{min:0,max:1,ticks:{color:ink,stepSize:0.25,callback:function(v){return (v*100).toFixed(0)+'%';}},grid:{color:grid},title:{display:true,text:'identity grounded rate',color:ink}}}},plugins:[lblP]});
"""
JS = (JS.replace('__COTS__', json.dumps(cot_stack))
        .replace('__OUT__', json.dumps(out_ds)).replace('__ID__', json.dumps(id_data)).replace('__COH__', json.dumps(cohorts))
        .replace('__RAX__', json.dumps(RAX)).replace('__RM__', json.dumps(radar_models))
        .replace('__SCAT__', json.dumps(scat_ds)))
leg = "".join(f'<span><i style="background:{COL[m]}"></i>{m}</span>' for m in ranked)
gap = S[worst]['id_ng'] / max(S[best]['id_ng'], 0.01)
ahead = "".join(f'<th class="num">{a.upper()}</th>' for a in arms)

# ---- dynamic header bits (model count, tier banner, CNA panel) ----
NM = len(ranked)
model_line = " · ".join(ranked)
def pct(v): return f"{v:.0%}" if isinstance(v, (int, float)) else "n/a"
_ft = [m for m in ranked if TIER.get(m) != 'flagship']
tier_banner = ""
if _ft:
    tier_banner = ('<div class="warn"><b>⚠️ Tier asymmetry — read before ranking.</b> '
        + ", ".join(f'{m} runs a <b>{TIER[m]}</b> tier' for m in _ft)
        + f', while the others run flagship tiers. Any deficit for {", ".join(_ft)} is '
          '<b>confounded by tier</b> and must not be attributed to the model family '
          '(see <code>docs/MODEL_LADDER.md</code> §2). Restore parity by re-running on the flagship tier.</div>')
# ---- Chain-of-thought section (the resolution to the outcome tie) ----
cot_section = ""
cot_kfind = ""
if HAS_COT:
    cot_kfind = (f'<div class="kfind"><div class="ix">🧠</div><div><b>Chain-of-thought resolves '
        f'the tie.</b> On the blinded G2 arm, {cot_best} <b>derives</b> the cancer identity from '
        f'the data {CS[cot_best]["g2_derived"]:.0%} of the time vs {cot_worst} at '
        f'{CS[cot_worst]["g2_derived"]:.0%} — same outcome, opposite process (derive vs recall). '
        f'See the chain-of-thought section.</div></div>')
    rows = ""
    for m in cot_ranked:
        cs = CS[m]
        rows += (f'<tr><td class="grp" style="color:{COL[m]}">{m}</td>'
                 f'<td class="num"><b>{cs["g2_derived"]:.0%}</b></td>'
                 f'<td class="num">{cs["g2_id"].get("mixed",0)}/{cs["n_g2"]}</td>'
                 f'<td class="num">{cs["g2_recalled"]:.0%}</td>'
                 f'<td class="num">{cs["rigor_high"]:.0%}</td>'
                 f'<td class="num">{cs["pivots"]:.2f}</td></tr>')
    dsp = f"{CS[cot_best]['g2_derived']:.0%}"
    wsp = f"{CS[cot_worst]['g2_derived']:.0%}"
    # sample-count benchmark-recognition callout
    leak_callout = ""
    if LEAK and LEAK_MODEL and LEAK[LEAK_MODEL][0] > 0:
        lh, ln, lq = LEAK[LEAK_MODEL]
        others = "; ".join(f"{m} {LEAK[m][0]}/{LEAK[m][1]}" for m in ranked if m != LEAK_MODEL)
        szs = ", ".join(f"{c}={SIZES[c]}" for c in sorted(SIZES))
        quote_html = (f'<div class="ev bad" style="margin-top:8px"><div class="evq">“{esc(lq)}”</div>'
                      f'<div class="evh" style="margin-top:4px">— {LEAK_MODEL}, pre-reveal observation</div></div>'
                      if lq else "")
        leak_callout = (
            '<div class="warn" style="margin-top:12px"><b>⚠️ Benchmark recognition — the shape leak.</b> '
            'Blinding hides gene symbols, sample barcodes and identity-bearing clinical fields, but it '
            'cannot hide the dataset\'s <b>shape</b>. Each TCGA cohort has a fingerprint sample count '
            f'({szs}). On the blinded G2 arm, <b>{LEAK_MODEL} named the correct cancer from the row '
            f'count alone in {lh}/{ln} episodes — before any clustering, DE or mutation analysis</b> '
            f'(others: {others}). This is recall in its most literal form: the benchmark identified from '
            'a single integer, not the disease derived from its molecular profile — a shortcut invisible '
            'to outcome and to the grounding score, surfacing only in the reasoning trace.'
            f'{quote_html}'
            '<div class="lead" style="margin-top:8px"><b>Two bounds:</b> the behaviour is confined to the '
            'Flash-tier model, so a capability/tier confound cannot be excluded; and the evidence is the '
            'agent\'s <i>stated</i> reasoning (WHY headers + observations), since raw chain-of-thought is '
            'not retained. Ablation to prove it: subsample every cohort to a common n and the pre-reveal '
            'recognition should collapse.</div></div>')
    cot_section = f"""
<h2>How the models actually reason (chain-of-thought)</h2>
<div class="panel">
<p class="lead" style="margin-top:0"><b>This is the resolution to the outcome tie.</b> A neutral judge
(DeepSeek) summarized each episode's reasoning trace — the symmetric channels only
(<code>record_observation</code> hypothesis log + <code>#WHY</code> intent + submission; model
"thinking" is not persisted, so it is not used). The discriminating axis is
<b>identity_derivation on the blinded G2 arm</b>: did the agent <b>derive</b> the cancer identity
from the anonymized data, or <b>recall</b> it from priors? Outcome cannot see this — but it is
exactly the correct-but-unwarranted behaviour the benchmark targets.</p>
<div style="display:flex;gap:18px;flex-wrap:wrap;align-items:center">
<div class="chartbox" style="flex:1;min-width:300px;height:280px"><canvas id="cotid" role="img" aria-label="G2 identity-derivation composition per model."></canvas></div>
<div style="flex:1;min-width:300px"><table><thead><tr><th>model</th><th class="num">G2 derived</th><th class="num">mixed</th><th class="num">recalled</th><th class="num">rigor high</th><th class="num">pivots</th></tr></thead><tbody>{rows}</tbody></table></div>
</div>
<p class="lead"><b>{cot_best}</b> derives the cohort identity from data on <b>{dsp}</b> of blinded G2
episodes; <b>{cot_worst}</b> only <b>{wsp}</b> — the rest it recalls or guesses. The models
<i>tie on outcome</i> (see headline) yet split sharply here: the weaker model reaches comparable
scores by <b>recalling rather than deriving</b>. This is the process-level mechanism behind the
support-grounding gap above (D2 unsupported identity), now visible in the reasoning itself.
Bars = episode counts (n={CS[cot_best]['n_g2']} G2 episodes/model); <code>identity_derivation</code>
is a neutral-judge label (evidence, not ground truth — see the multi-judge check in
<code>cot_compare.py --agree</code>).</p>
{leak_callout}</div>"""

cna_panel = ""
if HAS_CNA:
    crows = "".join(f'<tr><td class="grp" style="color:{COL[m]}">{m}</td>'
                    f'<td class="num">{CNA_ENG[m] if CNA_ENG[m] is not None else "n/a"}</td></tr>' for m in ranked)
    cna_panel = ('<h2>CNA modality engagement</h2><div class="panel">'
        f'<div class="tblwrap"><table><thead><tr><th>model</th>'
        f'<th class="num">CNA run_code calls / honest ep</th></tr></thead><tbody>{crows}</tbody></table></div>'
        '<p class="lead">The benchmark carries three modalities (expression + mutation + <b>CNA</b>). '
        '<b>Proxy</b> = mean run_code calls per honest episode whose code references copy-number — it measures '
        '<b>engagement, not correctness</b>, and reads ~0 for pre-CNA runs.</p></div>')

html = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>TCGA Benchmark — {NM}-Model Detailed Report</title><style>{CSS}</style></head><body><div class="wrap">
<h1>TCGA Agent Benchmark — {NM}-Model Detailed Report</h1>
<div class="meta">{model_line} · {N_TYP} episodes each ({N_TOTAL} total, {len(SEEDS)} seeds) · two-part scoring: outcome (v3) + support/grounding · grounding judge = <b>DeepSeek-v4-pro</b> (neutral, not in tested set)</div>
{tier_banner}
<div class="tiles">{tiles}</div>

<h2>Headline</h2>
<div class="panel">
<div class="kfind"><div class="ix">🔍</div><div><b>Identity is where the models split — and outcome scores hide it.</b> {best} and {worst} differ modestly on outcome ({S[best]['outcome']:.3f} vs {S[worst]['outcome']:.3f}) but ~{gap:.0f}× on unsupported identity recall ({S[best]['id_ng']:.0%} vs {S[worst]['id_ng']:.0%}).</div></div>
<div class="kfind"><div class="ix">📏</div><div><b>The outcome ranking is not the story — its margin is thin.</b> On honest-arm outcome, {sig_txt}. Outcome means carry ±{S[best]['ci']:.3f} (95% CI, {best}); the models are separated on <b>identity grounding</b>, not outcome.</div></div>
{cot_kfind}
<div class="kfind"><div class="ix">📊</div><div><b>Outcome and grounding are positively correlated</b> — better models both discover and ground more. "Higher-outcome models just recall more" is <b>not</b> what's happening.</div></div>
<div class="kfind"><div class="ix">🎣</div><div><b>All models are fooled by misleading framing</b> ({min(S[m]['fa']+S[m]['fb'] for m in ranked)}–{max(S[m]['fa']+S[m]['fb'] for m in ranked)} of {sum(1 for x in DATA[best] if x['arm'] in ('g3a','g3b'))} G3 episodes), with <b>no consistent early≫late gradient</b>.</div></div>
</div>

<h2>Capability profile</h2>
<div class="panel"><div class="legend">{leg}</div>
<div style="display:flex;gap:18px;flex-wrap:wrap;align-items:center">
<div class="chartbox" style="flex:1;min-width:300px;height:340px"><canvas id="radar" role="img" aria-label="Radar chart of six abilities per model."></canvas></div>
<div style="flex:1;min-width:280px"><table><thead><tr><th>axis (raw)</th>{"".join(f'<th class="num" style="color:{COL[m]}">{m.split()[0]}</th>' for m in ranked)}</tr></thead><tbody>{radrows}</tbody></table></div>
</div>
<p class="lead">Axes ordered <b>outcome-visible → process-hidden</b> (Faithfulness…Consistency on the outcome side; Support…Identity grounding on the process side). All three overlap on the outcome side; <b>{worst}'s polygon caves in on the process side</b>, deepest at identity grounding — the asymmetry an outcome-only leaderboard misses. Each spoke normalized 0–1 (Faithfulness ÷0.65, {HARD_COH} ÷0.5, Consistency 1−SD/0.15, Support ÷5, Fooling 1−fooled/#G3, Identity 1−unsupported); <b>shape, not area</b>, is the comparison — raw values in the table.</p></div>

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
<p class="lead" style="margin-top:8px">Pooled across all {NM} models (honest arms). The difficulty ranking is <b>identical for every model</b> — it's a property of the <b>biology</b>, not the agent. The gap is dominated by one component: <b>genomic·drivers</b> — OV scores <b>0.00</b> vs ~0.95 for BRCA/LUAD. HGSOC is <b>copy-number–driven with near-universal TP53</b>, so there are <i>no subtype-differentiating point mutations</i> for that component to reward (a real feature of the disease, per the cohort card). Weak prognostic separation (clinical 0.08) and purity-confounded transcriptional structure (0.18) compound it; LIHC sits between because HCC is only partly mutation-driven (drivers 0.33).</p>
<p class="lead"><b>Note the knowledge components are flat across cohorts</b> (marker/pathway/mechanism ≈ constant) — agents narrate equally well everywhere. Difficulty lives entirely in the <b>data-grounded</b> components. <b>Implication:</b> cross-cohort scores are <b>not directly comparable</b> — an OV 0.37 and a BRCA 0.54 reflect task difficulty, not just agent skill; model comparison is only fair <i>within</i> a cohort or difficulty-normalized across.</p></div>

<h2>Literature volume vs identity grounding</h2>
<div class="panel"><div class="legend">{leg}</div>
<div class="chartbox" style="height:320px"><canvas id="lit" role="img" aria-label="Scatter of identity-grounded rate vs PubMed paper count per cohort, one line per model."></canvas></div>
<p class="lead">x = PubMed hits for "&lt;cancer&gt; molecular subtypes" (log; {", ".join(f"{c} {PAPERS[c]/1000:.1f}k" for c in lit_order)}; snapshot 2026-07) — a proxy for how much prior knowledge each cohort affords. <b>The story is model-type, not a clean correlation.</b> <span style="color:{COL[worst]}">{worst}</span> is the most <b>literature-dependent</b>: it grounds identity best on the most-studied cohort ({pct(id_grounded[worst].get(lit_order[-1]) if lit_order else None)} on {lit_order[-1] if lit_order else "—"}) and weakest on the least-studied — it recalls identity mainly when the cancer is well-represented in the literature. The stronger models stay high regardless of paper count — they <b>derive</b> identity from computed markers (e.g. TP53), so they don't depend on the literature.{lit_note}</p>
<p class="lead"><b>Caveats:</b> n={len(LIT_COHORTS)} cohorts — illustrative, not a fit. Biological derivability matters alongside prior-knowledge volume (e.g. HCC's liver-specific AFP/CYP450 are easy to derive even with little literature), and #papers is confounded with cohort commonness and subtype-cleanliness.</p></div>

<h2>The finding: unsupported identity recall</h2>
<div class="panel"><div class="chartbox" style="height:250px"><canvas id="idc" role="img" aria-label="Unsupported identity-recall rate by model."></canvas></div>
<p class="lead">Fraction of episodes where the model committed to a grouping while recalling / never establishing the cohort identity from this cohort's computed data (grounding judge, D2). The recall-miscalibration locus — invisible to an outcome-only leaderboard.</p></div>
{cot_section}

<h2>What "unsupported" vs "grounded" identity actually looks like</h2>
<div class="panel">
<p class="lead" style="margin-top:0">Same-episode contrast, verbatim from the grounding judge's <code>evidence</code> field.</p>
<div style="font-weight:600;color:var(--bad);font-size:12px;margin:4px 0">Unsupported — identity recalled / never established from data</div>{uns_html}
<div style="font-weight:600;color:var(--good);font-size:12px;margin:10px 0 4px">Grounded — identity inferred from this cohort's computed data</div>{grd_html}
</div>

<h2>Per-model performance &amp; caveats</h2>
<div class="cards">{cards}</div>

{cna_panel}

<h2>Outcome × support by arm</h2>
<div class="panel"><div class="tblwrap"><table><thead><tr><th>model</th>{ahead}</tr></thead><tbody>{armtab}</tbody></table></div>
<p class="lead">Each cell: mean outcome, with mean support-score (/5) below. G3a/G3b are the mislead arms.</p></div>

<h2>Per-episode detail (all {N_TOTAL})</h2>
<p class="lead">Chips = grounding verdict per decision (D1·D2·D3): <span class="chip g">gr</span> grounded · <span class="chip m">un</span> unsupported · <span class="chip b">an</span> anchored. 🎣 = fooled (mislead cohort).</p>
{epsections}

<h2>Open gates before publication</h2>
<div class="warn">
(1) <b>D1/D3 constant-grounded</b> — hand-audit ~10 to confirm agents genuinely ground partition/mechanism vs. a judge default.<br>
(2) <b>Multi-judge robustness</b> — re-score a subset with a second neutral judge; confirm the identity ordering ({" &lt; ".join(reversed(ranked))} by grounding) holds before {worst}'s {S[worst]['id_ng']:.0%} is a headline number.<br>
(3) <b>Record the judge model</b> in the score files (currently absent).<br>
(4) n={N_TYP}/model across {len(SEEDS)} seeds — the outcome CIs overlap ({sig_txt}); the defensible claims are on identity grounding, not the outcome ranking. Add seeds to separate outcome.<br>
{'(5) <b>Tier confound</b> — ' + ", ".join(_ft) + f" run a non-flagship tier; the Gemini gap is not a clean model-family result until re-run on the flagship tier.<br>" if _ft else ''}</div>

<div class="foot">Outcome from <code>*_v3scores.json</code>, grounding from <code>*_supportscores.json</code> (judge: DeepSeek-v4-pro). Honest arms = G0–G2. Generated by <code>scripts/gen_ladder_report.py</code>. Charts are live Chart.js (cdnjs, online).</div>
</div>
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.js"></script>
<script>{JS}</script>
</body></html>"""

out = OUT_PATH
open(out, 'w').write(html)
print("wrote", out, len(html), "bytes")
