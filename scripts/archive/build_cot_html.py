#!/usr/bin/env python3
"""
build_cot_html.py — Build the per-run CoT summary HTML from MD files.

Reads <run_dir>/*.md (output of extract_cot.py), parses per-call reasoning
plus stage transitions, classifies each call by archetype, and emits a
self-contained HTML with:

  - Compliance grid (PC1 / residual / [PRIOR]/[DATA] adoption etc.)
  - Trajectory strips, one per episode — TWO parallel rows per strip:
      · top    : archetype colors (current format, unchanged)
      · bottom : stage band (distinguishes Stage 0/1/2/3/4/5 visually)
  - Pivots, per-episode reasoning cards, etc.

Usage:
  python scripts/build_cot_html.py --in analysis/cot_run9 --out analysis/cot_run9/cot_summary.html
  python scripts/build_cot_html.py --in analysis/cot_run8 --out analysis/cot_run8/cot_summary.html
"""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path


# ---------------------------------------------------------------------------
# Parse one CoT markdown file into a structured payload
# ---------------------------------------------------------------------------

def parse_episode(path: Path) -> dict:
    text = path.read_text()
    m = re.match(r"# CoT: `([^`]+)` \| (G\d) seed=(\d+)", text)
    uuid = m.group(1) if m else path.stem
    mode = m.group(2) if m else "?"
    seed = int(m.group(3)) if m else -1

    wall = re.search(r"\*\*Wall\*\*:\s*([\d.]+) min", text)
    calls = re.search(r"\*\*Calls\*\*:\s*(\d+)", text)
    cb = re.search(r"codebook revealed at call \*\*#(\d+)\*\*", text)
    cb_pre = "codebook **pre-revealed**" in text
    n_err = re.search(r"\*\*(\d+) error", text)

    # Final submission
    final_m = re.search(r"## Final submission\n(.*?)\n## Reasoning chain", text, re.DOTALL)
    final_txt = final_m.group(1) if final_m else ""
    top_genes = []
    tg = re.search(r"\*\*Top genes\*\*:\s*(.+)", final_txt)
    if tg:
        top_genes = [g.strip() for g in tg.group(1).split(",")]
    mech = ""
    m2 = re.search(r"\*\*Mechanism hypothesis\*\*:\s*\n((?:> .+\n?)+)", final_txt)
    if m2:
        mech = "\n".join(l[2:] if l.startswith("> ") else l
                         for l in m2.group(1).strip().split("\n"))
    sizes_m = re.search(r"\*\*Groups\*\*\s*\((\d+)\):\s*(.+)", final_txt)
    k = int(sizes_m.group(1)) if sizes_m else 0
    sizes = ([int(x) for x in re.findall(r"n=(\d+)", sizes_m.group(2))]
             if sizes_m else [])
    pathway_lines = re.findall(
        r"- (HALLMARK_[A-Z_]+|REACTOME_[A-Z_]+|KEGG_[A-Z_]+|BIOCARTA_[A-Z_]+)\s+p=([\d.eE+-]+)",
        final_txt)[:4]

    # Episode-level stage summary (from the header table)
    stages = []
    for sm in re.finditer(r"  - Stage (\d+) \(([^)]+)\): (\d+) calls", text):
        stages.append({"num": int(sm.group(1)),
                       "label": sm.group(2),
                       "calls": int(sm.group(3))})

    # Reasoning chain — walk in order, tracking which stage we're in
    rc_m = re.search(r"## Reasoning chain\n(.*?)(?:\n## |\Z)", text, re.DOTALL)
    rc_text = rc_m.group(1) if rc_m else ""

    # Find positions of stage headings and call blocks, interleaved by position
    chain = []
    current_stage_num = None      # None = pre-Stage-0 / unlabeled
    current_stage_label = ""

    # Pattern that matches EITHER a stage heading OR a call block
    token_pat = re.compile(
        r"(?:^### Stage (\d+) — (.+?)$)"
        r"|"
        r"(?:^\*\*\[(\d+)\]\*\*\s*`([^`]+)`\s*(?:‹([^›]*)›)?\n((?:.|\n)*?)(?=\n\*\*\[|\n### |\Z))",
        re.MULTILINE,
    )
    for tok in token_pat.finditer(rc_text):
        if tok.group(1) is not None:
            # Stage heading
            current_stage_num = int(tok.group(1))
            current_stage_label = tok.group(2).strip()
            continue
        # Call block
        n, tool, tag, body = int(tok.group(3)), tok.group(4), tok.group(5) or "", tok.group(6) or ""
        why = re.search(r"WHY:\s*(.+?)(?=\n\s*EXPECTS:|\n\s*→|\Z)", body, re.DOTALL)
        expects = re.search(r"EXPECTS:\s*(.+?)(?=\n\s*→|\Z)", body, re.DOTALL)
        result_lines = re.findall(r"→ (.+)", body)
        stats = re.search(r"→ stats:\s*(.+)", body)
        chain.append({
            "n": n,
            "tool": tool,
            "tag": tag,
            "why":     (why.group(1).strip()     if why     else "").replace("\n", " ")[:300],
            "expects": (expects.group(1).strip() if expects else "").replace("\n", " ")[:200],
            "result":  (result_lines[0] if result_lines else "").strip()[:200],
            "stats":   (stats.group(1).strip() if stats else "")[:200],
            "stage_num":   current_stage_num,
            "stage_label": current_stage_label,
        })

    return {
        "uuid": uuid, "mode": mode, "seed": seed,
        "wall": float(wall.group(1)) if wall else 0,
        "calls": int(calls.group(1)) if calls else 0,
        "cb_at": int(cb.group(1)) if cb else None,
        "cb_pre": cb_pre,
        "n_err": int(n_err.group(1)) if n_err else 0,
        "top_genes": top_genes, "mech": mech, "k": k, "sizes": sizes,
        "pathways": pathway_lines,
        "stages": stages,
        "chain": chain,
    }


