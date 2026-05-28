#!/usr/bin/env python3
"""
Summarize the chain-of-thought / analysis flow of each cohort run in detail.

Reads episode JSONs under results/cohort/external/<run>/ and produces:
  1. One detailed markdown file per run (default ~150-400 lines)
  2. A combined index markdown listing all runs with channel × mode breakdown

For each run it extracts:
  - Mode / CLI flags / wall / message counts
  - Cohort-identification moment + channel + evidence
  - Codebook-reveal call (G2 only)
  - Stage labels declared by the agent in code (# Stage N, # === ===)
  - **Full call-by-call timeline** (every tool call) with:
      * Leading code-comment intent
      * Call category (data_load / clustering / de / methylation / pathway /
        survival / network / mutation / cohort_id / codebook / submit)
      * Tool-result snippet (truncated)
      * Errors caught
  - Per-stage statistics (calls in stage, methylation use, errors)
  - Methylation event log (when methylation was actually touched)
  - Quantitative findings extracted (p-values, correlations, fold changes,
    log-rank p, c-index, HRD scores)
  - Hypothesis-evolution snippets (assistant text-reasoning blocks)
  - Final submitted discovery payload (top genes / hypothesis / experiment)

Usage:
  python scripts/summarize_cot.py
  python scripts/summarize_cot.py --run 7fd94434
  python scripts/summarize_cot.py --brief         # short mode (first 40 calls)
  python scripts/summarize_cot.py --results <dir> --out <dir>
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Optional


# ---------------------------------------------------------------------------
# Regex / classification patterns
# ---------------------------------------------------------------------------

STAGE_PATTERNS = [
    re.compile(r"^\s*#\s*(?:Stage|Step|Phase)\s*(\d+)\s*[:\-—]\s*(.+?)\s*$", re.I | re.M),
    re.compile(r"^\s*#\s*===\s*(.+?)\s*===\s*$", re.M),
    re.compile(r"^\s*#\s*---+\s*(.+?)\s*---+\s*$", re.M),
]

COHORT_KEYWORDS = re.compile(r"(osteosarcoma|bone[- ]sarcoma|osteogenic sarcoma)", re.I)

ID_CHANNELS = [
    ("pathology_metadata_leak",
     re.compile(r"pathology.{0,80}(osteoblastic|chondroblastic|fibroblastic|small cell)|"
                r"(osteoblastic|chondroblastic|fibroblastic|small cell).{0,80}pathology",
                re.I | re.S),
     0),
    ("h3f3a_mutation_inference",
     re.compile(r"H3F3A.{0,200}(osteo|histone|hallmark|H3\.3|K27M|G34)", re.I | re.S),
     1),
    ("expression_pattern",
     re.compile(r"(SP7|Osterix|RUNX2|ALPL).{0,150}(osteo|bone|differentiat)", re.I | re.S),
     2),
    ("age_distribution",
     re.compile(r"(median age|young|adolescent|pediatric).{0,80}osteo", re.I | re.S),
     3),
]

# Call-category patterns: ordered, first match wins
CALL_CATEGORIES = [
    ("submit_discovery",        re.compile(r"submit_discovery", re.I)),
    ("codebook_request",        re.compile(r"request_codebook", re.I)),
    ("data_load",               re.compile(r"\b(metadata|expression\.shape|methylation\.shape|mutation\.shape|rppa|data availability|orientation|stage 0)\b", re.I)),
    ("methylation_analysis",    re.compile(r"\b(methylation|cpg|beta_value|EPIC|dmr|dmp|hypermethyl|hypomethyl|promoter methylation)\b", re.I)),
    ("clustering",              re.compile(r"\b(KMeans|cluster|hierarchical|consensus|NMF|silhouette|ARI|hclust|k=\d|n_clusters)\b", re.I)),
    ("differential_expression", re.compile(r"\b(DE |differential expression|logFC|log2FC|fold change|Cohen.{0,3}d|top markers|marker gene)\b", re.I)),
    ("pathway_enrichment",      re.compile(r"\b(MSigDB|REACTOME|HALLMARK|GOBP|GOMF|KEGG|enrichment|gsea|ORA|gene set|pathway)\b", re.I)),
    ("survival_analysis",       re.compile(r"\b(survival|log[_ ]rank|Cox|hazard|kaplan|HR=|c[_ -]?index|HRD)\b", re.I)),
    ("pca_dimred",              re.compile(r"\b(PCA|UMAP|tSNE|PC1|PC2|explained variance|StandardScaler)\b", re.I)),
    ("mutation_analysis",       re.compile(r"\b(mutation|TP53|H3F3A|ATRX|RB1|somatic|variant|driver)\b", re.I)),
    ("network_analysis",        re.compile(r"\b(STRING|PPI|network|degree|hub|PrimeKG|Steiner|nx\.|networkx)\b", re.I)),
    ("classifier",              re.compile(r"\b(classifier|cross[_ ]valid|LOO|CV accuracy|RandomForest|LogisticRegression|bootstrap)\b", re.I)),
    ("plotting",                re.compile(r"\b(plt\.|sns\.|fig.*savefig|heatmap|volcano|km_curve|figure)\b", re.I)),
]

CATEGORY_ICONS = {
    "submit_discovery":         "✅",
    "codebook_request":         "🔓",
    "data_load":                "📂",
    "methylation_analysis":     "🧬",
    "clustering":               "🎯",
    "differential_expression":  "📊",
    "pathway_enrichment":       "🛤️",
    "survival_analysis":        "💉",
    "pca_dimred":               "🌀",
    "mutation_analysis":        "🧪",
    "network_analysis":         "🕸️",
    "classifier":               "🧮",
    "plotting":                 "🖼️",
    "other":                    "·",
}

ERROR_PAT = re.compile(r"(Traceback|NameError|KeyError|ValueError|TypeError|AttributeError|FileNotFoundError|IndexError|ZeroDivisionError):")

# Quantitative-finding extractors (from tool results)
QUANT_PATTERNS = [
    ("p_value",     re.compile(r"\bp\s*[=<>]\s*[\d.e\-+]+", re.I)),
    ("padj",        re.compile(r"\b(?:padj|FDR|q[_-]?value)\s*[=<>]?\s*[\d.e\-+]+", re.I)),
    ("correlation", re.compile(r"\br\s*=\s*-?0\.\d+\b|Spearman r\s*=\s*-?[\d.]+|Pearson r\s*=\s*-?[\d.]+|rho\s*=\s*-?[\d.]+", re.I)),
    ("fold_change", re.compile(r"\b(?:logFC|log2FC|fold change|FC)\s*=\s*-?[\d.]+", re.I)),
    ("hazard",      re.compile(r"\bHR\s*=\s*[\d.]+", re.I)),
    ("cindex",      re.compile(r"\bc[\-_ ]?index\s*[=:]\s*[\d.]+", re.I)),
    ("hrd_score",   re.compile(r"\bHRD[^\n]{0,40}=\s*[\d.]+", re.I)),
    ("cpg_id",      re.compile(r"\bcg\d{8}\b")),
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def extract_code_intent(code: str, max_lines: int = 3) -> list[str]:
    intents = []
    for raw in code.split("\n"):
        s = raw.strip()
        if not s:
            if intents:
                break
            continue
        if s.startswith("#") and not s.startswith("#!"):
            text = s.lstrip("#").strip()
            if text:
                intents.append(text)
                if len(intents) >= max_lines:
                    break
        else:
            break
    return intents


def find_stage_label(code: str) -> Optional[str]:
    for pat in STAGE_PATTERNS:
        m = pat.search(code)
        if m:
            groups = [g for g in m.groups() if g]
            return " — ".join(g.strip() for g in groups)
    return None


def classify_call(code: str, tool_name: str = "") -> str:
    """Categorize a call by what it's primarily doing."""
    if tool_name == "submit_discovery":
        return "submit_discovery"
    if tool_name == "request_codebook":
        return "codebook_request"
    blob = code
    for cat, pat in CALL_CATEGORIES:
        if pat.search(blob):
            return cat
    return "other"


