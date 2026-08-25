#!/usr/bin/env python3
"""Episode-level deep dive: what the agent actually DID, turn by turn, across all 570 runs.

`cot_deepdive.py` answers two hypothesis tests (H1 outcome-vs-strategy, H2 strategy-vs-robustness)
and nothing else. It is a statistics file. This is the descriptive layer underneath it: for every
episode, the tool sequence, the data it opened, the methods it ran, the hypotheses it held and
where it changed them.

WHAT IS MEASURED HERE IS DETERMINISTIC. Nothing on this page comes from an LLM judge. Every field
is parsed from the episode trace — tool_use blocks, run_code source, and the agent's own
`record_observation` payloads. That matters because the judge-derived layer has one pass per
family and a known confound (see EVALUATION_ARCHITECTURE.md §10); this layer has neither, so it
can be quoted without that caveat. The ONE judge number carried along is `num_pivots`, kept
strictly as a cross-check against the deterministic pivot count, never as a substitute.

SECTIONS
  1 Tool flow        the call sequence, its shape, code errors, where turns go
  2 Data touched     which modalities the code opened, and how early
  3 Methods          clustering / validation / survival / enrichment vocabulary, from source
  4 Thought flow     confidence trajectory, evidence and alternatives per checkpoint
  5 Pivots           hypothesis change measured on the text, vs the judge's count
  6 Per-episode      every run, sortable, with its own sequence

Usage:
  BDG_RUNS=clean python scripts/cot_flow.py
      -> manuscript/figures/cot_flow.json     (aggregates + one record per episode)
      -> results/tcga/reports/FLOW_REPORT.html
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

OUT_JSON = 'manuscript/figures/cot_flow.json'
OUT_HTML = 'results/tcga/reports/FLOW_REPORT.html'

# ---------------------------------------------------------------------------------------------
# VOCABULARY. Every pattern below was counted against a 60-episode sample of the real run_code
# source before being written down (1,414 code blocks, 2.6M chars) — none of it is guessed, and a
# term that did not appear is not listed. Word boundaries are load-bearing: a bare "ari" matched
# 2,189 times, almost all of it inside "variance"/"variable", and a bare "ora" matches "more a".
# ---------------------------------------------------------------------------------------------
MODALITIES = {
    'expression':  r'\bexpression\b',
    'mutation':    r'\bmutation\b',
    'cna':         r'\bcna\b|\bcopy[_ ]?number\b',
    'methylation': r'\bmethylation\b',
    'metadata':    r'\bmetadata\b|\bclinical\b',
    'codebook':    r'\bcodebook\b|\bgene_map\b',
}
METHODS = {
    'kmeans':        r'\bk-?means\b|\bKMeans\b',
    'nmf':           r'\bNMF\b|\bnon_?negative_?matrix\b',
    'hierarchical':  r'\bagglomerative\b|\bhierarchical\b|\blinkage\b|\bdendrogram\b',
    'gmm':           r'\bGMM\b|\bGaussianMixture\b',
    'spectral':      r'\bSpectralClustering\b|\bspectral_?cluster',
    'consensus':     r'\bconsensus[_ ]?clust',
    'snf':           r'\bSNF\b|\bsimilarity[_ ]?network[_ ]?fusion\b',
    'silhouette':    r'\bsilhouette\b',
    'bootstrap':     r'\bbootstrap\b',
    'ari':           r'\badjusted_rand\b|\badjusted[ _]rand\b|\bARI\b',
    'calinski':      r'\bcalinski\b|\bdavies[_ ]?bouldin\b',
    'permutation':   r'\bpermutation[_ ]?test\b|\bpermutation_?importance\b',
    'crossval':      r'\bcross_?val\b|\bStratifiedKFold\b|\bKFold\b',
    'cox':           r'\bCoxPH\b|\bCoxPHFitter\b|\bcoxph\b',
    'logrank':       r'\blogrank\b|\blog[_ ]rank\b|\bmultivariate_logrank\b',
    'kaplanmeier':   r'\bKaplanMeier\b|\bkaplan[_ ]meier\b|\bKMFitter\b',
    'enrichment':    r'\benrich\w*\b|\bGSEA\b|\bhypergeom\w*\b|\bfisher_exact\b|\bMSigDB\b|\.gmt\b',
    'pca':           r'\bPCA\b',
    'umap_tsne':     r'\bUMAP\b|\bt-?SNE\b|\bTSNE\b',
    'hvg':           r'\bHVG\b|\bhighly_?variable\b',
}
METHOD_FAMILY = {
    'kmeans': 'clustering', 'nmf': 'clustering', 'hierarchical': 'clustering', 'gmm': 'clustering',
    'spectral': 'clustering', 'consensus': 'clustering', 'snf': 'clustering',
    'silhouette': 'validation', 'bootstrap': 'validation', 'ari': 'validation',
    'calinski': 'validation', 'permutation': 'validation', 'crossval': 'validation',
    'cox': 'survival', 'logrank': 'survival', 'kaplanmeier': 'survival',
    'enrichment': 'enrichment',
    'pca': 'reduction', 'umap_tsne': 'reduction', 'hvg': 'reduction',
}
MOD_RE = {k: re.compile(v, re.I) for k, v in MODALITIES.items()}
MET_RE = {k: re.compile(v, re.I) for k, v in METHODS.items()}

# A modality is PROBED whenever its name appears anywhere in the source, and USED only when it
# appears outside an availability check. Every episode's orientation block opens with
#     print('methylation_available', methylation is not None)
# so a plain name match reported 100% coverage of every modality in every lane — six columns of
# 100%, which is not a finding, it is the boilerplate. Strip the probe lines first.
_PROBE_LINE = re.compile(
    r'is\s+(?:not\s+)?None'          # `methylation is not None`
    r'|_available'                   # `print('cna_available', ...)`
    r'|\.shape\s*\)?\s*$'            # `print('mutation', mutation.shape)`
    r'|^\s*#',                       # comment-only line
    re.I | re.M)

# A NAME-PAIRED ENUMERATION is still a sweep: `for name, df in [('mutation', mutation),
# ('methylation', methylation), ('cna', cna)]:` walks the modalities to see which exist. Without
# this, that single loop header credited GPT with "using" methylation in 86 episodes — a modality
# that does not exist in this benchmark at all (there is no methylation file for any TCGA cohort;
# `methylation` is always None), producing a clean 90%-vs-4% model difference out of dead code.
_ENUM_PAIR = re.compile(r"""['"](\w+)['"]\s*,\s*\1\b""", re.I)


