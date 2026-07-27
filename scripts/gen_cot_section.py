#!/usr/bin/env python3
"""Build a dark-theme 'reasoning evidence (CoT)' section for the ladder report.
Source = the agent's STATED reasoning (# WHY headers + assistant text + record_observation),
NOT hidden thinking (stripped by the adapters). G2 (blind) pre-codebook cancer-naming."""
import glob, os, json, re, html as H
runs = {'Sonnet 5': 'sonnet5_20260713', 'GPT-5.5': 'gpt55_20260707', 'Gemini 3.5 Flash': 'gemini35flash_20260716'}
COL = {'Sonnet 5': '#7F77DD', 'GPT-5.5': '#1D9E75', 'Gemini 3.5 Flash': '#EF9F27'}
DIS = {'ov': r'ovarian|serous|hgsoc', 'brca': r'\bbreast\b|luminal|basal-like', 'luad': r'lung adeno|\bLUAD\b',
       'lusc': r'squamous|\bLUSC\b', 'lihc': r'\bliver\b|hepatocellular|\bHCC\b', 'ucec': r'endometrial|uterine', 'prad': r'prostate'}
STAT = re.compile(r'\d+\.?\d*\s*%|mutated in \d|burden|amplif|instability|\bp\s*[=<]')

def seq(ep):
    s = []; ci = 0
    for m in ep.get('messages', []):
        c = m.get('content')
        if not isinstance(c, list): continue
        for b in c:
            if not isinstance(b, dict): continue
            if b.get('type') == 'tool_use':
                ci += 1
                if b.get('name') == 'run_code':
                    for ln in b['input'].get('code', '').splitlines():
                        if re.match(r'\s*#\s*WHY', ln): s.append((ci, ln.strip().lstrip('# ')))
                elif b.get('name') == 'record_observation':
                    h = b['input'].get('current_hypothesis', '')
                    if h: s.append((ci, h))
            elif b.get('type') == 'text' and m.get('role') == 'assistant':
                t = b.get('text', '')
                if t and len(t) > 30: s.append((ci, t))
    return s

def cbcall(ep):
    ci = 0
    for m in ep.get('messages', []):
        c = m.get('content')
        if not isinstance(c, list): continue
        for b in c:
            if isinstance(b, dict) and b.get('type') == 'tool_use': ci += 1
            if isinstance(b, dict) and b.get('type') == 'tool_result':
                r = b.get('content', '')
                if isinstance(r, list): r = ' '.join(x.get('text', '') for x in r if isinstance(x, dict))
                if 'codebook' in str(r).lower() and 'GENE_' in str(r): return ci
    return 999

data = {}
for n, dsl in runs.items():
    dirs = [d for d in sorted(glob.glob(f'results/tcga/ladder/{dsl}/g2_*')) if os.path.isdir(d)]
    pre = 0; quotes = []
    for d in dirs:
        j = os.path.join(d, os.path.basename(d) + '.json')
        if not os.path.exists(j): continue
        ep = json.load(open(j)); coh = (ep.get('cohort') or '').lower()
        pat = re.compile(DIS.get(coh, 'zzzz'), re.I); cb = cbcall(ep)
        for ci, txt in seq(ep):
            if ci < cb and pat.search(txt):
                pre += 1
                quotes.append((coh.upper(), ci, cb, 'derive' if STAT.search(txt) else 'assume', re.sub(r'\s+', ' ', txt).strip()))
                break
    data[n] = (len(dirs), pre, quotes)

# curated quote cards (Gemini's assume-first guesses are the payload)
def cards():
    out = ""
    # Gemini vivid ones first
    for n in ['Gemini 3.5 Flash', 'Sonnet 5', 'GPT-5.5']:
        tot, pre, quotes = data[n]
        for coh, ci, cb, mode, q in quotes[:3]:
            cls = 'bad' if mode == 'assume' else 'mis'
            out += (f'<div class="q {cls}"><div class="qh"><b style="color:{COL[n]}">{n}</b> · {coh} · '
                    f'call #{ci} (blind — codebook at #{cb}) · <span class="tag {cls}">{mode}-first</span></div>'
                    f'<div class="qt">“{H.escape(q[:240])}”</div></div>')
    return out

bars = ""
for n in ['Sonnet 5', 'GPT-5.5', 'Gemini 3.5 Flash']:
    tot, pre, _ = data[n]
    w = int(pre / tot * 100) if tot else 0
    bars += (f'<div class="br"><span class="bl">{n}</span><div class="bt"><div style="width:{max(w,2)}%;background:{COL[n]}"></div></div>'
             f'<span class="bv">{pre}/{tot}</span></div>')

