#!/usr/bin/env python3
"""Instruction-ablation report — DETAILED (staged Stage 0-5 prompt) vs LEAN (no prescribed
procedure) across all models. Same model/cohorts/seeds/budget; only the prompt differs. Pairs
every metric per model so you can read whether instruction changes WHAT is found (outcome),
how GROUNDED it looks (support/D2), and how it actually REASONS (CoT derive-vs-recall, fooling,
observation count). Reads v3 + support + cotsummary + the raw trace (record_observation count).

Usage: python scripts/gen_ablation_report.py     ->  results/tcga/reports/ABLATION_REPORT.html
"""
import glob, json, os, re, sys, statistics as st
from collections import Counter
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import judges_config as J
import panel_data
import panel_judges
import runs_config


from g3_exposure import exposed_g3
from extract_cot import extract_episode, count_based_identity

# (label, detailed_dir, lean_dir, color, tier)
PAIRS = runs_config.pairs()
OUT = 'results/tcga/reports/ABLATION_REPORT.html'

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
    # PANEL-REDUCED. These loaded J.tags()[0] — nemotron — for outcome, support AND CoT while
    # the report footer described a three-family panel. Every principal metric was one judge's
    # value presented as a panel result.
    v3 = {}; sup = {}; cot = {}
    for p in glob.glob(panel_data.artifact_glob(D, 'outcome', J.tags()[0])):
        ed = panel_data.episode_dir_of(p); per = panel_data.load_all_judges(ed, 'outcome')
        if not per: continue
        b = dict(next(iter(per.values())))
        b['normalized'] = panel_data.mean([v.get('normalized') for v in per.values()])
        b['cohort_identity_verdict'] = J.consensus(
            [v.get('cohort_identity_verdict') for v in per.values()]) or ''
        v3[panel_data.label_of(p)] = b
    for p in glob.glob(panel_data.artifact_glob(D, 'support', J.tags()[0])):
        ed = panel_data.episode_dir_of(p); per = panel_data.load_all_judges(ed, 'support')
        if not per: continue
        b = dict(next(iter(per.values())))
        b['support_score'] = panel_data.mean([x.get('support_score') for x in per.values()])
        b['levels'] = {k: {'strategy': J.consensus([(x['levels'].get(k) or {}).get('strategy')
                                                    for x in per.values()]),
                           'support': J.consensus([(x['levels'].get(k) or {}).get('support')
                                                   for x in per.values()])}
                       for k in ('d1_partition', 'd2_identity', 'd3_mechanism')}
        sup[panel_data.label_of(p)] = b
    for p in glob.glob(panel_data.artifact_glob(D, 'cot', J.tags()[0])):
        ed = panel_data.episode_dir_of(p); per = panel_data.load_all_judges(ed, 'cot')
        if not per: continue
        b = dict(next(iter(per.values())))
        for fld in ('identity_derivation', 'validation_rigor', 'reasoning_strategy'):
            b[fld] = J.consensus([c.get(fld) for c in per.values()])
        cot[panel_data.label_of(p)] = b
    panel_data.require_loaded(len(v3), D, 'outcome artifacts')
    panel_data.require_loaded(len(sup), D, 'support artifacts')
    panel_data.require_loaded(len(cot), D, 'CoT artifacts')
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
        # EXPOSED denominator, not the arm size. Most lean late-reveal episodes never
        # received a false label (see scripts/g3_exposure.py), and counting them as
        # 'not fooled' produced a p=6e-08 result that was pure artifact.
        g3_all=[l for l in v3 if arm(l) in ('g3a', 'g3b')],
        # Exposed AND scored. An exposed episode whose scorer left a placeholder (verdict "") is
        # not evidence of resistance — it is a missing measurement, and including it in the
        # denominator understates the adoption rate. See audit_integrity AUDIT 2.
        g3_exposed=(_ex := {l for l in exposed_g3(D, [l for l in v3 if arm(l) in ('g3a', 'g3b')])
                            if v3[l].get('cohort_identity_verdict')}),
        fooled=sum(1 for l in _ex if v3[l].get('cohort_identity_verdict') == 'mislead_cohort'),
        n_g3=len(_ex),
        n_g3_arm=sum(1 for l in v3 if arm(l) in ('g3a', 'g3b')),
        ro_per_ep=st.mean(ro) if ro else 0.0)

_lane_counts = [len(glob.glob(panel_data.artifact_glob(d, 'outcome', J.tags()[0])))
                for _, dd_, ld_, _, _ in PAIRS for d in (dd_, ld_)]