def _analysis_lines(src, mod=None):
    """Source with availability probes, sweeps and comments removed — what the code DOES.

    `mod` scopes the enumeration filter: a line is dropped only if THIS modality appears in it
    as a name-paired enumeration entry, so a genuine join like `expression.join(metadata)` is
    still credited to both.
    """
    out = []
    for l in src.split('\n'):
        if not l.strip() or _PROBE_LINE.search(l):
            continue
        if mod and any(g.lower() == mod for g in _ENUM_PAIR.findall(l)):
            continue
        out.append(l)
    return '\n'.join(out)

# Every run_code call carries its own hypothesis line. This is a SECOND, denser hypothesis trail
# than the record_observation checkpoints, and it is the one the judge also reads — which is why
# the judge's num_pivots can legitimately exceed (checkpoints - 1). Counting pivots only over
# checkpoints and then calling the judge wrong would have been comparing two different substrates.
CURHYP_PAT = re.compile(r'#\s*CURRENT_HYPOTHESIS:\s*(.+)', re.I)

TOOL_CHAR = {'run_code': 'C', 'record_observation': 'R', 'submit_discovery': 'S'}
CONF_VAL = {'low': 0.0, 'medium': 0.5, 'high': 1.0}

# Content words only. Comparing raw hypothesis strings would call every checkpoint a pivot,
# because the agent rewrites the sentence every time even when the claim is unchanged.
_STOP = set("""a an the and or but of to in on for with from by as at is are was were be been being
this that these those it its their there here we our us i my he she they them then than so such
no not only also more most less least very much many few some any all both each other another
which who whom whose what when where why how if while during before after above below between
into through over under again further once do does did doing done has have had having can could
should would may might must will shall now new old same different first second third stage step
cohort dataset data sample samples gene genes cluster clusters group groups subtype subtypes""".split())
_WORD = re.compile(r"[a-z][a-z0-9_-]{2,}")


def content_words(s):
    return {w for w in _WORD.findall((s or '').lower()) if w not in _STOP}


def jaccard(a, b):
    if not a and not b:
        return 1.0
    return len(a & b) / len(a | b) if (a | b) else 1.0


# A pivot is a checkpoint whose hypothesis shares less than this fraction of its content words
# with the previous one. 0.35 was chosen by reading the extremes: pairs above ~0.5 are the same
# claim with new evidence appended; pairs below ~0.25 name different biology. Anything in between
# is genuinely arguable, which is why the judge's own count is reported next to this one rather
# than replaced by it — two independent measures disagreeing is information.
PIVOT_THRESHOLD = 0.35


def episode_json_paths(run):
    """<run>/<episode>/<episode>.json — the harness trace, not a scoring artifact."""
    out = []
    for d in sorted(glob.glob(f'{run}/g*_s*')):
        p = os.path.join(d, os.path.basename(d) + '.json')
        if os.path.isdir(d) and os.path.exists(p):
            out.append(p)
    return out


def arm_of(label):
    a = label.split('_')[0]
    return 'g3' if a.startswith('g3') else a


AVAIL_PAT = re.compile(r'(expression|mutation|methylation|cna)[ _]available[ :]+(True|False)', re.I)