# ---------------------------------------------------------------------------
# Classify each call's WHY into a reasoning archetype
# ---------------------------------------------------------------------------

def classify_why(why: str) -> str:
    w = (why or "").lower()
    if any(t in w for t in [
        "orient", "load data", "load_data", "check what", "initial data",
        "understand what we", "inspect", "distributions", "data availabili", "codebook",
    ]):
        return "orient"
    if any(t in w for t in [
        "pca", "pc1", "pc2", "pc3", "variance", "dominant axis", "principal component",
    ]):
        return "pca"
    if any(t in w for t in [
        "residual", "regress out", "after pc1", "beyond pc1", "orthogonal to pc1",
    ]):
        return "residual"
    if any(t in w for t in [
        "cluster", "k=", "kmeans", "leiden", "hierarchical", "subtype", "group", "partition",
    ]):
        return "cluster"
    if any(t in w for t in [
        "cox", "survival", "log-rank", "logrank", "kaplan", "hr=", "hazard",
    ]):
        return "survival"
    if any(t in w for t in [
        "differential", "de marker", "de gene", "wilcoxon", "top gene",
        "marker gene", "limma", "top variable", "most expressed", "top expressed",
    ]):
        return "marker"
    if any(t in w for t in [
        "pathway", "gsea", "enrich", "hallmark", "reactome", "go term", "biological",
    ]):
        return "pathway"
    if any(t in w for t in [
        "mutation", "cna", "methylation", "rppa", "multi-modal", "multi modal",
        "cross-modal", "methylat", "amplification", "deletion", "somatic",
    ]):
        return "multimodal"
    if any(t in w for t in [
        "validate", "verify", "confirm", "sanity", "robust", "permutation", "check",
    ]):
        return "validate"
    if any(t in w for t in [
        "record_observation", "submit", "final", "report", "commit",
    ]):
        return "commit"
    return "other"