def extract_quant_findings(text: str, limit: int = 5) -> list[tuple[str, str]]:
    """Pull out quantitative claims from a tool_result blob."""
    findings = []
    for kind, pat in QUANT_PATTERNS:
        for m in pat.finditer(text):
            findings.append((kind, m.group(0).strip()))
            if len(findings) >= limit * len(QUANT_PATTERNS):
                break
    # Deduplicate, cap
    seen = set()
    deduped = []
    for kind, s in findings:
        key = (kind, s)
        if key in seen:
            continue
        seen.add(key)
        deduped.append((kind, s))
        if len(deduped) >= limit:
            break
    return deduped


def mode_from_label(label: str) -> str:
    parts = label.split("_")
    if len(parts) >= 2 and parts[1] in ("g0", "g1", "g2"):
        return parts[1].upper()
    return "?"


def detect_cohort_channel(searchable: str) -> Optional[str]:
    matches = []
    for name, pat, prio in ID_CHANNELS:
        if pat.search(searchable):
            matches.append((prio, name))
    if not matches:
        return None
    matches.sort()
    return matches[0][1]


def truncate(s: str, n: int) -> str:
    s = (s or "").strip()
    if len(s) <= n:
        return s
    return s[:n].rstrip() + "…"


def first_line(s: str, n: int = 160) -> str:
    s = (s or "").strip()
    if not s:
        return ""
    first = s.split("\n", 1)[0]
    return truncate(first, n)