def modality_availability(ep):
    """{modality: True/False} as the HARNESS reported it, read off the tool_result text.

    Needed to interpret the reach-for rates: `methylation` is None in every cohort of this
    benchmark, so an episode that references it is ATTEMPTING an absent matrix, not using one.
    Without this the column reads as coverage and invents an 87%-vs-4% capability difference.
    """
    out = {}
    for m in ep.get('messages') or []:
        c = m.get('content')
        if not isinstance(c, list):
            continue
        for b in c:
            if b.get('type') != 'tool_result':
                continue
            t = b.get('content')
            t = t if isinstance(t, str) else json.dumps(t)
            for mod, val in AVAIL_PAT.findall(t):
                out.setdefault(mod.lower(), val == 'True')
    return out


def res_err(ep):
    """The harness's own execution-error count — an independent check on the text match."""
    return (ep.get('resources') or {}).get('n_exec_errors')


def analyse(path):
    """One episode -> one flat record. Deterministic; no LLM anywhere in this function."""
    ep = json.load(open(path))
    label = os.path.basename(path)[:-5]
    ed = os.path.dirname(path)

    seq, code_src, n_err = [], [], 0
    for m in ep.get('messages') or []:
        c = m.get('content')
        if not isinstance(c, list):
            continue
        for b in c:
            if b.get('type') != 'tool_use':
                continue
            seq.append(b.get('name'))
            if b.get('name') == 'run_code':
                code_src.append((b.get('input') or {}).get('code') or '')

    # Execution errors. There is NO `is_error` flag on these tool_result blocks — checking for
    # one counted zero errors in all 570 episodes while `resources.n_exec_errors` said otherwise,
    # a clean 0.00 column that meant "I looked in the wrong place". The executor prefixes a failed
    # result with "Error:", so match that, and report the harness's own count beside it.
    for m in ep.get('messages') or []:
        c = m.get('content')
        if not isinstance(c, list):
            continue
        for b in c:
            if b.get('type') != 'tool_result':
                continue
            body = b.get('content')
            body = body if isinstance(body, str) else json.dumps(body)
            if body.lstrip().startswith('Error:') or 'Traceback (most recent call last)' in body:
                n_err += 1

    shape = ''.join(TOOL_CHAR.get(t, '?') for t in seq)
    counts = Counter(seq)

    # first call index (1-based, over run_code calls) at which each modality / method appears
    mod_first, met_first, mod_probed = {}, {}, set()
    for i, src in enumerate(code_src, 1):
        analysis = _analysis_lines(src)
        for k, rx in MOD_RE.items():
            if rx.search(src):
                mod_probed.add(k)
            if k not in mod_first and rx.search(_analysis_lines(src, k)):
                mod_first[k] = i
        for k, rx in MET_RE.items():
            if k not in met_first and rx.search(analysis):
                met_first[k] = i

    obs = [o for o in (ep.get('observations') or []) if isinstance(o, dict)]
    confs = [CONF_VAL.get(o.get('confidence')) for o in obs]
    confs = [c for c in confs if c is not None]
    hyps = [o.get('current_hypothesis') or '' for o in obs]
    words = [content_words(h) for h in hyps]

    sims = [jaccard(words[i - 1], words[i]) for i in range(1, len(words))]
    pivots = sum(1 for s in sims if s < PIVOT_THRESHOLD)

    # Wide trail: the same measure over every hypothesis statement in the trace, checkpoints and
    # per-call CURRENT_HYPOTHESIS headers together, in call order. This is comparable to the
    # judge's count; `pivots` above is not.
    hdr = [h.strip() for src in code_src for h in CURHYP_PAT.findall(src)]
    trace_hyps = hyps + hdr
    tw = [content_words(h) for h in trace_hyps]
    tsims = [jaccard(tw[i - 1], tw[i]) for i in range(1, len(tw))]
    pivots_trace = sum(1 for s in tsims if s < PIVOT_THRESHOLD)

    # time-to-high-confidence, normalised to [0,1] over the checkpoint sequence. 1.0 = never
    # reached high (or reached it only at the very end) — an explorer commits late.
    ttc = 1.0
    for i, c in enumerate(confs):
        if c >= 1.0:
            ttc = i / max(len(confs) - 1, 1)
            break

    # judge's own pivot count, panel-averaged. Cross-check only.
    cots = panel_data.load_all_judges(ed, 'cot')
    judge_piv = panel_data.mean([c.get('num_pivots') for c in cots.values()]) if cots else None

    res = ep.get('resources') or {}

    return {
        'label': label, 'arm': arm_of(label), 'cohort': ep.get('cohort'),
        'seed': ep.get('seed'), 'model': ep.get('model'),
        'n_tool_calls': len(seq), 'n_code': counts.get('run_code', 0),
        'n_exec_errors_harness': res_err(ep),
        'n_obs_calls': counts.get('record_observation', 0),
        'submitted': bool(counts.get('submit_discovery', 0)),
        'shape': shape, 'n_code_errors': n_err,
        'n_turns': res.get('n_turns'), 'wall_s': res.get('wall_time_s'),
        'pct_exec': res.get('pct_exec'),
        'modalities': sorted(mod_first), 'modality_first': mod_first,
        'modalities_probed': sorted(mod_probed),
        'modality_available': modality_availability(ep),
        'methods': sorted(met_first), 'method_first': met_first,
        'families': sorted({METHOD_FAMILY[m] for m in met_first}),
        'n_checkpoints': len(obs),
        'conf_first': confs[0] if confs else None,
        'conf_last': confs[-1] if confs else None,
        'conf_rise': (confs[-1] - confs[0]) if len(confs) > 1 else None,
        'ttc': ttc if confs else None,
        'mean_alternatives': st.mean([len(o.get('alternatives_considered') or []) for o in obs]) if obs else None,
        'mean_evidence_for': st.mean([len(o.get('evidence_for') or []) for o in obs]) if obs else None,
        'mean_evidence_against': st.mean([len(o.get('evidence_against') or []) for o in obs]) if obs else None,
        'hypothesis_sims': [round(s, 3) for s in sims],
        'pivots_measured': pivots,
        'n_hypothesis_headers': len(hdr),
        'n_hypothesis_statements': len(trace_hyps),
        'pivots_trace': pivots_trace,
        'pivots_judge': judge_piv,
        'hypotheses': hyps,
    }