N_PER_LANE = max(_lane_counts) if _lane_counts else 0
panel_data.require_data(sum(_lane_counts), 'scored episodes', runs_config.SOURCE)
JUDGE_NAME = panel_judges.panel_judge_label([d for _, d, l, _, _ in PAIRS])

DATA = {lab: {'detailed': metrics(dd), 'lean': metrics(ld), 'color': col, 'tier': tier}
        for lab, dd, ld, col, tier in PAIRS}

# ---- inter-judge robustness: three judge FAMILIES, one pass each -------------------------
# The whole explore/exploit axis rides on ONE label (identity_derivation). This re-reads the same
# G2 traces under every family on the panel.
#
# This block used to compare judge A against a single judge B, loading both by the pre-reorg flat
# filenames (`{D}/g2_*/*_cotsummary_j2.json`). Under scoring/<judge>/ that glob matches nothing,
# so `n_both` was 0 for every arm, `JP_ANY` was False, and the ENTIRE section — the one that
# answers "does this survive a different judge?" — was dropped from the report with no message.
# It now reads the panel and compares all three families.
JFIELDS = ['identity_derivation', 'validation_rigor', 'codebook_response']
JTAGS = J.tags()


def _load_tag(D, tag):
    """{label: summary} for the G2 episodes this judge family has scored."""
    out = {}
    for p in glob.glob(panel_data.artifact_glob(D, 'cot', tag)):
        lab = panel_data.label_of(p)
        if not lab.startswith('g2_'):
            continue
        try:
            out[lab] = json.load(open(p))
        except Exception:
            continue
    return out


def _der(summaries):
    """fraction 'data-derived' over a list of summaries (the explore/exploit proxy)."""
    if not summaries:
        return None
    return sum(1 for x in summaries if x.get('identity_derivation') == 'data-derived') / len(summaries)


def judge_panel(D):
    per = {t: _load_tag(D, t) for t in JTAGS}
    # Compare on the episodes EVERY family scored. A family-specific subset would confound a
    # judge effect with a cohort effect: G2 artifacts are written cohort-alphabetically, so a
    # partial lane over-represents BRCA/LIHC/LUAD and omits OV, the difficulty floor.
    common = sorted(set.intersection(*[set(v) for v in per.values()])) if all(per.values()) else []
    n_any = max((len(v) for v in per.values()), default=0)
    unan, pair = {}, {}
    for f in JFIELDS:
        unan[f] = (sum(1 for l in common if len({per[t][l].get(f) for t in JTAGS}) == 1), len(common))
        pair[f] = {}
        for i, a in enumerate(JTAGS):
            for b in JTAGS[i + 1:]:
                pair[f][(a, b)] = sum(1 for l in common if per[a][l].get(f) == per[b][l].get(f))
    flips = Counter()
    for l in common:
        vs = [per[t][l].get('identity_derivation') for t in JTAGS]
        for i in range(len(vs)):
            for k in range(i + 1, len(vs)):
                if vs[i] != vs[k]:
                    flips[tuple(sorted((str(vs[i]), str(vs[k]))))] += 1
    return dict(n_any=n_any, n_common=len(common), unan=unan, pair=pair, flips=flips,
                der={t: _der([per[t][l] for l in common]) for t in JTAGS},
                complete=bool(common) and all(len(v) == len(common) for v in per.values()))


JP = {lab: {'detailed': judge_panel(dd), 'lean': judge_panel(ld)} for lab, dd, ld, _, _ in PAIRS}
JP_ANY = any(JP[m][p]['n_common'] for m in JP for p in ('detailed', 'lean'))
if not JP_ANY:
    sys.exit("no G2 episode was scored by all three judge families — refusing to emit the ablation "
             "report with the inter-judge robustness section silently missing")

# agreement table
j_rows = ""
for lab in DATA:
    for prompt in ('detailed', 'lean'):
        j = JP[lab][prompt]
        if not j['n_common']:
            j_rows += (f'<tr><td class="grp" style="color:{DATA[lab]["color"]}">{lab}</td><td>{prompt}</td>'
                       f'<td class="num mut" colspan="4">no episode scored by all three families</td></tr>')
            continue
        cov = f"{j['n_common']}/{j['n_any']}" + ('' if j['complete'] else ' <span class="part">partial</span>')
        cells = ""
        for f in JFIELDS:
            a, n = j['unan'][f]
            cls = 'good' if a / n >= 0.8 else ('bad' if a / n < 0.6 else 'mut')
            cells += f'<td class="num {cls}">{a}/{n}<span class="sub">{a/n*100:.0f}% unanimous</span></td>'
        j_rows += (f'<tr><td class="grp" style="color:{DATA[lab]["color"]}">{lab}</td><td>{prompt}</td>'
                   f'<td class="num">{cov}</td>{cells}</tr>')

