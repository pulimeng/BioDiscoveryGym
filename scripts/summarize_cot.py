#!/usr/bin/env python3
"""summarize_cot.py — LLM (neutral DeepSeek) chain-of-thought summary per episode.

DISTILL-THEN-SUMMARIZE. Feeds the compact reasoning trace (NOT the ~54k-token raw episode)
to a neutral judge (DeepSeek-v4-pro, same family as the support scorer), which returns
structured fields + a prose paragraph describing HOW the agent reasoned.

Input = the SYMMETRIC reasoning channels only, so cross-model comparison is fair:
  · record_observation inputs  — the hypothesis-evolution log (all models, richest channel)
  · run_code # WHY / # EXPECTS  — the agent's stated intent per analysis step
  · the final submission        — grouping / top_genes / mechanism_hypothesis
It deliberately EXCLUDES: model 'thinking' (empty in saved episodes — the adapters strip the
text) and assistant free-text blocks (Sonnet writes ~27k words; GPT/Gemini write ~none, so
including them would bias the comparison). See extract_cot.py for the provenance.

Mirrors score_support.py: per-episode _cotsummary.json, resume-safe, neutral judge.

Usage:
  DEEPSEEK_API_KEY=... python scripts/summarize_cot.py results/tcga/ladder/gpt55_20260707 --save
  ... --dry          # print the distilled LLM input, no API call
  ... --limit 3      # first N episodes
  ... --rescore      # redo episodes that already have _cotsummary.json
  ... --model claude-...   # different NEUTRAL judge (not a benchmarked family)
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from extract_cot import extract_episode  # deterministic distiller (no LLM)

# ---------------------------------------------------------------------------
# Judge prompt + tool schema (structured fields + prose)
# ---------------------------------------------------------------------------
COT_SYSTEM = """You analyze the reasoning process of an autonomous AI scientist agent. It was \
given an ANONYMIZED multi-omics cancer cohort (opaque GENE_XXXXX ids; a gene codebook is \
revealed only at its 3rd observation) and asked to (1) find patient subgroups, (2) identify the \
cancer type, and (3) hypothesize the mechanism behind their different outcomes.

You are given a DISTILLED trace of its reasoning: its stated intent per step (WHY/EXPECTS), its \
logged hypothesis-evolution checkpoints (record_observation), and its final submission. This is \
its full auditable reasoning — there is no hidden chain-of-thought.