def main():
    rows, lanes = [], []
    for model, prompt, run in runs_config.triples():
        paths = episode_json_paths(run)
        panel_data.require_loaded(len(paths), run, 'episode traces')
        for p in paths:
            r = analyse(p)
            r['model'], r['prompt'], r['run'] = model, prompt, run
            rows.append(r)
        lanes.append((model, prompt))
    panel_data.require_data(len(rows), 'episode traces', runs_config.SOURCE)

    def agg(sel):
        R = [r for r in rows if sel(r)]
        if not R:
            return None
        def mean(k):
            v = [r[k] for r in R if r.get(k) is not None]
            return round(st.mean(v), 3) if v else None

        # MEDIANS TOO, and they are not decoration. One episode (g0_ucec_s7) logs 352
        # alternatives_considered entries per checkpoint and another 516 evidence_against
        # entries; those single runs move a whole arm's mean by 2-3x. On means it looks like G0
        # weighs the most alternatives and G3 records the most counter-evidence, and on medians
        # both are FLAT across every arm. Report both so the skew is visible instead of narrated.
        def med(k):
            v = [r[k] for r in R if r.get(k) is not None]
            return round(st.median(v), 3) if v else None
        mods = Counter(m for r in R for m in r['modalities'])
        av_seen, av_true = Counter(), Counter()
        for r in R:
            for k, v in (r.get('modality_available') or {}).items():
                av_seen[k] += 1
                av_true[k] += bool(v)
        fams = Counter(f for r in R for f in r['families'])
        mets = Counter(m for r in R for m in r['methods'])
        return {
            'n': len(R),
            'median': {k: med(k) for k in
                       ('n_code', 'n_checkpoints', 'n_tool_calls', 'n_code_errors',
                        'mean_alternatives', 'mean_evidence_against', 'mean_evidence_for',
                        'pivots_measured', 'pivots_trace', 'conf_rise', 'ttc', 'wall_s')},
            'code_calls': mean('n_code'), 'checkpoints': mean('n_checkpoints'),
            'tool_calls': mean('n_tool_calls'), 'code_errors': mean('n_code_errors'),
            'turns': mean('n_turns'), 'wall_s': mean('wall_s'), 'pct_exec': mean('pct_exec'),
            'conf_rise': mean('conf_rise'), 'ttc': mean('ttc'),
            'alternatives': mean('mean_alternatives'),
            'evidence_for': mean('mean_evidence_for'),
            'evidence_against': mean('mean_evidence_against'),
            'pivots_measured': mean('pivots_measured'), 'pivots_trace': mean('pivots_trace'),
            'pivots_judge': mean('pivots_judge'),
            'hypothesis_statements': mean('n_hypothesis_statements'),
            'never_pivoted': sum(1 for r in R if r['pivots_measured'] == 0),
            'no_submit': sum(1 for r in R if not r['submitted']),
            'modality_rate': {k: round(v / len(R), 3) for k, v in mods.most_common()},
            'modality_available_rate': {k: round(av_true[k] / av_seen[k], 3)
                                        for k in av_seen},
            'modality_available_n': dict(av_seen),
            'family_rate': {k: round(v / len(R), 3) for k, v in fams.most_common()},
            'method_rate': {k: round(v / len(R), 3) for k, v in mets.most_common()},
        }

    stats = {
        'source': runs_config.SOURCE,
        'generator': 'scripts/cot_flow.py',
        'derivation': 'deterministic — parsed from tool_use blocks, run_code source and '
                      'record_observation payloads; no LLM judge except pivots_judge, '
                      'which is a cross-check only',
        'pivot_threshold': PIVOT_THRESHOLD,
        'n_episodes': len(rows),
        'overall': agg(lambda r: True),
        'by_lane': {f'{m} / {p}': agg(lambda r, m=m, p=p: r['model'] == m and r['prompt'] == p)
                    for m, p in lanes},
        'by_arm': {a: agg(lambda r, a=a: r['arm'] == a) for a in ('g0', 'g1', 'g2', 'g3')},
        'by_lane_arm': {f'{m} / {p} / {a}':
                        agg(lambda r, m=m, p=p, a=a: r['model'] == m and r['prompt'] == p and r['arm'] == a)
                        for m, p in lanes for a in ('g0', 'g1', 'g2', 'g3')},
        'episodes': rows,
    }
    os.makedirs(os.path.dirname(OUT_JSON), exist_ok=True)
    json.dump(stats, open(OUT_JSON, 'w'), indent=2)
    print(f'wrote {OUT_JSON}  ({len(rows)} episodes)')

    write_html(stats, rows, lanes)


