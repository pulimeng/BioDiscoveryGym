#!/usr/bin/env python3
"""
extract_cot.py — Extract scientific chain-of-thought from BioDiscoveryGym episodes.

For each episode JSON, produces:
  1. A compact CoT trace (~100-200 lines) showing the reasoning chain:
       - What the agent looked for (# WHY / # EXPECTS)
       - What it found (first lines of tool result + key stats)
       - Hypothesis evolution milestones
       - Final submission summary
  2. A cross-run index comparing reasoning patterns across all episodes.

Usage:
  python scripts/extract_cot.py
  python scripts/extract_cot.py --results results/external/run8 --out analysis/cot_run8
  python scripts/extract_cot.py --episode 7a240cea
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Optional


# ---------------------------------------------------------------------------
# Regex helpers
# ---------------------------------------------------------------------------

WHY_PAT     = re.compile(r"#\s*WHY:\s*(.+)")
EXPECTS_PAT = re.compile(r"#\s*EXPECTS:\s*(.+)")
STAGE_PAT   = re.compile(r"#\s*(?:Stage|Step|Phase)\s*(\d+)\s*[:\-—]\s*(.+)", re.I)
STAGE_IN_WHY = re.compile(r"Stage\s+(\d+)\s*[-—:]\s*(.+)", re.I)
BANNER_PAT  = re.compile(r"#\s*=+\s*(.+?)\s*=+")
STAT_PAT    = re.compile(
    r"(?:p\s*[=<>]\s*[\d.e+\-]+|HR\s*=\s*[\d.]+|r\s*=\s*-?[\d.]+|"
    r"rho\s*=\s*-?[\d.]+|ρ\s*=\s*-?[\d.]+|"
    r"(?:delta_beta|Δβ|delta-beta)\s*=\s*-?[\d.]+|"
    r"OR\s*=\s*[\d.]+|Fisher(?:\s+exact)?\s+p\s*=\s*[\d.e+\-]+|"
    r"Cohen'?s?\s+d\s*=\s*-?[\d.]+|chi[2²]\s*=\s*[\d.]+|"
    r"log.rank p\s*=\s*[\d.e+\-]+|silhouette\s*=\s*[\d.]+|"
    r"AUC\s*=\s*[\d.]+|c.index\s*=\s*[\d.]+|"
    r"NMI\s*=\s*[\d.]+|ARI\s*=\s*[\d.]+)",
    re.I,
)

# Hypothesis-signal keywords — text containing these marks reasoning milestones
HYPOTHESIS_KW = re.compile(
    r"\b(hypothesis|conclude|subtype|cluster|pathway|mechanism|"
    r"driving|causal|this suggests|consistent with|key finding|"
    r"C\d_\w+|HALLMARK_|REACTOME_)\b",
    re.I,
)

# Codebook-arrival signature (tool_result text emitted at G2 reveal, or pre-revealed for G0/G1)
CODEBOOK_PAT = re.compile(
    r"(?:Your assistant has identified the gene codebook|translations loaded|"
    r"codebook is now available in your Python namespace|"
    r"codebook[\s'\"]*\s*[:=]?\s*[\{<]?\s*['\"]?GENE_\d)",
    re.I,
)

# Disease-naming signatures (broad cancer naming) — first call where agent commits to a diagnosis
DISEASE_PAT = re.compile(
    r"\b(osteosarcoma|ewing\s+sarcoma|rhabdomyosarcoma|wilms|chondrosarcoma|"
    r"acute\s+myeloid\s+leukemia|breast\s+cancer|lung\s+adenocarcinoma|"
    r"hepatocellular|glioblastoma|melanoma)\b",
    re.I,
)

# Pediatric/young-patient inference signatures — first call where clinical-metadata
# narrowing has occurred (this is the leak channel we identified in run8)
PEDIATRIC_PAT = re.compile(
    r"\b(pediatric|paediatric|adolescent|young\s+patients?|young\s+adult|"
    r"median\s+(?:age\s+)?(?:1[0-9]|2[0-5])|AYA\s+cancer|childhood\s+(?:cancer|tumor))\b",
    re.I,
)


# ---------------------------------------------------------------------------
# Extraction helpers
# ---------------------------------------------------------------------------

def _first_n_lines(s: str, n: int = 4) -> str:
    lines = [l for l in (s or "").split("\n") if l.strip()][:n]
    return " | ".join(lines)


def _trunc(s: str, n: int = 200) -> str:
    s = (s or "").strip()
    return s if len(s) <= n else s[:n].rstrip() + "…"


def _extract_stats(text: str, limit: int = 4) -> list[str]:
    seen, out = set(), []
    for m in STAT_PAT.finditer(text):
        val = m.group(0).strip()
        if val not in seen:
            seen.add(val)
            out.append(val)
        if len(out) >= limit:
            break
    return out


def _code_intent(code: str) -> dict:
    """Extract WHY, EXPECTS, stage label, and section banners from code."""
    why_m  = WHY_PAT.search(code)
    exp_m  = EXPECTS_PAT.search(code)
    ban_m  = BANNER_PAT.search(code)

    # Stage can appear as standalone "# Stage N:" or embedded in WHY
    stage = ""
    stage_num: Optional[int] = None
    stg_m = STAGE_PAT.search(code)
    if stg_m:
        stage = f"{stg_m.group(1)} — {stg_m.group(2).strip()}"
        try:
            stage_num = int(stg_m.group(1))
        except ValueError:
            pass
    elif why_m:
        why_text = why_m.group(1)
        sw_m = STAGE_IN_WHY.search(why_text)
        if sw_m:
            stage = f"{sw_m.group(1)} — {sw_m.group(2).strip()}"
            try:
                stage_num = int(sw_m.group(1))
            except ValueError:
                pass

    return {
        "why":       _trunc(why_m.group(1), 200) if why_m else "",
        "expects":   _trunc(exp_m.group(1), 160) if exp_m else "",
        "stage":     stage,
        "stage_num": stage_num,
        "banner":    ban_m.group(1).strip() if ban_m else "",
    }


# ---------------------------------------------------------------------------
# Core extractor
# ---------------------------------------------------------------------------

def extract_episode(path: str) -> dict:
    """Parse an episode JSON and return a structured CoT record."""
    ep = json.load(open(path))
    msgs    = ep.get("messages", [])
    disc    = ep.get("discovery", {}) or {}
    episode_id = ep.get("episode_id", Path(path).parent.name)
    mode = _infer_mode(Path(path).name)

    calls: list[dict] = []
    text_blocks: list[dict] = []
    current_stage = ""
    current_stage_num: Optional[int] = None
    call_idx = 0
    last_stage_num: Optional[int] = None
    stage_skips: list[dict] = []        # forward jumps > 1
    stage_regressions: list[dict] = []  # backwards jumps

    # G0/G1 have the codebook pre-loaded — check the initial user message
    codebook_at: Optional[int] = None
    pre_revealed = False
    if msgs and isinstance(msgs[0].get("content"), (str, list)):
        first_content = msgs[0]["content"]
        if isinstance(first_content, list):
            first_content = " ".join(
                str(b.get("text", b.get("content", ""))) for b in first_content if isinstance(b, dict)
            )
        if CODEBOOK_PAT.search(str(first_content)):
            codebook_at = 0
            pre_revealed = True

    disease_at: Optional[int] = None        # first call mentioning a specific disease
    pediatric_at: Optional[int] = None      # first call doing pediatric/age-based narrowing
    n_error_calls = 0

    for i, m in enumerate(msgs):
        role    = m.get("role", "")
        content = m.get("content", [])
        if not isinstance(content, list):
            continue

        for block in content:
            if not isinstance(block, dict):
                continue
            btype = block.get("type", "")

            if btype == "tool_use":
                call_idx += 1
                tool   = block.get("name", "")
                code   = block.get("input", {}).get("code", "") if tool == "run_code" else ""
                intent = _code_intent(code)
                if intent["stage"]:
                    current_stage = intent["stage"]
                    new_num = intent["stage_num"]
                    if new_num is not None:
                        if last_stage_num is not None:
                            if new_num > last_stage_num + 1:
                                stage_skips.append({
                                    "call": call_idx,
                                    "from": last_stage_num,
                                    "to":   new_num,
                                })
                            elif new_num < last_stage_num:
                                stage_regressions.append({
                                    "call": call_idx,
                                    "from": last_stage_num,
                                    "to":   new_num,
                                })
                        last_stage_num = new_num
                        current_stage_num = new_num

                # Fetch matching tool_result
                result_text = ""
                if i + 1 < len(msgs):
                    for nb in (msgs[i + 1].get("content", []) or []):
                        if isinstance(nb, dict) and nb.get("type") == "tool_result" and nb.get("tool_use_id") == block.get("id"):
                            r = nb.get("content", "")
                            if isinstance(r, list):
                                r = "\n".join(x.get("text", "") for x in r if isinstance(x, dict))
                            result_text = r or ""
                            break

                stats = _extract_stats(result_text)
                is_error = bool(re.search(r"Traceback|Error:", result_text))
                if is_error:
                    n_error_calls += 1

                # Codebook arrival — only check tool_result for G2 (post-reveal moment).
                # G0/G1 detected from initial user message above.
                if codebook_at is None and CODEBOOK_PAT.search(result_text):
                    codebook_at = call_idx

                # Disease + pediatric inference signatures (search WHY/EXPECTS + result_head)
                why_exp = (intent["why"] + " " + intent["expects"]).strip()
                head_for_signals = (why_exp + " " + result_text[:1500]).strip()
                if disease_at is None and DISEASE_PAT.search(head_for_signals):
                    disease_at = call_idx
                if pediatric_at is None and PEDIATRIC_PAT.search(head_for_signals):
                    pediatric_at = call_idx

                # WHY-text milestones (agent's hypothesis-tracking lives in WHY comments)
                why_is_milestone = bool(HYPOTHESIS_KW.search(why_exp)) if why_exp else False

                calls.append({
                    "idx":     call_idx,
                    "msg":     i,
                    "tool":    tool,
                    "stage":   current_stage,
                    "stage_num": current_stage_num,
                    "why":     intent["why"],
                    "expects": intent["expects"],
                    "banner":  intent["banner"],
                    "result_head": _first_n_lines(result_text, 3),
                    "stats":   stats,
                    "error":   is_error,
                    "code_head": "\n".join(code.strip().split("\n")[:5]),
                    "pre_codebook":  codebook_at is None or call_idx < codebook_at,
                    "is_milestone":  why_is_milestone,
                })

            elif btype == "text" and role == "assistant":
                txt = block.get("text", "").strip()
                if txt and len(txt) > 40:
                    text_blocks.append({
                        "call_after": call_idx,
                        "msg":        i,
                        "text":       txt,
                        "is_milestone": bool(HYPOTHESIS_KW.search(txt)),
                    })

    # Summarize stage breakdown by integer (canonical label = most common variant per stage)
    stage_calls_by_num: dict[int, int] = defaultdict(int)
    stage_label_variants: dict[int, list[str]] = defaultdict(list)
    unlabeled_calls = 0
    for c in calls:
        if c["stage_num"] is not None:
            stage_calls_by_num[c["stage_num"]] += 1
            if c["stage"]:
                stage_label_variants[c["stage_num"]].append(c["stage"])
        else:
            unlabeled_calls += 1

    stage_canonical: dict[int, str] = {}
    for num, labels in stage_label_variants.items():
        from collections import Counter
        stage_canonical[num] = Counter(labels).most_common(1)[0][0]

    # Legacy stage_calls (preserved for backwards compat in render_cot)
    stage_calls: dict[str, int] = defaultdict(int)
    for c in calls:
        stage_calls[c["stage"] or "(unlabeled)"] += 1

    return {
        "episode_id":  episode_id,
        "cohort":      ep.get("cohort", "?"),
        "seed":        ep.get("seed"),
        "model":       ep.get("model", "?"),
        "wall_s":      ep.get("wall_time_s", 0),
        "mode":        mode,
        "n_calls":     call_idx,
        "n_text":      len(text_blocks),
        "discovery":   disc,
        "calls":       calls,
        "text_blocks": text_blocks,
        "stage_calls": dict(stage_calls),                  # legacy: full-string keys
        "stage_calls_by_num": dict(stage_calls_by_num),    # new: integer-keyed
        "stage_canonical":    stage_canonical,             # new: int → canonical label
        "unlabeled_calls":    unlabeled_calls,             # new
        "stage_skips":        stage_skips,                 # new: forward jumps > 1
        "stage_regressions":  stage_regressions,           # new
        "codebook_at":        codebook_at,                 # new: call # of codebook arrival (0 = pre-revealed)
        "codebook_pre_revealed": pre_revealed,             # new: True for G0/G1
        "disease_at":         disease_at,                  # new: first explicit disease mention
        "pediatric_at":       pediatric_at,                # new: first pediatric/age-narrowing call
        "n_error_calls":      n_error_calls,               # new
    }


def _infer_mode(filename: str) -> str:
    m = re.search(r"_g([012])_", filename, re.I)
    return f"G{m.group(1)}" if m else "?"


# ---------------------------------------------------------------------------
# Render CoT markdown
# ---------------------------------------------------------------------------

def render_cot(ep: dict, detail: str = "normal") -> str:
    """
    detail: "normal" shows all calls with WHY/result
            "compact" shows only calls with WHY, stats, or errors
    """
    out: list[str] = []
    disc = ep["discovery"]
    wall_min = ep["wall_s"] / 60.0

    out.append(f"# CoT: `{ep['episode_id']}` | {ep['mode']} seed={ep['seed']}")
    out.append("")
    out.append(f"**Cohort**: {ep['cohort']}  **Model**: {ep['model']}  **Wall**: {wall_min:.1f} min  **Calls**: {ep['n_calls']}")

    # Key-event banner (codebook / disease-inference / pediatric-narrowing)
    banner_bits = []
    if ep["codebook_pre_revealed"]:
        banner_bits.append("codebook **pre-revealed** (G0/G1)")
    elif ep["codebook_at"] is not None:
        banner_bits.append(f"codebook revealed at call **#{ep['codebook_at']}**")
    else:
        banner_bits.append("codebook **never revealed** in trace")
    if ep["pediatric_at"] is not None:
        banner_bits.append(f"pediatric/age-narrowing at call **#{ep['pediatric_at']}**")
    if ep["disease_at"] is not None:
        banner_bits.append(f"disease named at call **#{ep['disease_at']}**")
    if ep["n_error_calls"]:
        banner_bits.append(f"**{ep['n_error_calls']} error(s)**")
    if banner_bits:
        out.append("")
        out.append(f"**Key events**: {' · '.join(banner_bits)}")

    # Pre-codebook reasoning audit (for G2 only — what did the agent narrow with no gene names?)
    if not ep["codebook_pre_revealed"] and ep["codebook_at"] is not None:
        if ep["pediatric_at"] is not None and ep["pediatric_at"] < ep["codebook_at"]:
            out.append(f"")
            out.append(f"> ⚠ **Pre-codebook narrowing detected**: pediatric/age inference at call #{ep['pediatric_at']}, "
                       f"{ep['codebook_at'] - ep['pediatric_at']} call(s) before codebook reveal. "
                       f"Clinical-metadata leak channel active.")
        if ep["disease_at"] is not None and ep["disease_at"] < ep["codebook_at"]:
            out.append(f"> ⚠ **Disease named pre-codebook**: call #{ep['disease_at']}.")

    # Stage breakdown (integer-keyed, dedupes the label variants)
    if ep.get("stage_calls_by_num"):
        out.append("")
        out.append("**Stage breakdown** (canonical label per stage):")
        for st_num in sorted(ep["stage_calls_by_num"]):
            n = ep["stage_calls_by_num"][st_num]
            canonical = ep["stage_canonical"].get(st_num, "")
            label = f"Stage {st_num}"
            if canonical:
                # strip the leading "N — " prefix
                m = re.match(r"\d+\s*[—\-:]\s*(.+)", canonical)
                short = m.group(1) if m else canonical
                label = f"Stage {st_num} ({_trunc(short, 60)})"
            out.append(f"  - {label}: {n} calls")
        if ep["unlabeled_calls"]:
            out.append(f"  - (unlabeled): {ep['unlabeled_calls']} calls")

    # Stage skips/regressions
    if ep["stage_skips"]:
        skip_strs = [f"call #{s['call']}: {s['from']}→{s['to']}" for s in ep["stage_skips"]]
        out.append(f"**Stage skips** ({len(ep['stage_skips'])}): {', '.join(skip_strs)}")
    if ep["stage_regressions"]:
        reg_strs = [f"call #{r['call']}: {r['from']}→{r['to']}" for r in ep["stage_regressions"]]
        out.append(f"**Stage regressions** ({len(ep['stage_regressions'])}): {', '.join(reg_strs)}")

    # Submission summary
    if disc:
        tg  = disc.get("top_genes", [])
        grp = disc.get("proposed_grouping", {})
        out.append("")
        out.append("## Final submission")
        if grp:
            counts: dict[str, int] = defaultdict(int)
            for v in grp.values():
                counts[v] += 1
            out.append(f"**Groups** ({len(counts)}): " + ", ".join(f"{k}(n={v})" for k, v in sorted(counts.items())))
        if tg:
            out.append(f"**Top genes**: {', '.join(tg[:20])}")
        pe = disc.get("pathway_evidence", [])
        if pe:
            out.append(f"**Pathway evidence** ({len(pe)} bullets):")
            for bullet in pe[:5]:
                out.append(f"  - {_trunc(str(bullet), 200)}")
        mh = disc.get("mechanism_hypothesis", "")
        if mh:
            out.append(f"**Mechanism hypothesis**:")
            out.append(f"> {_trunc(str(mh), 600)}")

    # Reasoning chain
    out.append("")
    out.append("## Reasoning chain")

    current_stage = ""
    codebook_divider_emitted = ep["codebook_pre_revealed"]  # already pre-revealed = no divider needed
    for c in ep["calls"]:
        # Emit codebook divider at the right moment
        if (not codebook_divider_emitted
            and ep["codebook_at"] is not None
            and c["idx"] >= ep["codebook_at"]):
            out.append("")
            out.append(f"> ═══════ **CODEBOOK REVEALED at call #{ep['codebook_at']}** ═══════")
            out.append("")
            codebook_divider_emitted = True

        # Print stage header when it changes — include skip/regression marker
        if c["stage"] and c["stage"] != current_stage:
            current_stage = c["stage"]
            skip_marker = ""
            for s in ep["stage_skips"]:
                if s["call"] == c["idx"]:
                    skip_marker = f"  ⚠ stage skip {s['from']}→{s['to']}"
                    break
            for r in ep["stage_regressions"]:
                if r["call"] == c["idx"]:
                    skip_marker = f"  ↩ stage regression {r['from']}→{r['to']}"
                    break
            out.append("")
            out.append(f"### Stage {current_stage}{skip_marker}")

        # In compact mode, skip calls without WHY, stats, error, or milestone
        if detail == "compact" and not c["why"] and not c["stats"] and not c["error"] and not c.get("is_milestone"):
            continue

        err_flag = " ⚠️" if c["error"] else ""
        ms_flag  = " ⭐" if c.get("is_milestone") else ""
        pre_flag = " ‹pre-cb›" if c.get("pre_codebook") and not ep["codebook_pre_revealed"] else ""
        banner   = f"  [{c['banner']}]" if c["banner"] else ""
        out.append(f"")
        out.append(f"**[{c['idx']}]** `{c['tool']}`{err_flag}{ms_flag}{pre_flag}{banner}")
        if c["why"]:
            out.append(f"  WHY: {c['why']}")
        if c["expects"]:
            out.append(f"  EXPECTS: {c['expects']}")
        if c["result_head"]:
            out.append(f"  → {_trunc(c['result_head'], 300)}")
        if c["stats"]:
            out.append(f"  → stats: {', '.join(c['stats'])}")

    # Text reasoning milestones
    milestones = [t for t in ep["text_blocks"] if t["is_milestone"]]
    if milestones:
        out.append("")
        out.append("## Hypothesis milestones (assistant reasoning blocks)")
        for tb in milestones:
            out.append("")
            out.append(f"### After call {tb['call_after']}")
            out.append(_trunc(tb["text"], 1200))

    # All text blocks (non-milestone) if normal detail
    other_text = [t for t in ep["text_blocks"] if not t["is_milestone"]]
    if detail == "normal" and other_text:
        out.append("")
        out.append("## Other reasoning blocks")
        for tb in other_text:
            out.append("")
            out.append(f"### After call {tb['call_after']}")
            out.append(_trunc(tb["text"], 800))

    return "\n".join(out)


# ---------------------------------------------------------------------------
# Cross-run index
# ---------------------------------------------------------------------------

def render_index(episodes: list[dict]) -> str:
    out: list[str] = []
    out.append("# CoT index — all episodes")
    out.append("")
    out.append("Per-episode key events. `cb` = codebook revealed; `ped` = first pediatric/age-narrowing inference; "
               "`dx` = first explicit disease mention. `pre` flag = `ped` or `dx` occurred BEFORE `cb` "
               "(clinical-metadata leak channel active in G2).")
    out.append("")
    out.append("| Episode | Mode | Seed | Calls | k | top1 | conf | cb call | ped call | dx call | leak | skips | err |")
    out.append("|---------|------|-----:|------:|--:|------|------|--------:|---------:|--------:|------|------:|----:|")

    for ep in sorted(episodes, key=lambda x: (x["mode"], x["seed"] or 0)):
        disc = ep["discovery"]
        tg   = disc.get("top_genes", [])
        grp  = disc.get("proposed_grouping", {})
        k    = len({v for v in grp.values()}) if grp else "?"
        conf = disc.get("confidence", "?")

        # Codebook column
        if ep["codebook_pre_revealed"]:
            cb_s = "pre"
        elif ep["codebook_at"] is not None:
            cb_s = f"#{ep['codebook_at']}"
        else:
            cb_s = "—"

        ped_s = f"#{ep['pediatric_at']}" if ep["pediatric_at"] is not None else "—"
        dx_s  = f"#{ep['disease_at']}"   if ep["disease_at"]   is not None else "—"

        # Leak detection: pediatric or disease inferred BEFORE codebook reveal (G2 only)
        leak = ""
        if not ep["codebook_pre_revealed"] and ep["codebook_at"] is not None:
            if ep["pediatric_at"] is not None and ep["pediatric_at"] < ep["codebook_at"]:
                leak = "⚠ ped"
            if ep["disease_at"] is not None and ep["disease_at"] < ep["codebook_at"]:
                leak = (leak + "+dx") if leak else "⚠ dx"

        skip_n = len(ep["stage_skips"]) + len(ep["stage_regressions"])
        err_n  = ep["n_error_calls"]

        out.append(
            f"| [{ep['episode_id']}]({ep['episode_id']}.md) "
            f"| {ep['mode']} "
            f"| {ep['seed']} "
            f"| {ep['n_calls']} "
            f"| {k} "
            f"| {tg[0] if tg else '–'} "
            f"| {conf} "
            f"| {cb_s} "
            f"| {ped_s} "
            f"| {dx_s} "
            f"| {leak} "
            f"| {skip_n if skip_n else ''} "
            f"| {err_n if err_n else ''} |"
        )

    # Stage usage (integer-aggregated — variant labels rolled up)
    out.append("")
    out.append("## Stage usage (by integer)")
    stages_by_num: dict[int, list[str]] = defaultdict(list)
    variant_counts: dict[int, set[str]] = defaultdict(set)
    for ep in episodes:
        for num in ep.get("stage_calls_by_num", {}):
            stages_by_num[num].append(ep["episode_id"])
        for num, label in ep.get("stage_canonical", {}).items():
            variant_counts[num].add(label)
    for num in sorted(stages_by_num):
        n_eps = len(set(stages_by_num[num]))
        n_variants = len(variant_counts[num])
        out.append(f"- **Stage {num}** — used by {n_eps} episode(s) across {n_variants} label variant(s)")

    # Stage skip / regression summary
    out.append("")
    out.append("## Stage skips and regressions")
    skip_lines = []
    for ep in sorted(episodes, key=lambda x: (x["mode"], x["seed"] or 0)):
        if ep["stage_skips"] or ep["stage_regressions"]:
            parts = []
            for s in ep["stage_skips"]:
                parts.append(f"skip {s['from']}→{s['to']}@call#{s['call']}")
            for r in ep["stage_regressions"]:
                parts.append(f"regression {r['from']}→{r['to']}@call#{r['call']}")
            skip_lines.append(f"- `{ep['episode_id']}` ({ep['mode']} s{ep['seed']}): {', '.join(parts)}")
    if skip_lines:
        out.extend(skip_lines)
    else:
        out.append("- (none)")

    # Codebook-leak summary (the cohort-level pattern we identified in run8)
    out.append("")
    out.append("## Clinical-metadata leak channel (G2 only)")
    g2_eps = [e for e in episodes if e["mode"] == "G2"]
    leaks = []
    for ep in g2_eps:
        cb = ep["codebook_at"]
        if cb is None: continue
        ped, dx = ep["pediatric_at"], ep["disease_at"]
        leak_bits = []
        if ped is not None and ped < cb:
            leak_bits.append(f"ped@#{ped}")
        if dx is not None and dx < cb:
            leak_bits.append(f"dx@#{dx}")
        if leak_bits:
            leaks.append(f"- `{ep['episode_id']}` (s{ep['seed']}): codebook@#{cb}, leak: {', '.join(leak_bits)}")
    if leaks:
        out.append(f"**{len(leaks)}/{len(g2_eps)} G2 episodes** show pre-codebook narrowing from clinical metadata:")
        out.extend(leaks)
    else:
        out.append(f"No leak detected in any of {len(g2_eps)} G2 episodes.")

    # Top gene frequency
    out.append("")
    out.append("## Top gene frequency across submissions")
    gene_freq: dict[str, int] = defaultdict(int)
    for ep in episodes:
        for g in (ep["discovery"].get("top_genes", []) or []):
            gene_freq[g] += 1
    top = sorted(gene_freq.items(), key=lambda x: -x[1])[:30]
    out.append("| Gene | # episodes |")
    out.append("|------|----------:|")
    for g, n in top:
        out.append(f"| {g} | {n} |")

    # k (number of groups) distribution
    out.append("")
    out.append("## k (number of groups) distribution")
    k_dist: dict[int, list[str]] = defaultdict(list)
    for ep in episodes:
        grp = ep["discovery"].get("proposed_grouping", {})
        k   = len({v for v in grp.values()}) if grp else 0
        k_dist[k].append(f"{ep['episode_id']}({ep['mode']})")
    for k_val in sorted(k_dist):
        out.append(f"- k={k_val}: {', '.join(k_dist[k_val])}")

    return "\n".join(out)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def find_episode_jsons(root: str) -> list[str]:
    paths = []
    for p in sorted(glob.glob(os.path.join(root, "*", "*.json"))):
        basename = os.path.basename(p)
        if any(x in basename for x in ("scores", "trace", "codebook", "gene_map", "grouping")):
            continue
        try:
            e = json.load(open(p))
            if e.get("messages") and e.get("discovery"):
                paths.append(p)
        except Exception:
            continue
    return paths


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--results", default="results/external/run8",
                    help="Root directory containing run episode subdirs")
    ap.add_argument("--out", default=None,
                    help="Output directory (default: analysis/cot_<run_dirname>)")
    ap.add_argument("--episode", default=None,
                    help="Restrict to one episode ID (substring match)")
    ap.add_argument("--detail", choices=["compact", "normal"], default="normal",
                    help="compact: only calls with WHY/stats; normal: all calls (default)")
    args = ap.parse_args()

    run_name = Path(args.results).name
    out_dir  = Path(args.out) if args.out else Path("analysis") / f"cot_{run_name}"
    out_dir.mkdir(parents=True, exist_ok=True)

    paths = find_episode_jsons(args.results)
    if args.episode:
        paths = [p for p in paths if args.episode in p]
        if not paths:
            print(f"No episode matching '{args.episode}' under {args.results}", file=sys.stderr)
            sys.exit(1)

    episodes = []
    for p in paths:
        try:
            ep = extract_episode(p)
        except Exception as exc:
            print(f"  ! {p}: {exc}", file=sys.stderr)
            continue

        md = render_cot(ep, detail=args.detail)
        out_path = out_dir / f"{ep['episode_id']}.md"
        out_path.write_text(md)
        episodes.append(ep)
        print(f"  ✓ {ep['episode_id']} ({ep['mode']} seed={ep['seed']}) — "
              f"{ep['n_calls']} calls | {len(ep['stage_calls'])} stages | "
              f"k={len({v for v in ep['discovery'].get('proposed_grouping',{}).values()})} groups")

    if episodes and not args.episode:
        idx = render_index(episodes)
        idx_path = out_dir / "index.md"
        idx_path.write_text(idx)
        print(f"\nWrote {len(episodes)} CoT traces to {out_dir}/")
        print(f"Index: {idx_path}")


if __name__ == "__main__":
    main()