def find_pivots(chain: list[dict]) -> list[dict]:
    out = []
    for i, c in enumerate(chain):
        w = (c["why"] or "").lower()
        if any(t in w for t in [
            "not significant", "no signal", "p>0.05", "failed to",
            "does not stratify", "no relationship", "minimal correlation",
            "instead", "pivot", "reconsider", "different approach",
            "unexpected", "surprising", "too few", "too small",
            "discard", "abandon", "rules out", "rule out",
        ]):
            out.append({
                "n": c["n"], "why": c["why"], "stage_num": c.get("stage_num"),
                "prev_expect": chain[i-1]["expects"] if i > 0 else "",
                "prev_result": chain[i-1]["result"] if i > 0 else "",
            })
    return out[:5]


def find_commits(chain: list[dict]) -> list[dict]:
    out = []
    for c in chain:
        w = (c["why"] or "").lower()
        if any(t in w for t in [
            "commit to", "pre-register", "lock in", "finalize",
            "final cluster", "final k", "best k", "choose k",
            "decide on", "go with k=", "go with", "pick k=", "select k=",
        ]):
            out.append({"n": c["n"], "why": c["why"], "stage_num": c.get("stage_num")})
    return out[:3]


# ---------------------------------------------------------------------------
# Build payload
# ---------------------------------------------------------------------------

def build_payload(in_dir: Path) -> dict:
    files = sorted(p for p in in_dir.glob("*.md") if p.name not in ("index.md",))
    eps = []
    for f in files:
        try:
            ep = parse_episode(f)
        except Exception as e:
            print(f"  skip {f.name}: {e}")
            continue
        for c in ep["chain"]:
            c["arch"] = classify_why(c["why"])
        ep["pivots"] = find_pivots(ep["chain"])
        ep["commits"] = find_commits(ep["chain"])
        ep["final_thoughts"] = ep["chain"][-5:] if len(ep["chain"]) >= 5 else ep["chain"]
        eps.append(ep)
    eps.sort(key=lambda e: (e["mode"], e["seed"]))

    arch_total: Counter = Counter()
    for ep in eps:
        for c in ep["chain"]:
            arch_total[c["arch"]] += 1

    return {
        "eps": eps,
        "arch_total": dict(arch_total),
        "n": len(eps),
        "total_calls": sum(len(e["chain"]) for e in eps),
    }


# ---------------------------------------------------------------------------
# Render HTML
# ---------------------------------------------------------------------------