# =============================================================================================
# report
# =============================================================================================
CSS = """
:root{--bg:#0d1117;--panel:#161b22;--line:#283041;--ink:#e6edf3;--mut:#9aa7b4;--acc:#58a6ff;
--good:#3fb950;--warn:#d29922;--bad:#f85149}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);
font:15px/1.6 -apple-system,Segoe UI,Roboto,Arial,sans-serif;padding:30px}
.wrap{max-width:1180px;margin:0 auto}h1{font-size:24px;margin:0 0 4px}
h2{font-size:18px;margin:30px 0 8px;border-left:3px solid var(--acc);padding-left:11px}
.meta{color:var(--mut);font-size:13px;margin-bottom:10px}
.lead{color:var(--mut);font-size:12.5px;margin:8px 0 0}
.panel{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:15px 18px;margin:12px 0}
table{border-collapse:collapse;width:100%;font-size:13px}
th,td{padding:6px 9px;border-bottom:1px solid var(--line);text-align:left}
th{color:var(--mut);font-weight:600;font-size:11.5px}
td.num,th.num{text-align:right;font-variant-numeric:tabular-nums}
.grp{font-weight:700}.mut{color:var(--mut)}.good{color:var(--good)}.bad{color:var(--bad)}
.tblwrap{overflow-x:auto}
code{background:#0b1220;padding:1px 5px;border-radius:4px;font-size:12px}
.seq{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:11px;letter-spacing:1px}
.seq .c{color:var(--acc)}.seq .r{color:var(--good)}.seq .s{color:var(--warn)}
.bar{height:9px;background:#0b1220;border-radius:5px;overflow:hidden;display:flex;min-width:80px}
.bar div{height:100%}
.warnbox{background:#2a2410;border:1px solid #5c4a12;border-radius:8px;padding:13px 16px;
margin:12px 0;color:#e8d48a;font-size:12.5px}
.sub{color:var(--mut);font-size:10.5px;display:block}
details{margin:8px 0}summary{cursor:pointer;color:var(--acc);font-size:13px}
.foot{color:var(--mut);font-size:11.5px;margin-top:26px;border-top:1px solid var(--line);padding-top:12px}
"""


def esc(s):
    return H.escape(str(s if s is not None else ''))


def fmt(v, n=2):
    return '&mdash;' if v is None else f'{v:.{n}f}'


def seq_html(shape, limit=60):
    out = ''
    for ch in shape[:limit]:
        cls = {'C': 'c', 'R': 'r', 'S': 's'}.get(ch, '')
        out += f"<span class='{cls}'>{ch}</span>"
    return f"<span class='seq'>{out}{'&hellip;' if len(shape) > limit else ''}</span>"


def rate_bar(d, keys, colors):
    segs = ''
    for k, c in zip(keys, colors):
        v = d.get(k, 0)
        if v:
            segs += f"<div style='width:{v*100:.0f}%;background:{c}' title='{esc(k)}: {v:.0%}'></div>"
    return f"<div class='bar'>{segs}</div>"