# ---------------------------------------------------------------------------
# Core analyzer
# ---------------------------------------------------------------------------

def analyze_run(eps_path: str) -> dict:
    e = json.load(open(eps_path))
    msgs = e.get("messages", [])
    label = Path(eps_path).stem

    summary = {
        "label": label,
        "episode_id": e.get("episode_id"),
        "cohort": e.get("cohort"),
        "seed": e.get("seed"),
        "model": e.get("model"),
        "wall_s": e.get("wall_time_s"),
        "cli": e.get("cli", {}),
        "mode": mode_from_label(label),
        "n_messages": len(msgs),
        "discovery": e.get("discovery", {}),
        "calls": [],            # detailed per-call records
        "stages": [],           # [(call, label)] in order seen
        "stage_assign": {},     # call_num -> stage label (carried)
        "cohort_id": None,
        "codebook_reveal": None,
        "tool_counts": Counter(),
        "category_counts": Counter(),
        "errors": [],
        "text_reasoning": [],
        "methylation_events": [],
        "quant_findings": [],
        "key_decisions": [],   # text-reasoning blocks with high signal
    }

    call_num = 0
    current_stage = None

    for i, m in enumerate(msgs):
        role = m.get("role")
        content = m.get("content", [])
        if not isinstance(content, list):
            continue

        # Aggregate text in this message (for cohort-id detection)
        joint_text = []
        for c in content:
            if isinstance(c, dict):
                if c.get("type") == "text":
                    joint_text.append(c.get("text", ""))
                elif c.get("type") == "tool_use":
                    joint_text.append(c.get("input", {}).get("code", ""))
        joint = "\n".join(joint_text)

        # Walk content blocks
        # Pair each tool_use with its corresponding tool_result in the next message
        for c in content:
            if not isinstance(c, dict):
                continue
            t = c.get("type")

            if t == "tool_use":
                call_num += 1
                tool_name = c.get("name", "")
                summary["tool_counts"][tool_name] += 1

                if tool_name == "request_codebook" and summary["codebook_reveal"] is None:
                    summary["codebook_reveal"] = {"call": call_num, "msg_idx": i}

                code = c.get("input", {}).get("code", "") if tool_name == "run_code" else json.dumps(c.get("input", {}))[:400]
                stage = find_stage_label(code) if tool_name == "run_code" else None
                if stage and stage != current_stage:
                    current_stage = stage
                    summary["stages"].append((call_num, stage))

                category = classify_call(code, tool_name)
                summary["category_counts"][category] += 1
                intent = extract_code_intent(code) if tool_name == "run_code" else []

                # Try to find the matching tool_result in the NEXT message
                result_snippet = ""
                result_quant = []
                result_error = False
                if i + 1 < len(msgs):
                    nxt = msgs[i + 1].get("content", [])
                    if isinstance(nxt, list):
                        for nc in nxt:
                            if isinstance(nc, dict) and nc.get("type") == "tool_result":
                                if nc.get("tool_use_id") == c.get("id"):
                                    tr = nc.get("content", "")
                                    if isinstance(tr, list):
                                        # newer formats may have list of {type:text, text:..}
                                        tr = "\n".join(x.get("text", "") for x in tr if isinstance(x, dict))
                                    if isinstance(tr, str):
                                        result_snippet = tr
                                        result_quant = extract_quant_findings(tr, limit=4)
                                        if ERROR_PAT.search(tr):
                                            result_error = True
                                            err_match = ERROR_PAT.search(tr)
                                            s_idx = max(0, err_match.start() - 40)
                                            summary["errors"].append({
                                                "call": call_num,
                                                "snippet": truncate(tr[s_idx:err_match.end() + 200].replace("\n", " "), 240),
                                            })
                                    break

                # Detect cohort identification (first match across message text + code)
                if summary["cohort_id"] is None and COHORT_KEYWORDS.search(joint):
                    channel = detect_cohort_channel(joint) or "unspecified"
                    kw_match = COHORT_KEYWORDS.search(joint)
                    s_idx = max(0, kw_match.start() - 80)
                    evidence = joint[s_idx:kw_match.end() + 200].replace("\n", " ")
                    summary["cohort_id"] = {
                        "call": call_num,
                        "msg_idx": i,
                        "channel": channel,
                        "evidence": truncate(evidence, 320),
                    }

                # Methylation event log
                if category == "methylation_analysis" or "methylation" in code.lower():
                    summary["methylation_events"].append({
                        "call": call_num,
                        "intent": intent[0] if intent else first_line(code, 120),
                        "result_quant": result_quant[:3],
                    })

                # Quantitative findings (per call, top few)
                for kind, val in result_quant[:3]:
                    summary["quant_findings"].append({
                        "call": call_num,
                        "kind": kind,
                        "value": val,
                        "stage": current_stage,
                    })

                summary["stage_assign"][call_num] = current_stage
                summary["calls"].append({
                    "call": call_num,
                    "msg_idx": i,
                    "tool": tool_name,
                    "category": category,
                    "stage": current_stage,
                    "stage_label_new": stage,  # non-None only when stage label first appears here
                    "intent": intent[:2],
                    "code_first_lines": "\n".join(code.split("\n")[:6]),
                    "result_snippet": truncate(result_snippet, 600),
                    "result_first_line": first_line(result_snippet, 200),
                    "result_quant": result_quant[:4],
                    "error": result_error,
                })

            elif t == "text" and role == "assistant":
                txt = c.get("text", "").strip()
                if txt:
                    summary["text_reasoning"].append({
                        "call": call_num,
                        "text": truncate(txt, 600),
                    })
                    # Heuristic: pick up "key decision" blocks — longer reasoning containing strong signals
                    if (len(txt) > 200 and
                        any(kw in txt.lower() for kw in ("hypothesis", "conclude", "key", "summary", "this is", "consistent with", "subtype", "central"))):
                        summary["key_decisions"].append({
                            "call": call_num,
                            "text": truncate(txt, 700),
                        })

    return summary


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