HTML_TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>CoT reasoning — TITLE_PLACEHOLDER</title>
<script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
<style>
  :root {
    --fg: #111; --muted: #555; --line: #ddd;
    --accent: #1a73e8; --good: #1e8a3c; --warn: #b06a00; --bad: #c0392b;
    --pill-bg: #f3f4f6;
  }
  * { box-sizing: border-box; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
    color: var(--fg); max-width: 1200px; margin: 0 auto; padding: 30px 20px 60px;
    line-height: 1.55; font-size: 15px;
  }
  h1 { font-size: 26px; margin-bottom: 4px; }
  h2 { font-size: 20px; margin-top: 36px; border-bottom: 1px solid var(--line); padding-bottom: 6px; }
  h3 { font-size: 15px; margin-top: 18px; color: #333; }
  .subtitle { color: var(--muted); font-size: 14px; margin-bottom: 24px; }
  .meta { background: var(--pill-bg); padding: 12px 16px; border-radius: 6px; font-size: 14px; margin-bottom: 24px; }
  .grp-g0 { color: #1a73e8; font-weight: 600; }
  .grp-g1 { color: #b06a00; font-weight: 600; }
  .grp-g2 { color: #1e8a3c; font-weight: 600; }
  code { background: #f4f4f4; padding: 1px 5px; border-radius: 3px; font-size: 12px; font-family: ui-monospace, monospace; }
  ul { padding-left: 22px; } li { margin: 4px 0; }
  .gene { display: inline-block; padding: 1px 5px; margin: 1px 2px; border-radius: 3px; background: #eef4ff; color: #1a73e8; font-size: 11px; font-family: ui-monospace, monospace; }

  /* === Reasoning chain (per-call details) === */
  .chain-call { border-left: 3px solid #ddd; padding: 4px 0 4px 12px; margin: 4px 0; font-size: 13px; }
  .chain-call.arch-pca       { border-left-color: #1a73e8; }
  .chain-call.arch-residual  { border-left-color: #6f42c1; }
  .chain-call.arch-cluster   { border-left-color: #00bcd4; }
  .chain-call.arch-survival  { border-left-color: #e8651a; }
  .chain-call.arch-marker    { border-left-color: #e91e63; }
  .chain-call.arch-pathway   { border-left-color: #9c27b0; }
  .chain-call.arch-multimodal{ border-left-color: #f9a825; }
  .chain-call.arch-validate  { border-left-color: #1e8a3c; }
  .chain-call.arch-commit    { border-left-color: #d32f2f; font-weight: 600; background: #fff5f5; }
  .chain-call.arch-orient    { border-left-color: #999; }
  .chain-call.arch-other     { border-left-color: #ddd; }
  .chain-call .head { font-size: 11px; color: var(--muted); font-family: ui-monospace, monospace; margin-bottom: 2px; }
  .chain-call .why { color: #111; }
  .chain-call .expects { color: #555; font-size: 12px; font-style: italic; }
  .chain-call .result { color: #444; font-size: 12px; font-family: ui-monospace, monospace; margin-top: 2px; }

  /* === Trajectory strips === */
  .traj-row {
    display: grid; grid-template-columns: 130px 1fr 230px; gap: 10px;
    align-items: center; margin: 10px 0;
  }
  .traj-strips { display: flex; flex-direction: column; gap: 2px; }
  .arc-strip, .stage-strip {
    display: flex; gap: 1px; border-radius: 3px; overflow: hidden;
  }
  .arc-strip   { height: 22px; }
  .stage-strip { height: 10px; }
  .arc-cell, .stage-cell {
    flex: 1; min-width: 4px;
    cursor: help;
  }
  /* White divider on the archetype strip at a stage transition */
  .arc-cell.stage-boundary { border-left: 2px solid white; }

  /* Archetype palette */
  .ac-pca        { background: #1a73e8; }
  .ac-residual   { background: #6f42c1; }
  .ac-cluster    { background: #00bcd4; }
  .ac-survival   { background: #e8651a; }
  .ac-marker     { background: #e91e63; }
  .ac-pathway    { background: #9c27b0; }
  .ac-multimodal { background: #f9a825; }
  .ac-validate   { background: #1e8a3c; }
  .ac-commit     { background: #d32f2f; }
  .ac-orient     { background: #777; }
  .ac-other      { background: #aaa; }

  /* Stage band palette — pale hues, distinct from archetype colors */
  .sc-s0 { background: #b3cde0; }
  .sc-s1 { background: #ccebc5; }
  .sc-s2 { background: #fbb4ae; }
  .sc-s3 { background: #fed9a6; }
  .sc-s4 { background: #decbe4; }
  .sc-s5 { background: #fddaec; }
  .sc-s6 { background: #e5d8bd; }
  .sc-sN { background: #eee; }

  /* Stage group blocks — used inside expanded reasoning chains */
  .stage-block {
    margin: 16px 0 8px;
    border-left: 4px solid var(--line);
    padding: 4px 0 4px 12px;
    background: linear-gradient(to right, rgba(0,0,0,0.02), transparent 30%);
  }
  .stage-block.stage-0 { border-left-color: #6b7c93; }
  .stage-block.stage-1 { border-left-color: #4f8a4f; }
  .stage-block.stage-2 { border-left-color: #c0392b; }
  .stage-block.stage-3 { border-left-color: #b06a00; }
  .stage-block.stage-4 { border-left-color: #6f42c1; }
  .stage-block.stage-5 { border-left-color: #c2185b; }
  .stage-block.stage-N { border-left-color: #bbb; }
  .stage-header {
    font-size: 13px; font-weight: 700; color: #333;
    margin: 0 0 6px; display: flex; align-items: baseline; gap: 8px;
  }
  .stage-header .stage-tag {
    display: inline-block; font-size: 10px; font-weight: 700;
    padding: 2px 8px; border-radius: 10px; color: white;
    letter-spacing: 0.5px; text-transform: uppercase;
  }
  .stage-header.stage-0 .stage-tag { background: #6b7c93; }
  .stage-header.stage-1 .stage-tag { background: #4f8a4f; }
  .stage-header.stage-2 .stage-tag { background: #c0392b; }
  .stage-header.stage-3 .stage-tag { background: #b06a00; }
  .stage-header.stage-4 .stage-tag { background: #6f42c1; }
  .stage-header.stage-5 .stage-tag { background: #c2185b; }
  .stage-header.stage-N .stage-tag { background: #bbb; color: #333; }
  .stage-header .stage-label-text {
    font-weight: 500; color: #555; font-size: 12px;
  }
  .stage-header .stage-meta {
    font-size: 11px; color: #888; font-weight: 400; margin-left: auto;
  }

  .pivot-box {
    background: #fff8f0; border-left: 3px solid var(--warn);
    padding: 8px 12px; margin: 6px 0; font-size: 13px; border-radius: 0 4px 4px 0;
  }
  .commit-box {
    background: #fff0f0; border-left: 3px solid var(--bad);
    padding: 8px 12px; margin: 6px 0; font-size: 13px; border-radius: 0 4px 4px 0;
  }
  details { margin: 8px 0; }
  details > summary { cursor: pointer; padding: 4px 0; }
  details[open] > summary { font-weight: 600; }
  .ep-card { border: 1px solid var(--line); border-radius: 6px; padding: 14px 18px; margin: 12px 0; background: white; }
  .ep-card > summary { font-weight: 600; font-size: 14px; display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }

  .chart { height: 340px; margin: 12px 0 20px; }
  .twocol { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; align-items: start; }
  blockquote {
    font-size: 13px; color: #333; border-left: 2px solid var(--line);
    padding: 6px 12px; margin: 6px 0; background: #fafafa;
  }
  .footer { margin-top: 50px; padding-top: 12px; border-top: 1px solid var(--line); color: var(--muted); font-size: 12px; }
  .legend { display: flex; flex-wrap: wrap; gap: 8px; margin: 8px 0 12px; font-size: 11px; }
  .legend-archetype span { padding: 2px 8px; border-radius: 8px; color: white; }
  .legend-stage span { padding: 2px 8px; border-radius: 8px; color: #222; }
</style>
</head>
<body>

<h1>HEADING_PLACEHOLDER</h1>
<div class="subtitle">
  N_EPS episodes · TOTAL_CALLS reasoning entries · trajectory strips color cells by reasoning archetype.
  Expand any episode below to see its reasoning chain grouped into stage blocks.
</div>

<h2>Legend</h2>
<div class="legend legend-archetype">
  <span class="ac-orient">orient</span>
  <span class="ac-pca">PCA</span>
  <span class="ac-residual">residual</span>
  <span class="ac-cluster">cluster</span>
  <span class="ac-survival">survival</span>
  <span class="ac-marker">marker</span>
  <span class="ac-pathway">pathway</span>
  <span class="ac-multimodal">multimodal</span>
  <span class="ac-validate">validate</span>
  <span class="ac-commit">commit</span>
  <span class="ac-other">other / setup</span>
</div>
<div class="legend legend-stage" style="margin-top:4px">
  <span class="sc-sN">pre-stage</span>
  <span class="sc-s0">Stage 0</span>
  <span class="sc-s1">Stage 1</span>
  <span class="sc-s2">Stage 2</span>
  <span class="sc-s3">Stage 3</span>
  <span class="sc-s4">Stage 4</span>
  <span class="sc-s5">Stage 5</span>
  <span class="sc-s6">Stage 6</span>
</div>

<h2>Archetype distribution across all calls</h2>
<div id="arch-chart" class="chart"></div>

<h2>Reasoning trajectories — one strip per episode</h2>
<p>Hover any cell to see its WHY and stage. Vertical white lines mark stage transitions on the archetype strip.</p>
<div id="trajectory-strips"></div>

<h2>Pivots — places where the agent reconsidered</h2>
<div id="pivot-list"></div>

<h2>Per-episode reasoning chains</h2>
<div id="episode-list"></div>

<div class="footer">
  Generated by <code>scripts/build_cot_html.py</code> from <code>INPUT_DIR_PLACEHOLDER/*.md</code>.
</div>

<script>
const data = __PAYLOAD__;

const ARCH_COLORS = {
  orient:'#777', pca:'#1a73e8', residual:'#6f42c1',
  cluster:'#00bcd4', survival:'#e8651a', marker:'#e91e63',
  pathway:'#9c27b0', multimodal:'#f9a825', validate:'#1e8a3c',
  commit:'#d32f2f', other:'#aaa',
};

function esc(s) {
  if (s === null || s === undefined) return '';
  return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

function stageKey(num) {
  if (num === null || num === undefined) return 'N';
  return String(num);
}
function stageDisplayName(num, label) {
  if (num === null || num === undefined) return '(pre-stage / unlabeled)';
  return `Stage ${num}${label ? ' — ' + label : ''}`;
}

function renderArchChart() {
  const order = ['orient','pca','residual','cluster','survival','marker','pathway','multimodal','validate','commit','other'];
  const counts = order.map(k => data.arch_total[k] || 0);
  const total = data.total_calls;
  Plotly.newPlot('arch-chart', [{
    x: order, y: counts, type: 'bar',
    marker: { color: order.map(k => ARCH_COLORS[k]) },
    text: counts.map(c => c + ' (' + (100*c/total).toFixed(0) + '%)'),
    textposition: 'outside',
  }], {
    title: `Calls per archetype, ${data.n} episodes combined`,
    yaxis: { title: '# calls', range: [0, Math.max(...counts) * 1.2] },
    margin: { l: 60, r: 30, t: 40, b: 60 }, height: 340,
  }, { displayModeBar: false });
}

function renderTrajectories() {
  const container = document.getElementById('trajectory-strips');
  container.innerHTML = data.eps.map(e => {
    const arcCells = e.chain.map((c, i) => {
      const prevStage = i > 0 ? e.chain[i-1].stage_num : undefined;
      const isBoundary = (i > 0 && c.stage_num !== prevStage);
      const stageLbl = (c.stage_num !== null && c.stage_num !== undefined)
        ? `Stage ${c.stage_num}` : '(pre-stage)';
      return `<div class="arc-cell ac-${c.arch}${isBoundary ? ' stage-boundary' : ''}"
                   title="#${c.n} · ${stageLbl} · ${c.arch}: ${esc((c.why||'').substring(0, 80))}"></div>`;
    }).join('');
    const stageCells = e.chain.map(c => {
      const key = (c.stage_num === null || c.stage_num === undefined) ? 'sN' : ('s' + c.stage_num);
      const stageLbl = (c.stage_num !== null && c.stage_num !== undefined)
        ? `Stage ${c.stage_num}` : '(pre-stage)';
      return `<div class="stage-cell sc-${key}"
                   title="${stageLbl}${c.stage_label ? ' — ' + esc(c.stage_label) : ''}"></div>`;
    }).join('');
    const lead = e.top_genes[0] || '—';
    const followGenes = (e.top_genes.slice(1, 6) || [])
      .map(g => `<span class="gene" style="font-size:10px">${esc(g)}</span>`).join('');
    return `<div class="traj-row">
      <div style="font-size:12px; color:#444">
        <span class="grp-${e.mode.toLowerCase()}">${e.mode} s${e.seed}</span><br>
        <code style="font-size:10px">${e.uuid}</code><br>
        <span style="font-size:11px; color:#888">${e.chain.length} calls</span>
      </div>
      <div class="traj-strips">
        <div class="arc-strip">${arcCells}</div>
        <div class="stage-strip">${stageCells}</div>
      </div>
      <div style="font-size:12px; line-height:1.3; padding-left: 6px; border-left: 3px solid #1e8a3c;">
        <div style="font-size:10px; color:#888; margin-bottom:2px">→ submitted</div>
        <div><span class="gene" style="font-size:12px; font-weight:600; padding:2px 7px;">${esc(lead)}</span></div>
        <div style="margin-top:3px">${followGenes}</div>
      </div>
    </div>`;
  }).join('');
}

function renderPivots() {
  const c = document.getElementById('pivot-list');
  const all = [];
  data.eps.forEach(e => e.pivots.forEach(p => all.push({...p, ep: e})));
  if (all.length === 0) {
    c.innerHTML = '<p><i>No pivots matched the heuristic.</i></p>';
    return;
  }
  c.innerHTML = all.map(p => {
    const stageLbl = p.stage_num !== null && p.stage_num !== undefined ? `Stage ${p.stage_num} · ` : '';
    return `<div class="pivot-box">
      <div><span class="grp-${p.ep.mode.toLowerCase()}">${p.ep.mode} s${p.ep.seed}</span>
           <code>${p.ep.uuid}</code> · ${stageLbl}call #${p.n}</div>
      <div>${esc(p.why)}</div>
      ${p.prev_expect ? `<div style="font-size:11px;color:#666;font-family:ui-monospace,monospace">prev EXPECTS: ${esc(p.prev_expect)}</div>` : ''}
      ${p.prev_result ? `<div style="font-size:11px;color:#666;font-family:ui-monospace,monospace">prev result: ${esc(p.prev_result)}</div>` : ''}
    </div>`;
  }).join('');
}

function renderOneCall(c) {
  return `<div class="chain-call arch-${c.arch}">
    <div class="head">#${c.n} · <code>${esc(c.tool)}</code> ${c.tag ? '· ‹' + esc(c.tag) + '›' : ''} · ${c.arch}</div>
    ${c.why ? `<div class="why"><b>WHY:</b> ${esc(c.why)}</div>` : ''}
    ${c.expects ? `<div class="expects"><b>EXPECTS:</b> ${esc(c.expects)}</div>` : ''}
    ${c.result ? `<div class="result">→ ${esc(c.result)}</div>` : ''}
    ${c.stats ? `<div class="result" style="color:#1e8a3c"><b>stats:</b> ${esc(c.stats)}</div>` : ''}
  </div>`;
}

// Ungrouped chain — used for "final 5 thoughts before submission" (rarely
// spans a stage boundary, so grouping adds noise there).
function renderCallChain(chain) {
  return chain.map(renderOneCall).join('');
}

// Grouped by stage — one block per stage, each block listing its calls in
// order. Walks the chain once so that consecutive runs of the same stage_num
// get folded together; if a stage is re-entered later (regression), it gets
// a fresh block — the temporal flow is preserved.
function renderCallChainGrouped(chain) {
  if (!chain.length) return '';
  const blocks = [];
  let curStage = chain[0].stage_num === undefined ? null : chain[0].stage_num;
  let curLabel = chain[0].stage_label || '';
  let buf = [];
  const flush = () => {
    if (!buf.length) return;
    const key = stageKey(curStage);
    const calls = buf.map(renderOneCall).join('');
    const firstN = buf[0].n, lastN = buf[buf.length - 1].n;
    blocks.push(`<div class="stage-block stage-${key}">
      <div class="stage-header stage-${key}">
        <span class="stage-tag">${curStage === null || curStage === undefined ? 'Pre' : 'S' + curStage}</span>
        <span class="stage-label-text">${esc(stageDisplayName(curStage, curLabel))}</span>
        <span class="stage-meta">${buf.length} call${buf.length !== 1 ? 's' : ''} · #${firstN}${firstN !== lastN ? '–#' + lastN : ''}</span>
      </div>
      ${calls}
    </div>`);
    buf = [];
  };
  for (const c of chain) {
    const stg = (c.stage_num === undefined ? null : c.stage_num);
    if (stg !== curStage) {
      flush();
      curStage = stg;
      curLabel = c.stage_label || '';
    } else if (c.stage_label && !curLabel) {
      // capture label if it shows up after the first call of the stage
      curLabel = c.stage_label;
    }
    buf.push(c);
  }
  flush();
  return blocks.join('');
}

function renderEpisodes() {
  const c = document.getElementById('episode-list');
  c.innerHTML = data.eps.map(e => {
    const topgenesHtml = e.top_genes.slice(0,15).map(g => `<span class="gene">${esc(g)}</span>`).join('');
    const pivotsHtml = e.pivots.map(p => {
      const stageLbl = p.stage_num !== null && p.stage_num !== undefined ? `Stage ${p.stage_num} · ` : '';
      return `<div class="pivot-box"><div><b>#${p.n}</b> · ${stageLbl}${esc(p.why)}</div></div>`;
    }).join('');
    const commitsHtml = e.commits.map(co => {
      const stageLbl = co.stage_num !== null && co.stage_num !== undefined ? `Stage ${co.stage_num} · ` : '';
      return `<div class="commit-box"><b>#${co.n}</b> · ${stageLbl}${esc(co.why)}</div>`;
    }).join('');
    const finalThoughtsHtml = renderCallChain(e.final_thoughts || []);
    const fullChainHtml = renderCallChainGrouped(e.chain);
    const mech = (e.mech || '');
    return `<details class="ep-card">
      <summary>
        <span class="grp-${e.mode.toLowerCase()}">${e.mode} seed ${e.seed}</span>
        <code>${e.uuid}</code>
        · ${e.calls} calls · ${e.chain.length} parsed thoughts
        · top-1: <span class="gene">${esc(e.top_genes[0] || '—')}</span>
        · k=${e.k}
      </summary>
      <h3>Final submission</h3>
      <div><b>Top genes:</b> ${topgenesHtml}</div>
      <h3>Mechanism hypothesis</h3>
      <blockquote>${esc(mech).substring(0, 1500)}${mech.length > 1500 ? '…' : ''}</blockquote>
      ${pivotsHtml ? '<h3>Pivot moments</h3>' + pivotsHtml : ''}
      ${commitsHtml ? '<h3>Commits / decisions</h3>' + commitsHtml : ''}
      <h3>Final 5 thoughts before submission</h3>
      ${finalThoughtsHtml}
      <details style="margin-top: 16px">
        <summary><b>Full reasoning chain — ${e.chain.length} thoughts (click to expand)</b></summary>
        <div style="margin-top:8px">${fullChainHtml}</div>
      </details>
    </details>`;
  }).join('');
}

renderArchChart();
renderTrajectories();
renderPivots();
renderEpisodes();
</script>
</body>
</html>
"""


def render(payload: dict, out_path: Path, in_dir: Path, title: str) -> None:
    html = HTML_TEMPLATE
    html = html.replace("TITLE_PLACEHOLDER", title)
    html = html.replace("HEADING_PLACEHOLDER", title)
    html = html.replace("N_EPS", str(payload["n"]))
    html = html.replace("TOTAL_CALLS", str(payload["total_calls"]))
    html = html.replace("INPUT_DIR_PLACEHOLDER", str(in_dir))
    payload_json = json.dumps(payload, separators=(",", ":"), default=str)
    html = html.replace("__PAYLOAD__", payload_json)
    out_path.write_text(html)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="in_dir", required=True, help="dir with CoT *.md files")
    ap.add_argument("--out", dest="out_path", required=True, help="output HTML path")
    ap.add_argument("--title", default=None, help="title for the report")
    args = ap.parse_args()

    in_dir = Path(args.in_dir)
    out_path = Path(args.out_path)
    title = args.title or f"CoT reasoning — {in_dir.name}"

    payload = build_payload(in_dir)
    render(payload, out_path, in_dir, title)
    print(f"wrote {out_path} — {payload['n']} episodes, {payload['total_calls']} calls")


if __name__ == "__main__":
    main()