def write_html(stats, rows, lanes):
    lane_rows = ''
    for m, p in lanes:
        a = stats['by_lane'][f'{m} / {p}']
        lane_rows += (
            f"<tr><td class='grp'>{esc(m)}</td><td>{esc(p)}</td><td class='num'>{a['n']}</td>"
            f"<td class='num'>{fmt(a['code_calls'],1)}</td>"
            f"<td class='num'>{fmt(a['checkpoints'],1)}</td>"
            f"<td class='num'>{fmt(a['code_errors'],2)}</td>"
            f"<td class='num'>{fmt(a['turns'],1)}</td>"
            f"<td class='num'>{fmt(a['wall_s'],0)}s</td>"
            f"<td class='num'>{fmt(a['pct_exec'],0)}%</td></tr>")

    arm_rows = ''
    for arm in ('g0', 'g1', 'g2', 'g3'):
        a = stats['by_arm'][arm]
        if not a:
            continue
        arm_rows += (
            f"<tr><td class='grp'>{arm}</td><td class='num'>{a['n']}</td>"
            f"<td class='num'>{fmt(a['code_calls'],1)}</td>"
            f"<td class='num'>{fmt(a['checkpoints'],1)}</td>"
            f"<td class='num'>{fmt(a['conf_rise'],2)}</td>"
            f"<td class='num'>{fmt(a['ttc'],2)}</td>"
            f"<td class='num'>{fmt(a['alternatives'],1)}</td>"
            f"<td class='num'>{fmt(a['evidence_against'],1)}</td>"
            f"<td class='num'>{fmt(a['pivots_measured'],2)}</td></tr>")

    MODS = list(MODALITIES)
    # Availability as the harness reported it, pooled over every episode that printed a probe.
    av_true, av_seen = Counter(), Counter()
    for r in rows:
        for k, v in (r.get('modality_available') or {}).items():
            av_seen[k] += 1
            av_true[k] += bool(v)
    avail_cells = ''
    for k in MODS:
        if not av_seen.get(k):
            avail_cells += "<td class='num mut' title='harness never printed a probe for this'>n/r</td>"
            continue
        frac = av_true[k] / av_seen[k]
        cls = 'good' if frac > 0.5 else 'bad'
        avail_cells += (f"<td class='num {cls}' title='{av_true[k]}/{av_seen[k]} episodes that "
                        f"printed a probe'>{frac:.0%}</td>")
    _mrate = {m: stats['by_lane'][f'{m} / {p}']['modality_rate'].get('methylation', 0)
              for m, p in lanes}
    _mhi = max(_mrate.values()) if _mrate else 0
    _mlo = min(_mrate.values()) if _mrate else 0
    if av_seen.get('methylation') and not av_true.get('methylation'):
        meth_txt = (
            f"<b>Methylation is absent from every cohort in this benchmark</b> &mdash; the harness "
            f"reports it unavailable in {av_seen['methylation']}/{av_seen['methylation']} of the "
            f"episodes that probed, and there is no methylation file under <code>data/tcga/</code>. "
            f"So this column is not coverage; it is the rate at which a lane writes analysis "
            f"against a matrix that is <code>None</code>, which spans "
            f"<b>{_mlo:.0%}&ndash;{_mhi:.0%}</b> across lanes and lands in the code-error column "
            f"in &sect;1. Reading it as a capability difference would invent one.")
    else:
        meth_txt = ("Availability was not uniformly reported, so no absent-modality claim is made "
                    "here.")
    mod_rows = ''
    for m, p in lanes:
        a = stats['by_lane'][f'{m} / {p}']
        cells = ''
        for k in MODS:
            v = a['modality_rate'].get(k, 0)
            cls = 'good' if v >= 0.9 else ('bad' if v < 0.25 else '')
            cells += f"<td class='num {cls}'>{v:.0%}</td>"
        mod_rows += f"<tr><td class='grp'>{esc(m)}</td><td>{esc(p)}</td>{cells}</tr>"

    FAMS = ['clustering', 'validation', 'survival', 'enrichment', 'reduction']
    fam_rows = ''
    for m, p in lanes:
        a = stats['by_lane'][f'{m} / {p}']
        cells = ''.join(f"<td class='num'>{a['family_rate'].get(k,0):.0%}</td>" for k in FAMS)
        top = ', '.join(f"{k} {v:.0%}" for k, v in list(a['method_rate'].items())[:4])
        fam_rows += (f"<tr><td class='grp'>{esc(m)}</td><td>{esc(p)}</td>{cells}"
                     f"<td class='mut'>{esc(top)}</td></tr>")

    piv_rows = ''
    for m, p in lanes:
        a = stats['by_lane'][f'{m} / {p}']
        piv_rows += (
            f"<tr><td class='grp'>{esc(m)}</td><td>{esc(p)}</td>"
            f"<td class='num'>{fmt(a['pivots_measured'],2)}</td>"
            f"<td class='num'>{fmt(a['pivots_trace'],2)}</td>"
            f"<td class='num'>{fmt(a['pivots_judge'],2)}</td>"
            f"<td class='num'>{fmt(a['hypothesis_statements'],1)}</td>"
            f"<td class='num'>{a['never_pivoted']}/{a['n']}</td></tr>")

    # correlation between the two pivot measures — the honest way to report agreement
    def _pearson(key):
        P = [(r[key], r['pivots_judge']) for r in rows
             if r['pivots_judge'] is not None and r.get(key) is not None]
        if len(P) < 3:
            return None, 0
        xs, ys = zip(*P)
        mx, my = st.mean(xs), st.mean(ys)
        num = sum((x - mx) * (y - my) for x, y in P)
        den = (sum((x - mx) ** 2 for x in xs) * sum((y - my) ** 2 for y in ys)) ** 0.5
        return (num / den if den else 0.0), len(P)

    r_chk, n_chk = _pearson('pivots_measured')
    r_tr, _ = _pearson('pivots_trace')
    n_impossible = sum(1 for r in rows if r['pivots_judge'] is not None
                       and r['n_checkpoints'] > 0
                       and r['pivots_judge'] > r['n_checkpoints'] - 1)
    if r_chk is None:
        piv_note = "Too few paired episodes to correlate the pivot measures."
    else:
        piv_note = (
            f"<b>The three columns do not measure the same thing, and the numbers say so.</b> "
            f"Against the judge's count, the checkpoint measure correlates at "
            f"Pearson <b>r = {r_chk:.2f}</b> and the whole-trace measure at <b>r = {r_tr:.2f}</b> "
            f"across {n_chk} episodes &mdash; both weak, and the trace measure runs an order of "
            f"magnitude larger in absolute terms (Sonnet ~40 vs the judge's ~3). "
            f"In <b>{n_impossible}/{n_chk}</b> episodes the judge reports more pivots than there "
            f"are checkpoint transitions, which is <i>not</i> an error: the judge reads the whole "
            f"trace, and its schema asks only for a &ldquo;count of hypothesis "
            f"revisions/pivots&rdquo; with no substrate named. It is making a semantic judgement "
            f"about which revisions are <i>major</i>, and neither mechanical count reproduces it. "
            f"<b>Use the checkpoint column as the process measure and do not treat the judge's "
            f"number as interchangeable with it.</b>")

    ep_rows = ''
    for r in sorted(rows, key=lambda x: (x['model'], x['prompt'], x['label'])):
        ep_rows += (
            f"<tr><td class='mut'>{esc(r['model'])}</td><td class='mut'>{esc(r['prompt'])}</td>"
            f"<td><code>{esc(r['label'])}</code></td>"
            f"<td>{seq_html(r['shape'])}</td>"
            f"<td class='num'>{r['n_code']}</td><td class='num'>{r['n_checkpoints']}</td>"
            f"<td class='num{' bad' if r['n_code_errors'] else ''}'>{r['n_code_errors']}</td>"
            f"<td class='num'>{r['pivots_measured']}</td>"
            f"<td class='mut'>{esc(', '.join(r['families']))}</td></tr>")

    o = stats['overall']
    no_sub = sum(1 for r in rows if not r['submitted'])
    zero_obs = sum(1 for r in rows if r['n_checkpoints'] == 0)
    html = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>TCGA Benchmark — Episode Flow Deep Dive</title><style>{CSS}</style></head>