Summarize HOW it reasoned — strategy, rigor, and decision-making — NOT whether the biology is \
correct (a separate scorer judges correctness). Be specific and cite concrete moves. In \
particular judge: did it DERIVE the cohort identity from the data, or RECALL it from priors? \
Did it validate its structure (silhouette/survival/stability/cross-method)? On the codebook \
reveal, did it annotate what it already found, or rebuild/overfit to the revealed biology? \
Call record_cot_summary with your analysis."""

_COT_TOOL = {
    "name": "record_cot_summary",
    "description": "Structured summary of the agent's reasoning process.",
    "input_schema": {
        "type": "object",
        "properties": {
            "reasoning_strategy": {"type": "string",
                "description": "short tag for the overall approach, e.g. 'systematic-staged', "
                               "'exploratory-iterative', 'hypothesis-first', 'minimal-efficient', "
                               "'compute-heavy'"},
            "identity_derivation": {"type": "string",
                "enum": ["data-derived", "recalled-prior", "mixed", "not-established"],
                "description": "how it established the cancer/cohort identity"},
            "validation_rigor": {"type": "string", "enum": ["high", "medium", "low"],
                "description": "did it validate structure (silhouette, survival, stability, cross-method)?"},
            "codebook_response": {"type": "string",
                "enum": ["annotated-existing", "rebuilt-from-priors", "overfit-to-revealed", "not-applicable"],
                "description": "how it handled the gene-codebook reveal"},
            "num_pivots": {"type": "integer", "description": "count of hypothesis revisions/pivots"},
            "key_moves": {"type": "array", "items": {"type": "string"},
                "description": "2-5 pivotal analytic decisions, each one short phrase"},
            "strengths": {"type": "array", "items": {"type": "string"}},
            "weaknesses": {"type": "array", "items": {"type": "string"}},
            "overall_verdict": {"type": "string", "description": "one-line characterization of the reasoning"},
            "summary": {"type": "string",
                "description": "one prose paragraph (4-8 sentences) narrating how the agent reasoned"},
        },
        "required": ["reasoning_strategy", "identity_derivation", "validation_rigor",
                     "codebook_response", "num_pivots", "key_moves", "strengths",
                     "weaknesses", "overall_verdict", "summary"],
    },
}
_REQUIRED = _COT_TOOL["input_schema"]["required"]


def _trunc(s, n):
    s = str(s or "").replace("\n", " ").strip()
    return s if len(s) <= n else s[:n] + "…"


def build_input(rec: dict) -> str:
    """Assemble the symmetric-channel reasoning trace for the judge."""
    lines = [
        f"COHORT (blinded to the agent): {rec['cohort']}   ARM: {rec['mode']}   "
        f"MODEL: {rec['model']}   tool_calls: {rec['n_calls']}",
        f"codebook revealed at call: {rec['codebook_at']}"
        + ("  (pre-revealed: G0/G1)" if rec["codebook_pre_revealed"] else ""),
        "",
        "=== REASONING TIMELINE (WHY/EXPECTS per step + hypothesis-evolution checkpoints) ===",
    ]
    for c in rec["calls"]:
        pre = "‹pre-codebook› " if c.get("pre_codebook") and not rec["codebook_pre_revealed"] else ""
        if c.get("obs"):
            lines.append(f"\n[{c['idx']}] {pre}OBSERVATION (record_observation):")
            for k, v in c["obs"].items():
                lines.append(f"    {k}: {_trunc(v, 500)}")
        elif c["why"] or c["expects"]:
            seg = f"\n[{c['idx']}] {pre}{c['tool']}"
            if c["why"]:
                seg += f"  WHY: {_trunc(c['why'], 300)}"
            if c["expects"]:
                seg += f"  EXPECTS: {_trunc(c['expects'], 200)}"
            lines.append(seg)
            if c.get("stats"):
                lines.append(f"    → {_trunc(', '.join(c['stats']), 200)}")
    d = rec.get("discovery") or {}
    grp = d.get("proposed_grouping")
    ngroups = len(grp) if isinstance(grp, dict) else "?"
    lines += [
        "",
        "=== FINAL SUBMISSION ===",
        f"top_genes: {_trunc(', '.join(d.get('top_genes', []) or []), 400)}",
        f"n_groups: {ngroups}   confidence: {d.get('confidence')}",
        f"mechanism_hypothesis: {_trunc(d.get('mechanism_hypothesis'), 1200)}",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Neutral-judge call (mirrors support_judge._judge_openai_compatible)
# ---------------------------------------------------------------------------
def call_judge(user_msg: str, model: str = "deepseek-v4-pro") -> dict:
    ml = model.lower()
    if ml.startswith("claude") or "claude" in ml:
        import anthropic
        r = anthropic.Anthropic().messages.create(
            model=model, max_tokens=2500, system=COT_SYSTEM,
            tools=[_COT_TOOL], tool_choice={"type": "tool", "name": "record_cot_summary"},
            messages=[{"role": "user", "content": user_msg}])
        for b in r.content:
            if getattr(b, "type", None) == "tool_use" and b.name == "record_cot_summary":
                return b.input
        raise ValueError(f"no tool_use (stop_reason={r.stop_reason})")

    import openai
    if ml.startswith("deepseek"):
        client = openai.OpenAI(base_url="https://api.deepseek.com",
                               api_key=os.environ.get("DEEPSEEK_API_KEY"))
        tok_key, base_toks, retry_toks, tool_choice = "max_tokens", 16000, 32000, "auto"
    else:
        client = openai.OpenAI()
        tok_key, base_toks, retry_toks = "max_completion_tokens", 4000, 8000
        tool_choice = {"type": "function", "function": {"name": "record_cot_summary"}}
    tool = {"type": "function", "function": {
        "name": "record_cot_summary", "description": _COT_TOOL["description"],
        "parameters": _COT_TOOL["input_schema"]}}

    def _call(mt):
        return client.chat.completions.create(
            model=model, messages=[{"role": "system", "content": COT_SYSTEM},
                                    {"role": "user", "content": user_msg}],
            tools=[tool], tool_choice=tool_choice, **{tok_key: mt})

    def _parse(r):
        msg = r.choices[0].message
        if getattr(msg, "tool_calls", None):
            return json.loads(msg.tool_calls[0].function.arguments)
        return json.loads(msg.content or "{}")

    last = None
    for attempt in range(3):
        r = _call(base_toks if attempt == 0 else retry_toks)
        if r.choices[0].finish_reason == "length":
            r = _call(retry_toks)
        try:
            v = _parse(r)
        except Exception:
            v = None
        if isinstance(v, dict) and all(k in v for k in _REQUIRED):
            return v
        last = v
    raise ValueError(f"{model} returned an incomplete summary after 3 attempts; "
                     f"got keys={list((last or {}).keys())}")


# ---------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("run_dir")
    ap.add_argument("--model", default="deepseek-v4-pro",
                    help="NEUTRAL judge (not a benchmarked family): deepseek-v4-pro / claude-* / gpt-*")
    ap.add_argument("--save", action="store_true", help="write <episode>_cotsummary.json")
    ap.add_argument("--dry", action="store_true", help="print the distilled LLM input, no API call")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--arms", default="", help="comma list to include, e.g. g0,g1,g2")
    ap.add_argument("--rescore", action="store_true",
                    help="redo episodes that already have _cotsummary.json (default: skip)")
    args = ap.parse_args()

    if not args.dry:
        m = args.model.lower()
        need = ("DEEPSEEK_API_KEY" if m.startswith("deepseek")
                else "ANTHROPIC_API_KEY" if "claude" in m else "OPENAI_API_KEY")
        if not os.environ.get(need):
            sys.exit(f"{need} not set for judge model {args.model} (or use --dry)")

    files = sorted(f for f in glob.glob(f"{args.run_dir}/*/g[0-3]*_s*.json")
                   if all(x not in os.path.basename(f) for x in
                          ("scores", "trace", "codebook", "gene_map", "grouping", "sample_codebook")))
    arms = {a.strip() for a in args.arms.split(",") if a.strip()}
    if arms:
        files = [f for f in files if os.path.basename(f).split("_")[0] in arms]
    if args.save and not args.rescore and not args.dry:
        before = len(files)
        files = [f for f in files if not os.path.exists(f[:-5] + "_cotsummary.json")]
        if before - len(files):
            print(f"(skipping {before - len(files)} already-summarized; --rescore to redo)")
    if args.limit:
        files = files[:args.limit]

    done = fail = 0
    for f in files:
        label = os.path.basename(f)[:-5]
        try:
            rec = extract_episode(f)
            umsg = build_input(rec)
        except Exception as e:
            print(f"  !! {label} skipped (extract): {e}", file=sys.stderr); fail += 1; continue
        if args.dry:
            print(f"===== {label}  ({rec['cohort']} {rec['mode']}, {rec['n_calls']} calls, "
                  f"~{len(umsg)//4} tok) =====\n{umsg}\n")
            continue
        try:
            v = call_judge(umsg, args.model)
        except Exception as e:
            print(f"  !! {label} judge failed: {e}", file=sys.stderr); fail += 1; continue
        v = {"cohort": rec["cohort"], "arm": rec["mode"], "model": rec["model"], **v}
        print(f"{label:34} {rec['cohort']:5} {v['reasoning_strategy']:22} "
              f"id:{v['identity_derivation']:13} rigor:{v['validation_rigor']:6} "
              f"pivots:{v['num_pivots']}  {_trunc(v['overall_verdict'], 60)}")
        if args.save:
            json.dump(v, open(f[:-5] + "_cotsummary.json", "w"), indent=2)
        done += 1

    if not args.dry:
        print(f"\n  CoT summary: {done} done, {fail} failed  ({args.model})")


if __name__ == "__main__":
    main()