# does the lean-detailed derivation delta SURVIVE under every family?
def _fmt_d(x):
    return '&mdash;' if x is None else f"{x*100:+.1f}"


surv_rows = ""
surv_verdicts = []
for lab in DATA:
    d, l = JP[lab]['detailed'], JP[lab]['lean']
    deltas = {t: (l['der'][t] - d['der'][t]) if (l['der'][t] is not None and d['der'][t] is not None)
              else None for t in JTAGS}
    vals = [v for v in deltas.values() if v is not None]
    if len(vals) < len(JTAGS):
        verdict, vcls = 'panel incomplete', 'part'
    elif all(abs(v) < 0.05 for v in vals):
        verdict, vcls = 'no effect, all families', 'mut'
    elif len({v > 0 for v in vals}) > 1:
        # A sign flip between families is the finding that matters: the effect is not a property
        # of the episodes, it is a property of who is reading them.
        verdict, vcls = 'SIGN FLIPS across families', 'bad'
    elif max(abs(v) for v in vals) and min(abs(v) for v in vals) >= 0.5 * max(abs(v) for v in vals):
        verdict, vcls = 'holds under all three', 'good'
    else:
        verdict, vcls = 'same sign, magnitude varies', 'part'
    surv_verdicts.append(verdict)
    surv_rows += (f'<tr><td class="grp" style="color:{DATA[lab]["color"]}">{lab}</td>'
                  + "".join(f'<td class="num">{_fmt_d(deltas[t])}</td>' for t in JTAGS)
                  + f'<td class="{vcls}">{verdict}</td></tr>')

# the most common cross-family confusion, pooled (is disagreement adjacent or sign-flipping?)
pool = Counter()
for m in JP:
    for p in ('detailed', 'lean'):
        pool.update(JP[m][p]['flips'])
# ADJACENT = the two families agree on the direction of the evidence and differ on where to put
# the threshold (one says `mixed` where the other commits). Everything else is POLAR: they read
# the same trace as different behaviours. `data-derived` vs `not-established` is polar — one
# family found a data-grounded identity derivation where another found no identity claim at all.
ADJ = {tuple(sorted(x)) for x in
       (('mixed', 'data-derived'), ('mixed', 'recalled-prior'), ('mixed', 'not-established'))}
n_flip = sum(pool.values())
n_adj = sum(v for k, v in pool.items() if k in ADJ)
n_pol = n_flip - n_adj
# The prose used to assert that disagreement is "largely adjacent". That is a claim about the
# data, so read it off the data instead of asserting it.
adj_frac = n_adj / n_flip if n_flip else 0.0
adj_txt = (
    "Most disagreement is <b>adjacent</b>: the families agree on the <i>direction</i> of the "
    "evidence and differ on where to put the threshold. That degrades the precision of any single "
    "episode's label but largely preserves an aggregate delta."
    if adj_frac >= 0.6 else
    f"<b>Fewer than half are adjacent.</b> The remaining <b>{n_pol}</b> are <b>polar</b> &mdash; "
    "the families read the same trace as different behaviours, not as the same behaviour at "
    "different thresholds. The largest single bucket is <code>data-derived</code> vs "
    "<code>not-established</code>: one family found a data-grounded identity derivation where "
    "another found no identity claim at all. This is not threshold noise, and an aggregate delta "
    "built on this label inherits it.")
flip_txt = "  &middot;  ".join(f"{a} vs {b} &times;{n}" for (a, b), n in pool.most_common(5)) or "none"
j_all_complete = all(JP[m][p]['complete'] for m in JP for p in ('detailed', 'lean'))
jth = "".join('<th class="num">&Delta; ' + t + '</th>' for t in JTAGS)
n_pairs_judged = sum(JP[m][p]['n_common'] for m in JP for p in ('detailed', 'lean')) * 3

# ---- metric rows: (key, label, fmt, lower_is_better) ----
ROWS = [
    ('out_hon', 'Outcome (honest mean)', lambda v: f"{v:.3f}", None),
    ('out_g2', '— outcome G2 (hardest honest)', lambda v: f"{v:.3f}", None),
    ('support', 'Support / grounding (/5)', lambda v: f"{v:.2f}", False),
    ('d2_unsup', 'D2 identity unsupported', lambda v: f"{v:.0%}", True),
    ('g2_derived', 'CoT: G2 identity DERIVED', lambda v: f"{v:.0%}", False),
    ('g2_recalled', 'CoT: G2 identity RECALLED', lambda v: f"{v:.0%}", True),
    ('rigor_high', 'CoT: validation rigor high', lambda v: f"{v:.0%}", False),
    ('fooled', 'G3 fooled (of exposed)', None, True),   # rendered by fooled_cell — denominator varies by wave
    ('ro_per_ep', 'record_observation / ep', lambda v: f"{v:.1f}", None),
]

