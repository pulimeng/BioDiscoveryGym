"""
BioDiscoveryGym v3 scoring — v2 scores + agent trace.

Adds TraceReport: per-call tracking of model reasoning and tool use extracted
from the raw message log. No new score components — trace is descriptive only.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from .evaluator_v2 import EvaluatorV2, ScoreReport, ExaminationReport


# ---------------------------------------------------------------------------
# Trace data structures
# ---------------------------------------------------------------------------

@dataclass
class ToolCallRecord:
    call_num: int
    tool_name: str                 # run_code | submit_discovery | request_codebook
    reasoning_chars: int           # chars of assistant text before this call
    reasoning_preview: str         # first 300 chars of that text
    input_preview: str             # first 300 chars of code / input JSON
    input_lines: int               # line count (meaningful for run_code)
    output_chars: int              # chars of tool_result returned
    output_preview: str            # first 300 chars of tool_result
    # Runtime-captured fields (None if episode was run without v3 instrumentation)
    exec_time_s: float | None = None   # code execution wall time (from executor.timing_log)
    is_error: bool | None = None       # True if output started with "Error:"
    input_tokens: int | None = None    # API input tokens for the turn containing this call
    output_tokens: int | None = None   # API output tokens for the turn containing this call
    inferred_stage: int | None = None  # 0-6, inferred from preceding reasoning text

    def to_dict(self) -> dict:
        return self.__dict__.copy()


@dataclass
class TraceReport:
    # --- Summary ---
    total_calls: int = 0
    tool_counts: dict[str, int] = field(default_factory=dict)
    total_reasoning_chars: int = 0
    calls_with_reasoning: int = 0
    reasoning_tokens_approx: int = 0   # total_reasoning_chars // 4
    codebook_call_num: int | None = None
    submit_call_num: int | None = None

    # --- Behavioral flags (from code content) ---
    used_survival_analysis: bool = False
    used_clustering: bool = False
    used_differential_expression: bool = False
    used_pathway_analysis: bool = False
    referenced_external_db: bool = False  # depmap, gtex, string, opentargets, primekg

    # --- Behavioral flags (from reasoning text) ---
    mentioned_uncertainty: bool = False    # uncertain/unclear/unexpected/surprising
    revised_hypothesis: bool = False       # revise/reassign/reconsider/re-examine

    # --- Runtime token totals (None if not instrumented) ---
    total_input_tokens: int | None = None
    total_output_tokens: int | None = None
    total_exec_time_s: float | None = None
    error_call_count: int | None = None   # run_code calls that returned an error

    # --- Per-call log ---
    calls: list[ToolCallRecord] = field(default_factory=list)

    def to_dict(self) -> dict:
        d = {k: v for k, v in self.__dict__.items() if k != "calls"}
        d["calls"] = [c.to_dict() for c in self.calls]
        return d

    def pretty_print(self) -> str:
        token_line = (
            f"  Tokens (in/out)    : {self.total_input_tokens:,} / {self.total_output_tokens:,}"
            if self.total_input_tokens is not None else
            f"  Tokens             : not instrumented"
        )
        exec_line = (
            f"  Code exec time     : {self.total_exec_time_s:.1f}s total  ({self.error_call_count} errors)"
            if self.total_exec_time_s is not None else
            f"  Code exec time     : not instrumented"
        )
        lines = [
            f"{'='*60}",
            f"  Agent Trace",
            f"{'='*60}",
            f"  Total tool calls   : {self.total_calls}",
            f"  Tool breakdown     : {self.tool_counts}",
            f"  Codebook revealed  : call {self.codebook_call_num}",
            f"  Submission         : call {self.submit_call_num}",
            f"  Reasoning chars    : {self.total_reasoning_chars:,}  (~{self.reasoning_tokens_approx:,} tokens)",
            f"  Calls w/ reasoning : {self.calls_with_reasoning} / {self.total_calls}",
            token_line,
            exec_line,
            f"",
            f"  Behavioral flags:",
            f"    survival analysis    : {self.used_survival_analysis}",
            f"    clustering           : {self.used_clustering}",
            f"    diff expression      : {self.used_differential_expression}",
            f"    pathway analysis     : {self.used_pathway_analysis}",
            f"    external DB access   : {self.referenced_external_db}",
            f"    mentioned uncertainty: {self.mentioned_uncertainty}",
            f"    revised hypothesis   : {self.revised_hypothesis}",
        ]
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Core trace extraction
# ---------------------------------------------------------------------------

def _infer_stage(text: str) -> int | None:
    """Return the highest stage number (0-6) mentioned in text, or None."""
    for stage in range(6, -1, -1):
        if re.search(rf"\bstage\s*{stage}\b", text, re.IGNORECASE):
            return stage
    return None


def trace_episode(messages: list[dict], run_log: dict | None = None) -> TraceReport:
    """
    Extract a TraceReport from the raw Anthropic message list stored in the
    episode JSON. Each assistant turn can have text (reasoning) + tool_use
    blocks; each user turn has tool_result blocks.

    run_log (optional): dict with 'usage_log' (per-turn token counts) and
    'timing_log' (per-call execution times) saved at runtime by the agent.
    When present, per-call records are enriched with exec_time_s and token data.
    """
    report = TraceReport()
    call_num = 0

    # Index tool_results by tool_use_id for fast lookup
    result_map: dict[str, str] = {}
    for msg in messages:
        if msg.get("role") == "user":
            content = msg.get("content", [])
            if isinstance(content, list):
                for block in content:
                    if block.get("type") == "tool_result":
                        tid = block.get("tool_use_id", "")
                        raw = block.get("content", "")
                        # content may be a list of text blocks
                        if isinstance(raw, list):
                            raw = " ".join(b.get("text", "") for b in raw if isinstance(b, dict))
                        result_map[tid] = str(raw)

    all_code: list[str] = []
    all_reasoning: list[str] = []

    for msg in messages:
        if msg.get("role") != "assistant":
            continue

        content = msg.get("content", [])
        if not isinstance(content, list):
            continue

        # Collect text/thinking and tool_use blocks in order
        text_blocks: list[str] = []
        tool_blocks: list[dict] = []
        for block in content:
            btype = block.get("type")
            if btype == "text":
                text_blocks.append(block.get("text", ""))
            elif btype == "thinking":
                text_blocks.append(block.get("thinking", ""))
            elif btype == "tool_use":
                tool_blocks.append(block)

        reasoning_text = " ".join(text_blocks).strip()
        if reasoning_text:
            all_reasoning.append(reasoning_text)

        for tool_block in tool_blocks:
            tool_name = tool_block.get("name", "unknown")
            tool_id = tool_block.get("id", "")
            inp = tool_block.get("input", {})

            # Serialize input for preview
            if isinstance(inp, dict):
                code_str = inp.get("code", "") or json.dumps(inp, indent=2)
            else:
                code_str = str(inp)

            all_code.append(code_str)

            output_raw = result_map.get(tool_id, "")
            output_chars = len(output_raw)

            rec = ToolCallRecord(
                call_num=call_num,
                tool_name=tool_name,
                reasoning_chars=len(reasoning_text),
                reasoning_preview=reasoning_text[:300],
                input_preview=code_str[:300],
                input_lines=code_str.count("\n") + 1,
                output_chars=output_chars,
                output_preview=output_raw[:300],
            )
            report.calls.append(rec)

            # Track special calls
            # Codebook reveal: works for both explicit (`request_codebook` tool — historic)
            # and action-based gate (codebook payload appended to the 3rd record_observation
            # tool_result). Scanning the tool_result content for the reveal marker handles
            # both mechanisms transparently.
            if report.codebook_call_num is None:
                if tool_name == "request_codebook":
                    report.codebook_call_num = call_num
                elif "identified the gene codebook" in output_raw:
                    report.codebook_call_num = call_num
            if tool_name == "submit_discovery" and report.submit_call_num is None:
                report.submit_call_num = call_num

            report.tool_counts[tool_name] = report.tool_counts.get(tool_name, 0) + 1
            if reasoning_text:
                report.calls_with_reasoning += 1

            # Reset reasoning for next call in same turn (text belongs to first call)
            reasoning_text = ""
            call_num += 1

    # --- Summary ---
    report.total_calls = call_num
    report.total_reasoning_chars = sum(len(r) for r in all_reasoning)
    report.reasoning_tokens_approx = report.total_reasoning_chars // 4

    # --- Merge runtime logs when available ---
    if run_log:
        timing_log: list[dict] = run_log.get("timing_log", [])
        usage_log: list[dict] = run_log.get("usage_log", [])

        # timing_log is indexed by executor call_num — only run_code calls get timed
        timing_by_num = {t["call_num"]: t for t in timing_log}
        exec_call_num = 0
        for rec in report.calls:
            if rec.tool_name == "run_code":
                t = timing_by_num.get(exec_call_num, {})
                rec.exec_time_s = t.get("exec_time_s")
                rec.is_error = t.get("is_error")
                exec_call_num += 1

        # usage_log is per API turn; map by turn index to the first call in that turn
        # (a single assistant turn may have multiple tool_use blocks, all sharing the same tokens)
        turn_idx = 0
        prev_turn = -1
        for rec in report.calls:
            if turn_idx < len(usage_log):
                u = usage_log[turn_idx]
                rec.input_tokens = u.get("input_tokens")
                rec.output_tokens = u.get("output_tokens")
                # Infer stage from reasoning
                rec.inferred_stage = _infer_stage(rec.reasoning_preview)
            # Advance turn when the turn number changes
            if turn_idx < len(usage_log) and usage_log[turn_idx].get("turn", -1) != prev_turn:
                prev_turn = usage_log[turn_idx].get("turn", -1)
            # Move to next usage entry for the next distinct tool call
            turn_idx += 1

        if timing_log:
            report.total_exec_time_s = round(sum(t.get("exec_time_s", 0) for t in timing_log), 2)
            report.error_call_count = sum(1 for t in timing_log if t.get("is_error"))
        if usage_log:
            report.total_input_tokens = sum(u.get("input_tokens", 0) or 0 for u in usage_log)
            report.total_output_tokens = sum(u.get("output_tokens", 0) or 0 for u in usage_log)

    # --- Behavioral flags from code ---
    all_code_joined = "\n".join(all_code).lower()
    report.used_survival_analysis = bool(re.search(
        r"survival|kaplan|lifelines|kmf|log.rank|cox", all_code_joined
    ))
    report.used_clustering = bool(re.search(
        r"kmeans|k.means|nmf|spectral|agglomerative|dbscan|cluster", all_code_joined
    ))
    report.used_differential_expression = bool(re.search(
        r"ttest|t_test|mannwhitney|wilcoxon|rankdata|differential|fold.change|logfc|log2fc", all_code_joined
    ))
    report.used_pathway_analysis = bool(re.search(
        r"gsea|overrepresent|ora\b|enrichr|pathway|gmt|gene.set", all_code_joined
    ))
    report.referenced_external_db = bool(re.search(
        r"depmap|gtex|gnomad|string_ppi|opentargets|primekg|ot_tract|ot_known", all_code_joined
    ))

    # --- Behavioral flags from reasoning ---
    all_reasoning_joined = "\n".join(all_reasoning).lower()
    report.mentioned_uncertainty = bool(re.search(
        r"uncertain|unclear|unexpected|surprising|caveat|limitation|however.*not", all_reasoning_joined
    ))
    report.revised_hypothesis = bool(re.search(
        r"revis|reassign|reconsider|re.examin|update.*cluster|chang.*cluster|different.*cluster", all_reasoning_joined
    ))

    return report


# ---------------------------------------------------------------------------
# Phase 2 data extraction
# ---------------------------------------------------------------------------

def extract_examination_data(messages: list[dict]) -> tuple[str, list[str]]:
    """
    Extract Examination data from the serialized message log.

    Returns:
        data_lock_report: Text submitted via submit_data_lock(report=...).
                          Empty string if submit_data_lock was never called.
        examination_answers: All assistant text blocks after the data lock,
                             i.e. the Q1-Q4 answers.
    """
    data_lock_report = ""
    examination_answers: list[str] = []
    found_data_lock = False

    for msg in messages:
        role = msg.get("role")
        content = msg.get("content", [])
        if not isinstance(content, list):
            continue

        if role == "assistant":
            accumulated_text: list[str] = []
            for block in content:
                if not isinstance(block, dict):
                    continue
                btype = block.get("type")
                if btype == "tool_use":
                    name = block.get("name", "")
                    if name == "submit_data_lock":
                        data_lock_report = block.get("input", {}).get("report", "")
                        found_data_lock = True
                    if accumulated_text and found_data_lock:
                        examination_answers.extend(t for t in accumulated_text if t.strip())
                    accumulated_text = []
                elif btype in ("text", "thinking") and found_data_lock:
                    text = block.get("text") or block.get("thinking") or ""
                    if text.strip():
                        accumulated_text.append(text)

            if accumulated_text and found_data_lock:
                examination_answers.extend(t for t in accumulated_text if t.strip())

    return data_lock_report, examination_answers


# ---------------------------------------------------------------------------
# V3 evaluator
# ---------------------------------------------------------------------------

class EvaluatorV3(EvaluatorV2):
    """
    V2 scorer + agent trace + Phase 2 scoring. Call score_and_trace() to get both reports.
    """

    def score_and_trace(
        self,
        discovery: dict[str, Any],
        expression,
        metadata,
        mutation,
        rppa,
        sample_id_map: dict[str, str],
        cohort: str,
        messages: list[dict],
        run_log: dict | None = None,
    ) -> tuple[ScoreReport, TraceReport]:
        score_report = self.score(
            discovery=discovery,
            expression=expression,
            metadata=metadata,
            mutation=mutation,
            rppa=rppa,
            sample_id_map=sample_id_map,
            cohort=cohort,
        )

        # Examination: prefer data_lock_report captured at runtime; fall back to extraction.
        data_lock_report = discovery.get("data_lock_report", "")
        extracted_lock, examination_answers = extract_examination_data(messages)
        data_lock_report = data_lock_report or extracted_lock

        # Only attach examination report if examination actually ran (Data Lock
        # text or Q1-Q4 answers exist). When --no-examination was passed (TCGA
        # default), keep `score_report.examination = None` so the grand-total
        # ceiling correctly drops from 23 to 18 instead of keeping a phantom
        # 5-pt zero-scored section.
        examination_report = self.score_examination(data_lock_report, examination_answers)
        if examination_report.data_lock_length > 0 or examination_report.n_examination_answers > 0:
            score_report.examination = examination_report

        trace_report = trace_episode(messages, run_log=run_log)
        return score_report, trace_report
