"""
ClaudeAgentTarget: runs a target discovery session using the Anthropic API tool-use loop.

Three phases:
  Phase 1 (anonymized):  run_code + submit_target_discovery. All genes GENE_XXXXX.
  Phase 2 (validation):  V1–V4 validation design questions injected after submission.
                         run_code available. Genes still GENE_XXXXX.
  Phase 3 (revelation):  Real gene symbols revealed for top candidates. Pathway databases
                         added to namespace. Agent answers R1–R4 and calls revise_submission.

The agent never sees real gene symbols during Phase 1 or 2.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import anthropic

from biodiscoverygym.phases.target_discovery import (
    TASK_PROMPT, SUBMIT_TOOL, REVISE_TOOL, format_revelation_prompt,
)
from biodiscoverygym.utils.skills import CONSULT_SKILL_TOOL as _CONSULT_SKILL_TOOL

# Defaults — can be overridden per-run for v2
_DEFAULT_TASK_PROMPT = TASK_PROMPT
_DEFAULT_SUBMIT_TOOL = SUBMIT_TOOL

_RUN_CODE_TOOL: dict = {
    "name": "run_code",
    "description": (
        "Execute Python code in the analysis environment. "
        "Variables persist between calls. Returns stdout as a string."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "code": {
                "type": "string",
                "description": "Python code to execute.",
            }
        },
        "required": ["code"],
    },
}


class ClaudeAgentTarget:
    """
    Runs a target discovery session via the Anthropic API tool-use loop.

    Environment variables pre-loaded into the code sandbox:
      depmap_crispr, depmap_expr, depmap_meta — DepMap 23Q4 (gene-anonymized)
      gtex_median                             — GTEx v8 median tissue expression (gene-anonymized)
      gnomad                                  — gnomAD v2.1.1 constraint metrics (gene-anonymized)
      output_dir                              — Path for saving plots/tables

    Optional phase2_prompt: injected as a user message after submit_target_discovery.
    The agent answers in text (+ run_code if needed). No second submit tool required.

    Optional phase3: after Phase 2 (or Phase 1 if no Phase 2), real gene symbols are
    revealed for top candidates, pathway databases are added, and the agent calls
    revise_submission to complete R1–R4.
    """

    def __init__(
        self,
        model: str = "claude-sonnet-4-6",
        max_tool_calls: int = 50,
        data_dir: str | Path = "data",
        verbose: bool = True,
        indication: str = "cancer",
        phase2_prompt: str | None = None,
        phase2_max_calls: int = 20,
        phase3: bool = False,
        phase3_max_calls: int = 20,
        task_prompt: str | None = None,
        submit_tool: dict | None = None,
        skill: str | None = None,
    ):
        self.model = model
        self.max_tool_calls = max_tool_calls
        self.data_dir = Path(data_dir)
        self.verbose = verbose
        self.indication = indication
        self.phase2_prompt = phase2_prompt
        self.phase2_max_calls = phase2_max_calls
        self.phase3 = phase3
        self.phase3_max_calls = phase3_max_calls
        self.client = anthropic.Anthropic()
        _prompt = task_prompt or _DEFAULT_TASK_PROMPT
        _tool = submit_tool or _DEFAULT_SUBMIT_TOOL
        self._system_prompt = _prompt.format(
            max_tool_calls=max_tool_calls,
            force_submit_at=int(max_tool_calls * 0.85),
            indication=indication,
        )
        # Optional reasoning skill (progressive disclosure via consult_skill tool): the
        # agent sees only a name+description pitch and decides for itself whether to call
        # consult_skill to load the SKILL.md body. The tool call is an authoritative,
        # confound-free signal of whether the agent consulted it. Nothing is forced.
        self.skill = skill
        self._skill_name = None
        self._skill_consulted = False
        if self.skill:
            from biodiscoverygym.utils.skills import resolve, skill_pitch, load_meta
            resolve(self.skill)  # fail fast on a bad name/path
            self._skill_name = load_meta(self.skill).get("name", self.skill)
            self._system_prompt += skill_pitch(self.skill)
            if verbose:
                print(f"[ClaudeAgentTarget] Skill offered (agent-invoked via consult_skill): {self._skill_name}")
        self._tools = [_RUN_CODE_TOOL, _tool]
        if self.skill:
            self._tools.append(_CONSULT_SKILL_TOOL)
        self._submit_tool = _tool

    def run(
        self,
        session_id: str,
        output_dir: Path | None = None,
        executor=None,
    ) -> tuple[dict[str, Any], dict[str, Any], list]:
        """
        Run the tool-use loop through all active phases.

        Returns (submission dict, revision dict, message history).
        revision is empty if Phase 3 was not run or not completed.
        """
        from biodiscoverygym.executor import CodeExecutor
        if executor is None:
            executor = CodeExecutor(data_dir=self.data_dir, output_dir=output_dir)

        messages: list[dict] = [
            {
                "role": "user",
                "content": "Begin. Work through each stage in order and show your reasoning.",
            }
        ]

        tool_call_count = 0
        submission: dict | None = None
        revision: dict | None = None

        phase2_active = False
        phase2_call_count = 0

        phase3_active = False
        phase3_call_count = 0

        current_tools = [_RUN_CODE_TOOL, self._submit_tool]
        if self.skill:
            current_tools.append(_CONSULT_SKILL_TOOL)
        self._log(f"[ClaudeAgentTarget] Starting session {session_id} (model={self.model})")

        while True:
            # Budget check
            if phase3_active:
                if phase3_call_count >= self.phase3_max_calls:
                    self._log(f"[ClaudeAgentTarget] Phase 3 budget exhausted ({self.phase3_max_calls} calls).")
                    break
            elif phase2_active:
                if phase2_call_count >= self.phase2_max_calls:
                    self._log(f"[ClaudeAgentTarget] Phase 2 budget exhausted ({self.phase2_max_calls} calls).")
                    if self.phase3 and submission:
                        phase2_active = False
                        phase3_active, current_tools = self._start_phase3(
                            messages, executor, submission
                        )
                        if not phase3_active:
                            break
                        continue
                    break
            else:
                if tool_call_count >= self.max_tool_calls:
                    self._log(f"[ClaudeAgentTarget] Hit max_tool_calls={self.max_tool_calls} without submission.")
                    break

            for attempt in range(3):
                try:
                    with self.client.messages.stream(
                        model=self.model,
                        system=self._system_prompt,
                        messages=messages,
                        tools=current_tools,
                        max_tokens=32000,
                    ) as stream:
                        response = stream.get_final_message()
                    break
                except Exception as e:
                    if attempt == 2:
                        raise
                    self._log(f"[ClaudeAgentTarget] Stream error (attempt {attempt+1}/3): {e} — retrying")

            phase_label = "P3" if phase3_active else ("P2" if phase2_active else "P1")
            call_n = phase3_call_count if phase3_active else (phase2_call_count if phase2_active else tool_call_count)
            self._log(
                f"[ClaudeAgentTarget] {phase_label} turn {call_n + 1}: "
                f"stop_reason={response.stop_reason}, "
                f"blocks={[b.type for b in response.content]}"
            )

            messages.append({"role": "assistant", "content": response.content})

            if response.stop_reason == "end_turn":
                if phase3_active:
                    self._log("[ClaudeAgentTarget] Phase 3 complete — agent finished.")
                elif phase2_active:
                    self._log("[ClaudeAgentTarget] Phase 2 complete — agent finished answering.")
                    if self.phase3 and submission:
                        phase2_active = False
                        phase3_active, current_tools = self._start_phase3(
                            messages, executor, submission
                        )
                        if phase3_active:
                            continue
                else:
                    self._log("[ClaudeAgentTarget] Model stopped — no submission made." if submission is None
                              else "[ClaudeAgentTarget] Submission made, model stopped.")
                    if self.phase3 and submission and not self.phase2_prompt:
                        phase3_active, current_tools = self._start_phase3(
                            messages, executor, submission
                        )
                        if phase3_active:
                            continue
                break

            if response.stop_reason == "max_tokens":
                self._log("[ClaudeAgentTarget] Hit max_tokens — nudging.")
                tool_results = [
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": "Response truncated — please retry this call.",
                    }
                    for block in response.content
                    if getattr(block, "type", None) == "tool_use"
                ]
                nudge = "Your previous response was cut off. Please continue from where you left off."
                content = (tool_results + [{"type": "text", "text": nudge}]) if tool_results else nudge
                messages.append({"role": "user", "content": content})
                continue

            if response.stop_reason != "tool_use":
                self._log(f"[ClaudeAgentTarget] Unexpected stop_reason: {response.stop_reason}")
                break

            tool_results = []
            submitted = False
            revised = False

            for block in response.content:
                if block.type != "tool_use":
                    continue

                if phase3_active:
                    phase3_call_count += 1
                elif phase2_active:
                    phase2_call_count += 1
                else:
                    tool_call_count += 1

                if block.name == "consult_skill":
                    from biodiscoverygym.utils.skills import load_body
                    requested = block.input.get("name", "") or self.skill
                    try:
                        content = load_body(self.skill)
                        self._skill_consulted = True
                        self._log(f"[consult_skill] Agent loaded skill {self._skill_name!r}")
                    except Exception as e:  # noqa: BLE001 — surface to the agent
                        content = f"Could not load skill {requested!r}: {e}"
                        self._log(f"[consult_skill] Load failed: {e}")
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": content,
                    })

                elif block.name == "run_code":
                    code = block.input.get("code", "")
                    total = tool_call_count + phase2_call_count + phase3_call_count
                    self._log(f"[run_code #{total}] {code[:120].strip()!r}")
                    output = executor.execute(code)
                    self._log(f"  → {output[:200].strip()!r}")
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": output,
                    })

                elif block.name == "submit_target_discovery":
                    submission = dict(block.input)
                    self._log(
                        f"[submit_target_discovery] candidates={submission.get('top_candidates', [])[:3]}"
                    )
                    if self.phase2_prompt and not phase2_active:
                        phase2_active = True
                        self._log("[ClaudeAgentTarget] Injecting Phase 2 validation questions.")
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": self.phase2_prompt,
                        })
                    else:
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": "Submission received. Session complete.",
                        })
                        submitted = True

                elif block.name == "revise_submission":
                    revision = dict(block.input)
                    self._log(
                        f"[revise_submission] revised_candidates={revision.get('revised_candidates', [])[:3]}, "
                        f"ranking_changed={revision.get('ranking_changed')}"
                    )
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": "Revision received. Phase 3 complete.",
                    })
                    revised = True

            if tool_results:
                messages.append({"role": "user", "content": tool_results})

            if revised:
                break

            if submitted:
                if self.phase3 and not self.phase2_prompt:
                    phase3_active, current_tools = self._start_phase3(
                        messages, executor, submission
                    )
                    if phase3_active:
                        continue
                break

        return submission or {}, revision or {}, messages

    def _start_phase3(
        self,
        messages: list,
        executor,
        submission: dict,
    ) -> tuple[bool, list]:
        """
        Inject revelation prompt and pathway namespace. Returns (phase3_active, tools).
        """
        if not hasattr(executor, "gene_map") or not hasattr(executor, "add_pathway_namespace"):
            self._log("[ClaudeAgentTarget] Phase 3 skipped — executor missing gene_map or add_pathway_namespace.")
            return False, [_RUN_CODE_TOOL, SUBMIT_TOOL]

        top_candidates = submission.get("top_candidates", [])
        if not top_candidates:
            self._log("[ClaudeAgentTarget] Phase 3 skipped — no candidates in submission.")
            return False, [_RUN_CODE_TOOL, SUBMIT_TOOL]

        self._log("[ClaudeAgentTarget] Starting Phase 3 — injecting gene revelation + pathway databases.")
        try:
            executor.add_pathway_namespace(self.data_dir)
        except Exception as e:
            self._log(f"[ClaudeAgentTarget] Phase 3: add_pathway_namespace failed: {e}")

        revelation = format_revelation_prompt(top_candidates, executor.gene_map)
        messages.append({"role": "user", "content": [{"type": "text", "text": revelation}]})
        return True, [_RUN_CODE_TOOL, REVISE_TOOL]

    def _log(self, msg: str) -> None:
        if self.verbose:
            print(msg)