<body><div class="wrap">
<h1>Episode flow &mdash; what the agent actually did</h1>
<div class="meta">{stats['n_episodes']} episodes &middot; {esc(stats['source'])} &middot;
generated by <code>scripts/cot_flow.py</code></div>

<div class="warnbox"><b>Everything on this page is deterministic.</b> It is parsed from the episode
trace &mdash; <code>tool_use</code> blocks, <code>run_code</code> source, and the agent's own
<code>record_observation</code> payloads. <b>No LLM judge produced any number here</b>, with one
exception that is labelled where it appears: the judge's <code>num_pivots</code>, carried only as a
cross-check against the text-measured count. So unlike the judge-derived layer, nothing here
inherits the one-pass-per-family confound.<br>
<b>What it is not.</b> These are process measures, not quality measures. Running more methods is
not doing better science, and a pivot is not necessarily an improvement &mdash; §5 exists to show
the distribution, not to rank the models.</div>

<h2>1 &middot; Tool flow</h2>
<div class="panel"><div class="tblwrap"><table>
<thead><tr><th>model</th><th>prompt</th><th class="num">eps</th>
<th class="num">run_code<span class="sub">per episode</span></th>
<th class="num">checkpoints<span class="sub">record_observation</span></th>
<th class="num">code errors</th><th class="num">turns</th>
<th class="num">wall</th><th class="num">% in exec</th></tr></thead>
<tbody>{lane_rows}</tbody></table></div>
<p class="lead">One row per lane. <b>run_code</b> is the work; <b>checkpoints</b> is the
self-reported reasoning trail the judges read. The ratio between them is the thing to look at
&mdash; a lane with many executions and few checkpoints is doing analysis it never narrates, and
the judge grades the narration.
{f'<br><b class="bad">{zero_obs} episode(s) logged ZERO checkpoints</b> and are graded on the WHY headers and submission alone (see <code>check_judge_symmetry</code>).' if zero_obs else ''}
{f'<br><b class="bad">{no_sub} episode(s) never called submit_discovery.</b>' if no_sub else ''}
</p></div>

<h2>2 &middot; Data the code reached for</h2>
<div class="panel"><div class="tblwrap"><table>
<thead><tr><th>model</th><th>prompt</th>
{''.join(f'<th class="num">{k}</th>' for k in MODS)}</tr></thead>
<tbody>{mod_rows}
<tr><td class="grp mut" colspan="2">present in the data</td>{avail_cells}</tr>
</tbody></table></div>
<p class="lead">Share of episodes whose <code>run_code</code> <b>reaches for</b> each modality in a
line that is not an availability probe or a name-paired sweep. This is what the agent tried, not
what it got: the last row is what the harness actually provides.
<br><b>Read the methylation column against that row.</b> {meth_txt}</p></div>