def render_run_markdown(s: dict, brief: bool = False) -> str:
    out: list[str] = []
    out.append(f"# {s['label']}")
    out.append("")
    out.append(f"**Episode**: `{s['episode_id']}` · **Cohort**: {s['cohort']} · **Seed**: {s['seed']} · **Mode**: {s['mode']}")
    out.append(f"**Model**: {s['model']} · **Wall**: {s['wall_s']:.0f}s · **Messages**: {s['n_messages']}")

    tc = dict(s["tool_counts"])
    out.append(f"**Tool calls**: {sum(tc.values())} total · " + ", ".join(f"`{k}`={v}" for k, v in sorted(tc.items())))

    cli = s.get("cli", {})
    cli_interesting = {k: cli.get(k) for k in (
        "max_tool_calls", "gene_codebook_gate", "explicit_retrieval",
        "sample_codebook_gate", "mislead_cohort", "phase2", "perturb",
    ) if k in cli}
    if cli_interesting:
        out.append("**CLI flags**: " + ", ".join(f"`{k}={v}`" for k, v in cli_interesting.items()))
    out.append("")

    # Call-category mix
    out.append("## Call-category mix")
    out.append("| Category | Count | Icon |")
    out.append("|----------|------:|:----:|")
    cc = s["category_counts"]
    total = sum(cc.values())
    for cat, n in sorted(cc.items(), key=lambda x: -x[1]):
        icon = CATEGORY_ICONS.get(cat, "·")
        pct = (100.0 * n / total) if total else 0
        out.append(f"| {cat} | {n} ({pct:.0f}%) | {icon} |")
    out.append("")

    # Cohort identification
    out.append("## Cohort identification")
    if s["cohort_id"]:
        ci = s["cohort_id"]
        out.append(f"- **First mentioned at call {ci['call']}** (message #{ci['msg_idx']})")
        out.append(f"- **Channel**: `{ci['channel']}`")
        out.append(f"- **Evidence**:")
        out.append(f"  > {ci['evidence']}")
    else:
        out.append("- Not detected (pattern miss or agent never wrote 'osteosarcoma').")
    out.append("")

    if s["codebook_reveal"]:
        out.append("## Codebook reveal")
        gate = cli.get("gene_codebook_gate", "?")
        out.append(f"- Agent requested codebook at **call {s['codebook_reveal']['call']}** (G2 gate at call {gate}).")
        out.append("")

    # Stage labels
    out.append("## Stage labels declared in code")
    if s["stages"]:
        for call, stage in s["stages"]:
            out.append(f"- call {call}: **{stage}**")
    else:
        out.append("- (none — agent did not annotate code with `# Stage N` / `# === ===` headers)")
    out.append("")

    # Methylation event log
    if s["methylation_events"]:
        out.append(f"## Methylation event log ({len(s['methylation_events'])} calls touched methylation)")
        for ev in s["methylation_events"][:20]:
            intent = ev["intent"] or "(no comment)"
            quant_str = ""
            if ev["result_quant"]:
                quant_str = " — " + ", ".join(f"`{kind}: {val}`" for kind, val in ev["result_quant"][:2])
            out.append(f"- call **{ev['call']}**: {truncate(intent, 110)}{quant_str}")
        if len(s["methylation_events"]) > 20:
            out.append(f"- … ({len(s['methylation_events']) - 20} more methylation-related calls)")
        out.append("")

    # Key decisions / reasoning
    if s["key_decisions"]:
        out.append(f"## Key decision / reasoning blocks ({len(s['key_decisions'])})")
        for kd in s["key_decisions"][:8]:
            out.append(f"### After call {kd['call']}")
            out.append(f"> {kd['text']}")
            out.append("")

    # Quantitative findings summary
    if s["quant_findings"]:
        out.append(f"## Quantitative findings extracted from tool results ({len(s['quant_findings'])})")
        # Group by kind
        by_kind: dict[str, list[dict]] = defaultdict(list)
        for q in s["quant_findings"]:
            by_kind[q["kind"]].append(q)
        out.append("| Kind | Sample values (call#) |")
        out.append("|------|----------------------|")
        for kind in ("p_value", "padj", "correlation", "fold_change", "hazard", "cindex", "hrd_score", "cpg_id"):
            arr = by_kind.get(kind, [])
            if not arr:
                continue
            # Show up to 5 unique values
            uniq, seen = [], set()
            for q in arr:
                if q["value"] not in seen:
                    seen.add(q["value"])
                    uniq.append(f"`{q['value']}` (call {q['call']})")
                if len(uniq) >= 5:
                    break
            n_more = len(arr) - len(uniq)
            tail = f"  *+{n_more} more*" if n_more > 0 else ""
            out.append(f"| **{kind}** ({len(arr)} total) | " + ", ".join(uniq) + tail + " |")
        out.append("")

    # Full call-by-call timeline
    cap = 40 if brief else None  # show ALL calls by default
    if cap is None:
        out.append(f"## Call-by-call timeline (all {len(s['calls'])} calls)")
    else:
        out.append(f"## Call-by-call timeline (first {cap})")

    current_stage_render = None
    n_shown = 0
    for cinfo in s["calls"]:
        if cap is not None and n_shown >= cap:
            break
        # Stage break heading when a new stage label appears
        if cinfo["stage_label_new"] and cinfo["stage_label_new"] != current_stage_render:
            current_stage_render = cinfo["stage_label_new"]
            out.append("")
            out.append(f"### 🚩 Stage: {current_stage_render}")
            out.append("")

        cat = cinfo["category"]
        icon = CATEGORY_ICONS.get(cat, "·")
        intent = " / ".join(cinfo["intent"]) if cinfo["intent"] else ""
        if not intent:
            intent = first_line(cinfo["code_first_lines"], 120) or f"({cinfo['tool']})"
        err = " ⚠️" if cinfo["error"] else ""
        out.append(f"**Call {cinfo['call']}** {icon} `{cat}`{err} — {truncate(intent, 200)}")
        if cinfo["result_first_line"]:
            out.append(f"  - result: _{cinfo['result_first_line']}_")
        if cinfo["result_quant"]:
            qs = ", ".join(f"`{kind}: {val}`" for kind, val in cinfo["result_quant"][:3])
            out.append(f"  - findings: {qs}")
        n_shown += 1

    if cap is not None and len(s["calls"]) > cap:
        out.append("")
        out.append(f"_({len(s['calls']) - cap} more calls — run without `--brief` to see all)_")
    out.append("")

    # Errors detail
    if s["errors"]:
        out.append(f"## Errors encountered ({len(s['errors'])})")
        for er in s["errors"][:10]:
            out.append(f"- call {er['call']}: `{er['snippet']}`")
        out.append("")

    # Discovery payload
    disc = s.get("discovery", {})
    if disc:
        out.append("## Submitted discovery")
        tg = disc.get("top_genes", [])
        out.append(f"- **Top genes** ({len(tg)} total): {', '.join(tg[:20])}" + ("…" if len(tg) > 20 else ""))
        out.append(f"- **Confidence**: {disc.get('confidence', '?')}")

        pe = disc.get("pathway_evidence", [])
        if isinstance(pe, list) and pe:
            out.append(f"- **Pathway evidence** ({len(pe)} bullets):")
            for p in pe[:6]:
                out.append(f"  - {truncate(p, 280)}")
            if len(pe) > 6:
                out.append(f"  - … ({len(pe) - 6} more)")

        mh = str(disc.get("mechanism_hypothesis", "")).strip()
        if mh:
            out.append(f"- **Mechanism hypothesis**:")
            out.append(f"  > {truncate(mh, 1500)}")
        ne = str(disc.get("next_experiment", "")).strip()
        if ne:
            out.append(f"- **Proposed experiment**:")
            out.append(f"  > {truncate(ne, 800)}")

    return "\n".join(out)