def delta_cell(key, det, lean, fmt, lower_better):
    d = lean - det
    arrow = "→" if abs(d) < 1e-9 else ("↑" if d > 0 else "↓")
    if lower_better is None or abs(d) < 0.005:
        cls = "mut"
    else:
        good = (d < 0) if lower_better else (d > 0)
        cls = "good" if good else "bad"
    return f'<td class="num">{fmt(det)}</td><td class="num">{fmt(lean)}</td><td class="num {cls}">{arrow}{fmt(abs(d))}</td>'


def fooled_rate(m):
    """G3 fooled (of exposed) as a RATE. n_g3 is not a constant across run sets."""
    n = m.get('n_g3', 0)
    return (m['fooled'] / n) if n else 0.0


def fooled_cell(det, lean):
    """Fooled count over the denominator each wave ACTUALLY has.

    The denominator was hardcoded to 12 — the pilot's G3 count (2 cohort pairs x 3 seeds). The
    clean run defaults to 8 seeds and so has 32, meaning a genuine 24/32 rendered as "24/12".
    Anything at or below 12 still looks entirely plausible while under-reporting the fooled rate
    by ~2.7x, and this row carries one of the headline findings. Rates are compared rather than
    counts because the two waves are not required to have equal n.
    """
    dn, ln_ = det.get('n_g3', 0), lean.get('n_g3', 0)
    dr, lr = fooled_rate(det), fooled_rate(lean)
    d = lr - dr
    arrow = "→" if abs(d) < 1e-9 else ("↑" if d > 0 else "↓")
    cls = "mut" if abs(d) < 0.005 else ("good" if d < 0 else "bad")   # fooled: lower is better
    return (f'<td class="num">{int(det["fooled"])}/{dn} ({dr:.0%})</td>'
            f'<td class="num">{int(lean["fooled"])}/{ln_} ({lr:.0%})</td>'
            f'<td class="num {cls}">{arrow}{abs(d):.0%}</td>')

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
        cell = fooled_cell(det, lean) if key == 'fooled' else delta_cell(key, det[key], lean[key], fmt, lb)
        body += f'<tr><td>{name}</td>{cell}</tr>'
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
# RATES, not counts. The staged-prompt finding rides on this comparison, and counts are only
# comparable when both waves have the same n_g3 — true in the pilot (12 v 12), not guaranteed
# afterwards. A wave with more G3 episodes would win on raw count while being fooled less often.
fool_up_det = sum(1 for m in DATA if fooled_rate(DATA[m]['detailed']) > fooled_rate(DATA[m]['lean']) + 1e-9)
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

interjudge_section = f"""
<h2>Inter-judge robustness &mdash; does the derivation finding survive a different judge?</h2>
<div class="panel">
<p class="lead">The explore&harr;exploit axis rests on a <b>single categorical label</b>
(<code>identity_derivation</code>) &mdash; and the lean prompt's own "derive from structure alone"
wording could plausibly nudge that label. So every G2 trace was judged independently by
<b>three different model families</b> ({JUDGE_NAME}), one pass each.
This panel is the foundation for every derivation claim above, not a footnote.</p>
<div class="tblwrap"><table><thead><tr><th>model</th><th>prompt</th>
<th class="num">judged by all three</th>
<th class="num">identity_derivation</th><th class="num">validation_rigor</th>
<th class="num">codebook_response</th></tr></thead>
<tbody>{j_rows}</tbody></table></div>
<p class="lead">Share of episodes where all three families gave the <b>same</b> label.
<code>codebook_response</code> is near-deterministic (an observable action) and its high agreement is
largely a <b>ceiling effect</b> &mdash; the label is almost always <i>annotated-existing</i>, so
agreeing on it costs nothing. <code>identity_derivation</code> is the <b>interpretive</b> one and
agrees least, which is exactly why the delta table below matters more than any single-family
percentage.</p>
</div>

<div class="panel">
<h3>Does the lean&minus;detailed derivation delta survive?</h3>
<div class="tblwrap"><table><thead><tr><th>model</th>
{jth}
<th>verdict</th></tr></thead>
<tbody>{surv_rows}</tbody></table></div>
<p class="lead">&Delta; = (lean &minus; detailed) percentage points of G2 episodes labelled
<b>data-derived</b>, computed separately under each judge family on the <i>same</i> episode set.
"Holds under all three" = same sign in every column and the smallest magnitude at least half the
largest. A <b>sign flip</b> between columns would mean the effect is a property of who is reading
the traces, not of the traces.</p>
</div>

<div class="panel">
<h3>Where the families disagree</h3>
<p class="lead">Pooled G2 <code>identity_derivation</code> disagreements across the three pairwise
comparisons ({n_flip} disagreeing pairs of {n_pairs_judged} judged pairs):</p>
<p><code>{flip_txt}</code></p>
<p class="lead"><b>{n_adj}/{n_flip}</b> disagreements are <b>adjacent</b> (one family says
<i>mixed</i> where another commits). {adj_txt}<br>
<b>What this does and does not establish.</b> Each family judged each episode <b>once</b>. A
disagreement therefore mixes genuine cross-family bias with ordinary per-judge stochasticity, and
this design cannot separate them &mdash; agreement here does <i>not</i> bound judge noise, because
no family was asked the same question twice. Separating the two needs a second pass from at least
one family.
{"" if j_all_complete else '<br><b class="part">Some episodes are missing from at least one family &mdash; every number in this panel is computed on the intersection and is provisional until the panel is complete.</b>'}</p>
</div>"""

html = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>TCGA Benchmark — Instruction Ablation (Detailed vs Lean)</title><style>{CSS}</style></head><body><div class="wrap">
<h1>TCGA Agent Benchmark — Instruction Ablation</h1>
<div class="meta">Detailed (staged Stage 0–5 prompt) vs Lean ("no prescribed procedure") · {len(DATA)} models × 2 prompts · {N_PER_LANE} episodes each · same model/cohorts/seeds/budget — only the prompt differs · judged by the neutral three-family panel {JUDGE_NAME}, one pass each; every artifact (CoT, support, outcome) records its judge</div>

<h2>Headline</h2>
<div class="panel">
<div class="kfind"><div class="ix">⚖️</div><div><b>Outcome is prompt-invariant for the flagships</b> (mean |lean−detailed| = <b>{flag_shift:.3f}</b> for {", ".join(flag)}){flash_line}</div></div>
<div class="kfind"><div class="ix">🎣</div><div><b>Once actually exposed, nearly every episode adopts the planted label.</b> Denominator is EXPOSED episodes, not arm size (see scripts/g3_exposure.py). On that denominator the prompt gap largely disappears — detailed is higher in only <b>{fool_up_det}/{len(DATA)}</b> models, and the earlier claim that the scaffold walks agents into the false frame is <b>retracted</b> (it was an exposure artifact).</div></div>
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
(1) <b>n = 21/arm</b> on honest arms, <b>32/arm on G3</b> — but G3 rates use the <b>exposed</b> denominator, which is far smaller on the lean wave (19/16/15 of 32). Deltas within a few points are noise.<br>
(2) <b>Two scorers, partly divergent</b> — CoT "derived" (behaviour) vs support "unsupported" (documented evidence) can move in opposite directions; that divergence is the finding, but neither is ground truth.<br>
(3) <b>Gemini 2.5 Pro is a generation behind</b>, not a lower tier — the clean run is three flagships. A Gemini delta is confounded with model generation. It also returned <b>zero record_observation</b> in 3 lean episodes, so it sometimes supplied no process evidence at all.<br>
(4) <b>identity_derivation is a majority across three judge FAMILIES; 98/570 episodes reach no majority and are excluded</b> — the lean prompt's own "derive from structure alone" wording may nudge it toward "data-derived". {"Second-judge coverage is COMPLETE; read the survival verdicts above and quote only deltas marked <i>holds</i>." if j_all_complete else "<b class='part'>Second-judge coverage is still INCOMPLETE</b> — treat every derivation magnitude as directional-pending-robustness until it finishes."}
</div>

<div class="foot">Source: <code>{runs_config.SOURCE}</code>. Outcome from <code>scoring/&lt;judge&gt;/v3scores.json</code>, grounding from <code>supportscores.json</code>, reasoning from <code>cotsummary.json</code> (3-family neutral panel: {'/'.join(J.tags())}); record_observation counts from the raw trace. Generated by <code>scripts/gen_ablation_report.py</code>. Charts: Chart.js (cdnjs).</div>
</div>
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.js"></script>
<script>{JS}</script>
</body></html>"""

open(OUT, 'w').write(html)
print("wrote", OUT, len(html), "bytes")