<h2>3 &middot; Methods</h2>
<div class="panel"><div class="tblwrap"><table>
<thead><tr><th>model</th><th>prompt</th>
{''.join(f'<th class="num">{k}</th>' for k in FAMS)}<th>most-used specific methods</th></tr></thead>
<tbody>{fam_rows}</tbody></table></div>
<p class="lead">Share of episodes using each method family at least once. The vocabulary was built
by counting a 60-episode sample of real source first, so a term absent here is absent from the
runs, not missing from the pattern list. <b>Reaching for a method is not evidence it was used
correctly</b> &mdash; that is what the outcome score measures, separately.</p></div>

<h2>4 &middot; Thought flow, by arm</h2>
<div class="panel"><div class="tblwrap"><table>
<thead><tr><th>arm</th><th class="num">eps</th><th class="num">run_code</th>
<th class="num">checkpoints</th>
<th class="num">confidence rise<span class="sub">last &minus; first</span></th>
<th class="num">time to high<span class="sub">0 = immediately</span></th>
<th class="num">alternatives<span class="sub">per checkpoint</span></th>
<th class="num">evidence against</th><th class="num">pivots</th></tr></thead>
<tbody>{arm_rows}</tbody></table></div>
<p class="lead">Confidence is the agent's own <code>confidence</code> field mapped
low/medium/high &rarr; 0/0.5/1. <b>Time to high</b> is where in the checkpoint sequence it first
says <i>high</i>, normalised to 0&ndash;1; 1.0 means never, or only at the very end. The predicted
explore/exploit signature is that blinded arms build confidence later than informed ones.
<b>All of this is self-reported</b> &mdash; the agent asserting it weighed alternatives is not
evidence that it did, which is exactly why the support judge grades grounding separately.</p></div>

<h2>5 &middot; Pivots &mdash; measured on the text, and what the judge said</h2>
<div class="panel"><div class="tblwrap"><table>
<thead><tr><th>model</th><th>prompt</th>
<th class="num">pivots<span class="sub">checkpoints only</span></th>
<th class="num">pivots<span class="sub">whole trace</span></th>
<th class="num">pivots<span class="sub">judge, panel mean</span></th>
<th class="num">hypothesis<span class="sub">statements/episode</span></th>
<th class="num">never pivoted<span class="sub">checkpoint measure</span></th></tr></thead>
<tbody>{piv_rows}</tbody></table></div>
<p class="lead">A <b>pivot</b> is a hypothesis statement sharing less than
<b>{PIVOT_THRESHOLD}</b> of its content words with the one before it &mdash; deterministic, over
the agent's own text, stopwords and task boilerplate removed. Two substrates carry hypotheses:
the <b>checkpoints</b> (<code>record_observation.current_hypothesis</code>, which is what the
support judge grades) and the far denser <b>whole trace</b>, which adds the
<code># CURRENT_HYPOTHESIS:</code> header every <code>run_code</code> call carries.
<br>{piv_note}
<br>Threshold sensitivity is real: raise it and paraphrase counts as a pivot, lower it and only
wholesale topic changes do. It is one number in <code>cot_flow.py</code>; change it there and
both measured columns move together.</p></div>

<h2>6 &middot; Every episode</h2>
<div class="panel">
<details><summary>show all {len(rows)} episodes</summary>
<div class="tblwrap"><table>
<thead><tr><th>model</th><th>prompt</th><th>episode</th><th>tool sequence</th>
<th class="num">code</th><th class="num">chk</th><th class="num">err</th>
<th class="num">pivots</th><th>method families</th></tr></thead>
<tbody>{ep_rows}</tbody></table></div></details>
<p class="lead">Tool sequence in call order:
<span class="seq"><span class="c">C</span></span> <code>run_code</code> &middot;
<span class="seq"><span class="r">R</span></span> <code>record_observation</code> &middot;
<span class="seq"><span class="s">S</span></span> <code>submit_discovery</code>.
Read the shape: <code>CCCCRS</code> is a run that analysed then narrated once at the end;
<code>CRCRCRS</code> is one that checkpointed as it went. The judges only ever see the
<span class="seq"><span class="r">R</span></span>s and the WHY headers.</p></div>

<div class="foot">Machine-readable output: <code>{OUT_JSON}</code> &mdash; the same aggregates plus
one record per episode, including every hypothesis string and the pairwise similarity series.
Companion: <code>scripts/cot_deepdive.py</code> (H1/H2 hypothesis tests, judge-derived).</div>
</div></body></html>"""
    os.makedirs(os.path.dirname(OUT_HTML), exist_ok=True)
    open(OUT_HTML, 'w').write(html)
    print(f'wrote {OUT_HTML}  ({len(html)} bytes)')
    print(f"  lanes={len(lanes)}  episodes={len(rows)}  "
          f"zero-checkpoint={zero_obs}  no-submit={no_sub}")


if __name__ == '__main__':
    main()