def render_combined_index(summaries: list[dict], out_path: Path) -> None:
    lines = ["# Chain-of-thought summary — all runs", ""]
    lines.append("One row per run. The `Identified at` column shows the **call number** at which the agent first wrote 'osteosarcoma', and `Channel` shows which data signal the agent used to figure it out.")
    lines.append("")
    lines.append("| Run | Mode | Seed | Calls | Stages | Meth events | Identified | Channel | Codebook | Errors |")
    lines.append("|-----|------|-----:|------:|------:|----------:|----------:|---------|--------:|------:|")
    for s in sorted(summaries, key=lambda x: (x["mode"], x["seed"])):
        ci = s["cohort_id"]
        cr = s["codebook_reveal"]
        lines.append(
            f"| [{s['episode_id']}](cot_summaries/{s['episode_id']}.md) "
            f"| {s['mode']} "
            f"| {s['seed']} "
            f"| {sum(s['tool_counts'].values())} "
            f"| {len(s['stages'])} "
            f"| {len(s['methylation_events'])} "
            f"| {ci['call'] if ci else '–'} "
            f"| {ci['channel'] if ci else '–'} "
            f"| {cr['call'] if cr else '–'} "
            f"| {len(s['errors'])} |"
        )
    lines.append("")

    # Channel breakdown
    lines.append("## Cohort-identification channel breakdown")
    chans = Counter()
    for s in summaries:
        ch = s["cohort_id"]["channel"] if s["cohort_id"] else "not_detected"
        chans[ch] += 1
    for ch, n in chans.most_common():
        lines.append(f"- `{ch}`: {n} run(s)")
    lines.append("")

    # Channel × mode grid
    lines.append("## Channel × mode")
    grid: dict[tuple[str, str], int] = {}
    for s in summaries:
        mode = s["mode"]
        ch = s["cohort_id"]["channel"] if s["cohort_id"] else "not_detected"
        grid[(mode, ch)] = grid.get((mode, ch), 0) + 1
    modes = sorted({m for m, _ in grid.keys()})
    chans_l = sorted({c for _, c in grid.keys()})
    lines.append("| Channel \\ Mode | " + " | ".join(modes) + " |")
    lines.append("|---|" + "|".join("---:" for _ in modes) + "|")
    for ch in chans_l:
        row = [ch] + [str(grid.get((m, ch), 0)) for m in modes]
        lines.append("| " + " | ".join(row) + " |")
    lines.append("")

    # Aggregate category mix per mode
    lines.append("## Aggregate call-category mix per mode")
    cat_by_mode: dict[str, Counter] = defaultdict(Counter)
    for s in summaries:
        for cat, n in s["category_counts"].items():
            cat_by_mode[s["mode"]][cat] += n
    all_cats = sorted({c for cm in cat_by_mode.values() for c in cm.keys()})
    lines.append("| Category | " + " | ".join(modes) + " |")
    lines.append("|---|" + "|".join("---:" for _ in modes) + "|")
    for cat in all_cats:
        row = [f"{cat} {CATEGORY_ICONS.get(cat, '')}"]
        for m in modes:
            row.append(str(cat_by_mode[m].get(cat, 0)))
        lines.append("| " + " | ".join(row) + " |")
    lines.append("")

    # Methylation usage by mode
    lines.append("## Methylation usage by mode")
    meth_by_mode: dict[str, list[int]] = defaultdict(list)
    for s in summaries:
        meth_by_mode[s["mode"]].append(len(s["methylation_events"]))
    lines.append("| Mode | Mean meth calls | Range |")
    lines.append("|------|----------------:|-------|")
    for m in modes:
        arr = meth_by_mode[m]
        if not arr:
            continue
        lines.append(f"| {m} | {sum(arr)/len(arr):.1f} | {min(arr)}–{max(arr)} |")
    lines.append("")

    out_path.write_text("\n".join(lines))


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def find_episode_jsons(results_root: str) -> list[str]:
    eps: list[str] = []
    for d in sorted(glob.glob(os.path.join(results_root, "*", ""))):
        if "stale" in d or "cot_summaries" in d:
            continue
        cands = [p for p in glob.glob(os.path.join(d, "os_*.json"))
                 if "v2scores" not in p and "v3scores" not in p and "v3trace" not in p]
        if cands:
            eps.append(cands[0])
    return eps


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--results", default="results/cohort/external",
                    help="Root directory containing run subdirectories")
    ap.add_argument("--out", default=None,
                    help="Output directory for per-run markdown summaries "
                         "(default: <results>/cot_summaries)")
    ap.add_argument("--combined", default=None,
                    help="Path for combined index markdown "
                         "(default: <results>/cot_summary_all.md)")
    ap.add_argument("--run", default=None,
                    help="Limit to one run (substring match on episode dir name)")
    ap.add_argument("--brief", action="store_true",
                    help="Cap call-by-call timeline at 40 calls (default: show all)")
    args = ap.parse_args()

    results_root = args.results
    out_dir = Path(args.out) if args.out else Path(results_root) / "cot_summaries"
    combined_path = Path(args.combined) if args.combined else Path(results_root) / "cot_summary_all.md"

    out_dir.mkdir(parents=True, exist_ok=True)

    eps_paths = find_episode_jsons(results_root)
    if args.run:
        eps_paths = [p for p in eps_paths if args.run in p]
        if not eps_paths:
            print(f"No runs match '{args.run}' under {results_root}", file=sys.stderr)
            sys.exit(1)

    summaries = []
    for eps in eps_paths:
        try:
            s = analyze_run(eps)
        except Exception as exc:
            print(f"  ! {eps}: {exc}", file=sys.stderr)
            continue
        md = render_run_markdown(s, brief=args.brief)
        out_path = out_dir / f"{s['episode_id']}.md"
        out_path.write_text(md)
        summaries.append(s)
        ci = s["cohort_id"]
        cr = s["codebook_reveal"]
        print(f"  ✓ {s['episode_id']} ({s['mode']}, seed {s['seed']}) — "
              f"id@{ci['call'] if ci else '-'} via {ci['channel'] if ci else '-'} · "
              f"codebook@{cr['call'] if cr else '-'} · "
              f"{sum(s['tool_counts'].values())} calls · "
              f"{len(s['methylation_events'])} meth · "
              f"{len(s['errors'])} errors")

    if summaries and not args.run:
        render_combined_index(summaries, combined_path)
        print(f"\nWrote {len(summaries)} per-run summaries to {out_dir}/")
        print(f"Combined index: {combined_path}")


if __name__ == "__main__":
    main()