CSS = """
:root{--bg:#0d1117;--panel:#161b22;--line:#283041;--ink:#e6edf3;--mut:#9aa7b4;--acc:#58a6ff;--bad:#f85149;--mis:#d29922}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.55 -apple-system,Segoe UI,Roboto,Arial,sans-serif;padding:30px}
.wrap{max-width:820px;margin:0 auto}h1{font-size:22px;margin:0 0 2px}h2{font-size:16px;margin:24px 0 6px;border-left:3px solid var(--acc);padding-left:10px}
.meta{color:var(--mut);font-size:13px;margin-bottom:8px}.lead{color:var(--mut);font-size:13px;margin:4px 0 10px}
.panel{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:14px 18px;margin:12px 0}
.br{display:flex;align-items:center;gap:8px;margin:6px 0;font-size:13px}.bl{width:130px}.bt{flex:1;height:16px;background:#0b1220;border-radius:5px;overflow:hidden}.bt div{height:100%}.bv{width:52px;text-align:right;font-variant-numeric:tabular-nums;font-weight:700}
.q{border-radius:8px;padding:10px 13px;margin:8px 0;border-left:3px solid var(--line);background:#0b1220}
.q.bad{border-left-color:var(--bad)}.q.mis{border-left-color:var(--mis)}
.qh{font-size:12px;color:var(--mut);margin-bottom:5px}.qt{font-size:13.5px;font-style:italic}
.tag{padding:1px 7px;border-radius:5px;font-size:11px;font-weight:700}.tag.bad{background:#3a1414;color:var(--bad)}.tag.mis{background:#3a2d10;color:var(--mis)}
.warn{background:#2a2410;border:1px solid #5c4a12;border-radius:8px;padding:11px 15px;margin:12px 0;color:#e8d48a;font-size:12.5px}
.foot{color:var(--mut);font-size:11.5px;margin-top:24px;border-top:1px solid var(--line);padding-top:12px}
code{background:#0b1220;padding:1px 5px;border-radius:4px;font-size:12px}.bad{color:var(--bad)}
"""

html = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Reasoning evidence (CoT) — recall in the agent's own words</title><style>{CSS}</style></head><body><div class="wrap">
<h1>Recall in the agent's own words</h1>
<div class="meta">G2 (fully blind) episodes · 3 models × 21 episodes · source: the agent's <b>stated</b> reasoning — # WHY headers + inter-call text + record_observation. <span style="color:var(--mut)">(Raw thinking is stripped by the model adapters, so this is stated intent, not hidden CoT.)</span></div>

<h2>How often the model names the cancer <i>before</i> any gene name is revealed</h2>
<div class="panel">{bars}
<p class="lead">Fraction of blind (G2) episodes where the model commits to the actual cancer type in its reasoning <b>before the codebook reveals the genes.</b> Sonnet and GPT never do — they analyze first. <b>Gemini names it 6/21</b>, almost always by bare assertion (no computed evidence).</p></div>

<h2>What that looks like — it's recognizing the <i>dataset</i>, not the biology</h2>
<div class="panel">{cards()}
<p class="lead"><b>The tell:</b> Gemini identifies the cohort from its <b>shape</b> — "1095 samples, typical of BRCA in TCGA"; "518 samples → likely TCGA-LUAD" — i.e. it recalls TCGA cohort <i>dimensions</i>, before any molecular analysis. That's the most literal recall: recognizing the benchmark, not deriving the science. Sonnet's pre-commit reasoning (where it has any) is <span class="tag mis">derive-first</span> — a computed statistic first, disease name only after the codebook.</p></div>

<div class="warn"><b>Honest scope.</b> This is the agent's <i>stated</i> reasoning (WHY headers, text, observations) — the model adapters strip raw thinking-token text, so no true chain-of-thought is available for any model. Use these as qualitative evidence, not a scored signal. Detection is cohort-keyword based; hand-verify quotes before slides.</div>

<div class="foot">From <code>results/tcga/ladder/*/g2_*</code> episode messages. Generated by <code>scripts/gen_cot_section.py</code>.</div>
</div></body></html>"""
open('results/tcga/ladder/COT_EVIDENCE.html', 'w').write(html)
print("wrote results/tcga/ladder/COT_EVIDENCE.html", len(html), "bytes")
for n in runs: print(f"  {n}: {data[n][1]}/{data[n][0]} pre-codebook naming")
