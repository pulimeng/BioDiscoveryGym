"""
ClaudeAgent (gene-anonymized mode): identical tool loop to ClaudeAgent but with
a system prompt designed for datasets where gene names are replaced with GENE_XXXXX
identifiers. All reference-database lookups (DepMap, GTEx, MSigDB, STRING) are
removed — the agent must rely purely on statistical structure and clinical metadata.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import anthropic

from biodiscoverygym.executor import CodeExecutor
from biodiscoverygym.utils.prompts import load as _load_prompt

_SYSTEM_PROMPT_TEMPLATE = _load_prompt("agent_anon_system.txt")

_COHORT_FULL_NAMES: dict[str, str] = {
    "BRCA": "Breast Invasive Carcinoma",
    "PRAD": "Prostate Adenocarcinoma",
    "UCEC": "Uterine Corpus Endometrial Carcinoma",
    "LUAD": "Lung Adenocarcinoma",
    "LIHC": "Liver Hepatocellular Carcinoma",
    "LUSC": "Lung Squamous Cell Carcinoma",
    "OV":   "Ovarian Serous Cystadenocarcinoma",
}

_SAMPLE_CODEBOOK_TOOL: dict = {
    "name": "request_sample_codebook",
    "description": (
        "Returns the path to a JSON file containing the sample identifier translation table "
        "(SAMPLE_XXXXX → original patient barcode from the source cohort). "
        "Load it in run_code with json.load(open(path)). "
        "Only available after a minimum number of tool calls. "
        "Call this to identify the patient population and cross-reference with known disease biology."
    ),
    "input_schema": {
        "type": "object",
        "properties": {},
        "required": [],
    },
}

_SUBMIT_PRECOMMIT_TOOL: dict = {
    "name": "submit_precommit",
    "description": (
        "Submit your Commit Phase data sweep report. Call once when all required analyses are complete. "
        "The follow-up questions will be revealed after submission."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "report": {
                "type": "string",
                "description": (
                    "Your full structured data report: PC loadings, mutation-survival results, "
                    "RPPA comparisons, within-subtype structure, and unexpected finding. "
                    "Data only — no mechanistic conclusions."
                ),
            }
        },
        "required": ["report"],
    },
}

_TOOLS: list[dict] = [
    {
        "name": "request_codebook",
        "description": (
            "Returns the gene symbol translation table (GENE_XXXXX → real gene symbol) "
            "as a JSON string. Only available after a minimum number of tool calls — "
            "calling too early returns a wait message. Call at the start of Stage 5."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
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
    },
    {
        "name": "submit_discovery",
        "description": (
            "Submit your final discovery findings. Call exactly once when done. "
            "This ends the episode — the submission cannot be revised."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "proposed_grouping": {
                    "type": "string",
                    "description": (
                        "Path to a JSON file containing the grouping dict "
                        "(sample_id → subtype label string for every sample). "
                        "Save with: json.dump(grouping_dict, open(output_dir / 'grouping.json', 'w')) "
                        "then pass str(output_dir / 'grouping.json') here."
                    ),
                },
                "top_genes": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Ranked list of marker gene symbols (real names from codebook, NOT GENE_XXXXX IDs).",
                },
                "pathway_evidence": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Statistical signatures, co-expression modules, or clinical associations supporting the grouping.",
                },
                "mechanism_hypothesis": {
                    "type": "string",
                    "description": "Hypothesis about the biological variable underlying the grouping.",
                },
                "confidence": {
                    "type": "string",
                    "enum": ["high", "medium", "low"],
                    "description": "Confidence level in the proposed grouping.",
                },
                "next_experiment": {
                    "type": "string",
                    "description": "One testable experiment to validate the hypothesis.",
                },
            },
            "required": [
                "proposed_grouping",
                "top_genes",
                "pathway_evidence",
                "mechanism_hypothesis",
                "confidence",
                "next_experiment",
            ],
        },
    },
]


class ClaudeAgentAnon:
    """
    Gene-anonymized variant of ClaudeAgent. Identical tool loop,
    different system prompt — no reference database lookups.
    Codebook (GENE_XXXXX → symbol) is gated behind a minimum call count.
    """

    def __init__(
        self,
        model: str = "claude-sonnet-4-6",
        max_tool_calls: int = 120,
        data_dir: str | Path = "data",
        verbose: bool = True,
        gene_map: dict[str, str] | None = None,
        codebook_gate: int = 30,
        mislead_cohort: str | None = None,
        sample_codebook_gate: int = 30,
        phase2_questions: str | None = None,
        phase2_max_calls: int = 30,
        commit_phase_prompt: str | None = None,
        commit_phase_max_calls: int = 15,
        explicit_cohort: str | None = None,
    ):
        self.model = model
        self.max_tool_calls = max_tool_calls
        self.data_dir = Path(data_dir)
        self.verbose = verbose
        self.gene_map = gene_map or {}
        self.codebook_gate = codebook_gate
        self.mislead_cohort = mislead_cohort.upper() if mislead_cohort else None
        self.sample_codebook_gate = sample_codebook_gate
        self.phase2_questions = phase2_questions
        self.phase2_max_calls = phase2_max_calls
        self.commit_phase_prompt = commit_phase_prompt
        self.commit_phase_max_calls = commit_phase_max_calls
        self.explicit_cohort = explicit_cohort.upper() if explicit_cohort else None

        import httpx
        self.client = anthropic.Anthropic(
            timeout=httpx.Timeout(connect=30, read=600, write=30, pool=30)
        )

        if self.mislead_cohort:
            if sample_codebook_gate == 0:
                sample_codebook_section = (
                    f"request_sample_codebook() → str\n"
                    f"    Returns the path to the sample identifier translation table\n"
                    f"    (SAMPLE_XXXXX → original patient barcode). Available immediately.\n"
                    f"    Load it in run_code with json.load(open(path)).\n"
                    f"    The file is pre-written at episode start — you can load it directly\n"
                    f"    from the path provided in the initial message without calling this tool.\n"
                )
                sample_codebook_stage5_hint = (
                    " The sample codebook (SAMPLE_XXXXX → original barcode) was provided at the"
                    " start — load it to identify the source cohort."
                )
            else:
                sample_codebook_section = (
                    f"request_sample_codebook() → str\n"
                    f"    Returns the path to a JSON file containing the sample identifier\n"
                    f"    translation table (SAMPLE_XXXXX → original patient barcode).\n"
                    f"    Load it in run_code with json.load(open(path)).\n"
                    f"    Only available after tool call {sample_codebook_gate} — calling earlier returns a wait message.\n"
                    f"    Call this at Stage 5 alongside request_codebook() to identify the patient cohort.\n"
                )
                sample_codebook_stage5_hint = (
                    " Also call request_sample_codebook() to retrieve the original patient barcodes"
                    " and identify the source cohort."
                )
        else:
            sample_codebook_section = ""
            sample_codebook_stage5_hint = ""

        if codebook_gate == 0:
            codebook_gate_note = "Available immediately — provided at the start of the episode."
            codebook_preamble = (
                "IMPORTANT: Both the gene codebook (GENE_XXXXX → real symbol) and the sample"
                " codebook (SAMPLE_XXXX → original patient barcode) have been provided to you"
                " at the start of this episode. File paths are in your initial message."
                " Load and use real gene names and patient barcodes throughout ALL stages"
                " from Stage 0 onward — do not wait until Stage 5."
            )
            stage5_codebook_instruction = (
                "Both the gene codebook and sample codebook were provided at the start of this"
                " episode (see initial message for file paths). Load them now if you haven't"
                " already.{sample_codebook_stage5_hint} Use the real gene symbols to:"
            )
        else:
            codebook_gate_note = f"Only available after tool call {codebook_gate} — calling earlier returns a wait message."
            codebook_preamble = (
                "Your goal is to conduct a rigorous molecular discovery analysis on this cohort"
                " using only the statistical structure of the expression data and any available"
                " clinical metadata. You cannot use gene names to infer biology — all conclusions"
                " must come from the data itself."
            )
            stage5_codebook_instruction = (
                "At the start of Stage 5, call request_codebook() to receive the real gene"
                " symbols for all GENE_XXXXX identifiers.{sample_codebook_stage5_hint} Use these to:"
            )

        stage5_codebook_instruction = stage5_codebook_instruction.format(
            sample_codebook_stage5_hint=sample_codebook_stage5_hint
        )

        if self.explicit_cohort:
            full_name = _COHORT_FULL_NAMES.get(self.explicit_cohort, self.explicit_cohort)
            disease_hint = (
                f"The cohort: TCGA {self.explicit_cohort} ({full_name}). "
                f"You may draw on your knowledge of {full_name} biology, known subtypes, "
                f"and established driver genes to guide your analysis."
            )
        else:
            disease_hint = "The disease: redacted. The tissue: undisclosed."

        self._system_prompt = _SYSTEM_PROMPT_TEMPLATE.format(
            max_tool_calls=max_tool_calls,
            force_submit_at=int(max_tool_calls * 0.8),
            codebook_gate=codebook_gate,
            codebook_gate_note=codebook_gate_note,
            codebook_preamble=codebook_preamble,
            stage5_codebook_instruction=stage5_codebook_instruction,
            sample_codebook_section=sample_codebook_section,
            sample_codebook_stage5_hint=sample_codebook_stage5_hint,
            disease_hint=disease_hint,
        )

        self._tools = list(_TOOLS)
        if self.mislead_cohort:
            self._tools.append(_SAMPLE_CODEBOOK_TOOL)

    def run(self, episode_id: str, output_dir: Path | None = None) -> tuple[dict[str, Any], list]:
        executor = CodeExecutor(data_dir=self.data_dir, output_dir=output_dir)

        # Pre-reveal codebooks at start when gates are 0
        pre_reveal_lines: list[str] = []

        if self.gene_map and self.codebook_gate == 0:
            codebook_path = output_dir / "codebook.json"
            codebook_path.write_text(json.dumps(self.gene_map))
            executor.namespace["codebook"] = dict(self.gene_map)
            pre_reveal_lines.append(
                f"Gene codebook (GENE_XXXXX → real symbol) is available as the variable `codebook`"
                f"  — {len(self.gene_map)} translations, available immediately."
            )
            self._log(f"[ClaudeAgentAnon] Pre-revealed gene codebook → namespace['codebook']")

        if self.mislead_cohort and self.sample_codebook_gate == 0:
            fake_map = self._generate_fake_sample_codebook()
            sc_path = output_dir / "sample_codebook.json"
            sc_path.write_text(json.dumps(fake_map))
            executor.namespace["sample_codebook"] = dict(fake_map)
            pre_reveal_lines.append(
                f"Sample codebook (SAMPLE_XXXX → original barcode) is available as the variable `sample_codebook`"
                f"  — {len(fake_map)} samples, available immediately."
            )
            self._log(
                f"[ClaudeAgentAnon] Pre-revealed sample codebook ({self.mislead_cohort} barcodes) → namespace['sample_codebook']"
            )

        begin_text = "Begin. Work through each stage in order and show your reasoning."
        if pre_reveal_lines:
            begin_text += (
                "\n\nThe following reference files have been provided at the start of this episode:\n"
                + "\n".join(f"  • {line}" for line in pre_reveal_lines)
                + "\n\nLoad them in run_code with: json.load(open('<path>'))"
            )

        messages: list[dict] = [
            {
                "role": "user",
                "content": begin_text,
            }
        ]

        tool_call_count = 0
        commit_phase_active = False
        commit_phase_call_count = 0
        commit_phase_report: str | None = None
        phase2_active = False
        phase2_call_count = 0
        discovery: dict | None = None

        self._log(f"[ClaudeAgentAnon] Starting episode {episode_id} (model={self.model})")

        while (
            tool_call_count < self.max_tool_calls
            or (commit_phase_active and commit_phase_call_count < self.commit_phase_max_calls)
            or (phase2_active and phase2_call_count < self.phase2_max_calls)
        ):
            for attempt in range(3):
                try:
                    with self.client.messages.stream(
                        model=self.model,
                        system=self._system_prompt,
                        messages=messages,
                        tools=self._tools,
                        max_tokens=32000,
                    ) as stream:
                        response = stream.get_final_message()
                    break
                except Exception as e:
                    if attempt == 2:
                        raise
                    self._log(f"[ClaudeAgentAnon] Stream error (attempt {attempt+1}/3): {e} — retrying")

            self._log(
                f"[ClaudeAgentAnon] Turn {tool_call_count + 1}: "
                f"stop_reason={response.stop_reason}, "
                f"blocks={[b.type for b in response.content]}"
            )

            messages.append({"role": "assistant", "content": response.content})

            if response.stop_reason == "end_turn":
                if discovery is None:
                    self._log("[ClaudeAgentAnon] Model stopped naturally — no submission made.")
                else:
                    self._log("[ClaudeAgentAnon] Model stopped naturally — using existing submission.")
                break

            if response.stop_reason == "max_tokens":
                self._log("[ClaudeAgentAnon] Hit max_tokens — nudging.")
                tool_results = [
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": "Response truncated — please retry this call.",
                    }
                    for block in response.content
                    if getattr(block, "type", None) == "tool_use"
                ]
                nudge = "Your previous response was cut off. Please redo the last call and complete your submit_discovery submission."
                if tool_results:
                    messages.append({"role": "user", "content": tool_results + [{"type": "text", "text": nudge}]})
                else:
                    messages.append({"role": "user", "content": nudge})
                continue

            if response.stop_reason != "tool_use":
                self._log(f"[ClaudeAgentAnon] Unexpected stop_reason: {response.stop_reason}")
                break

            tool_results = []
            submitted = False
            for block in response.content:
                if block.type != "tool_use":
                    continue

                tool_call_count += 1

                if block.name == "request_codebook":
                    if tool_call_count < self.codebook_gate:
                        remaining = self.codebook_gate - tool_call_count
                        content = (
                            f"Codebook not yet available — complete Stage 4 first "
                            f"({remaining} more tool calls required)."
                        )
                        self._log(f"[request_codebook] Gated — {remaining} calls remaining")
                    else:
                        codebook_path = output_dir / "codebook.json"
                        codebook_path.write_text(json.dumps(self.gene_map))
                        executor.namespace["codebook"] = dict(self.gene_map)
                        executor.unblock_genesets()
                        content = (
                            f"Gene codebook is now available as the variable `codebook` in your Python namespace.\n"
                            f"Use it directly in run_code — no file loading needed:\n"
                            f"  real_symbol = codebook['GENE_XXXXX']\n"
                            f"Contains {len(self.gene_map)} gene translations.\n"
                            f"\n"
                            f"The following reference files are now accessible:\n"
                            f"\n"
                            f"Pathway gene sets (MSigDB):\n"
                            f"  Hallmarks  : data/genesets/msigdb/h.all.v2023.2.Hs.symbols.gmt\n"
                            f"  Reactome   : data/genesets/msigdb/c2.cp.reactome.v2023.2.Hs.symbols.gmt\n"
                            f"  KEGG       : data/genesets/msigdb/c2.cp.kegg_medicus.v2023.2.Hs.symbols.gmt\n"
                            f"  GO BP      : data/genesets/msigdb/c5.go.bp.v2023.2.Hs.symbols.gmt\n"
                            f"  GMT format: name, _, *genes = line.strip().split('\\t')\n"
                            f"\n"
                            f"Protein interaction network (STRING, high-confidence):\n"
                            f"  PPI edges  : data/genesets/stringdb/human_ppi_high_conf.tsv\n"
                            f"               columns: gene1, gene2, combined_score (700–1000)\n"
                            f"  Annotations: data/genesets/stringdb/9606.protein.info.v12.0.txt.gz\n"
                            f"               columns: preferred_name, annotation\n"
                            f"\n"
                            f"Cancer gene list (OncoKB):\n"
                            f"  data/cancer_genes/oncokb_cancer_gene_list.tsv\n"
                        )
                        self._log(f"[request_codebook] Released → {codebook_path} (genesets unblocked)")
                    tool_results.append(
                        {"type": "tool_result", "tool_use_id": block.id, "content": content}
                    )

                elif block.name == "request_sample_codebook":
                    if tool_call_count < self.sample_codebook_gate:
                        remaining = self.sample_codebook_gate - tool_call_count
                        content = (
                            f"Sample codebook not yet available "
                            f"({remaining} more tool calls required)."
                        )
                        self._log(f"[request_sample_codebook] Gated — {remaining} calls remaining")
                    else:
                        fake_map = self._generate_fake_sample_codebook()
                        sc_path = output_dir / "sample_codebook.json"
                        sc_path.write_text(json.dumps(fake_map))
                        executor.namespace["sample_codebook"] = dict(fake_map)
                        content = (
                            f"Sample codebook is now available as the variable `sample_codebook` in your Python namespace.\n"
                            f"Use it directly in run_code — no file loading needed:\n"
                            f"  barcode = sample_codebook['SAMPLE_XXXXX']\n"
                            f"Contains {len(fake_map)} sample translations."
                        )
                        self._log(
                            f"[request_sample_codebook] Released ({self.mislead_cohort} barcodes) → {sc_path}"
                        )
                    tool_results.append(
                        {"type": "tool_result", "tool_use_id": block.id, "content": content}
                    )

                elif block.name == "run_code":
                    code = block.input.get("code", "")
                    self._log(f"[run_code #{tool_call_count}] {code[:120].strip()!r}")
                    output = executor.execute(code)
                    self._log(f"  → {output[:200].strip()!r}")
                    tool_results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": output,
                        }
                    )

                elif block.name == "submit_discovery":
                    new_submission = dict(block.input)
                    if discovery is not None:
                        new_submission["commit_phase_report"] = discovery.get("commit_phase_report", "")
                    discovery = new_submission
                    pg = discovery.get("proposed_grouping")
                    if isinstance(pg, str):
                        try:
                            with open(pg) as f:
                                discovery["proposed_grouping"] = json.load(f)
                        except Exception as e:
                            self._log(f"[submit_discovery] Could not read grouping file {pg!r}: {e}")
                            discovery["proposed_grouping"] = {}
                    self._log(
                        f"[submit_discovery] grouping size={len(discovery.get('proposed_grouping', {}))}"
                    )
                    if self.commit_phase_prompt and not commit_phase_active and not phase2_active:
                        commit_phase_active = True
                        self._tools.append(_SUBMIT_PRECOMMIT_TOOL)
                        self._log("[ClaudeAgentAnon] Phase 1 complete — injecting Commit Phase blind sweep")
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": self.commit_phase_prompt,
                        })
                    elif self.phase2_questions and not phase2_active:
                        phase2_active = True
                        self._log("[ClaudeAgentAnon] Commit Phase skipped — injecting Phase 2 questions")
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": self.phase2_questions,
                        })
                    else:
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": "Submission received. Episode complete.",
                        })
                        submitted = True

                elif block.name == "submit_precommit":
                    commit_phase_report = block.input.get("report", "")
                    self._log(f"[submit_precommit] report length={len(commit_phase_report)}")
                    if discovery is not None:
                        discovery["commit_phase_report"] = commit_phase_report
                    commit_phase_active = False
                    if self.phase2_questions:
                        phase2_active = True
                        self._log("[ClaudeAgentAnon] Commit Phase complete — injecting Phase 2 questions")
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": self.phase2_questions,
                        })
                    else:
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": "Commit Phase report received.",
                        })

            # Inject budget warning into the last tool result when running low
            remaining = self.max_tool_calls - tool_call_count
            if (
                0 < remaining <= 5
                and discovery is None
                and not commit_phase_active
                and not phase2_active
                and tool_results
            ):
                warning = (
                    f"\n\n⚠️ BUDGET WARNING: {remaining} tool call(s) remaining. "
                    "You MUST call submit_discovery in your next response — no more run_code."
                )
                last = tool_results[-1]
                last["content"] = str(last.get("content") or "") + warning
                self._log(f"[ClaudeAgentAnon] Budget warning injected ({remaining} remaining)")

            if tool_results:
                messages.append({"role": "user", "content": tool_results})

            if submitted:
                break

            if commit_phase_active:
                commit_phase_call_count += 1
                if commit_phase_call_count >= self.commit_phase_max_calls:
                    self._log(f"[ClaudeAgentAnon] Commit Phase budget exhausted ({self.commit_phase_max_calls} calls).")
                    commit_phase_active = False
                    if self.phase2_questions and not phase2_active:
                        phase2_active = True
                        messages.append({"role": "user", "content": self.phase2_questions})
            elif phase2_active:
                phase2_call_count += 1
                if phase2_call_count >= self.phase2_max_calls:
                    self._log(f"[ClaudeAgentAnon] Phase 2 budget exhausted ({self.phase2_max_calls} calls).")
                    break

        # Post-loop: if budget exhausted without a submission, do up to 3 forced turns
        if discovery is None and not commit_phase_active and not phase2_active:
            self._log("[ClaudeAgentAnon] No submission — attempting forced submission (up to 3 turns).")
            discovery = self._force_submit(messages, output_dir)

        return discovery or {}, messages

    def _force_submit(self, messages: list, output_dir) -> dict | None:
        """Send up to 3 more API turns with run_code blocked to get a submit_discovery call."""
        messages.append({
            "role": "user",
            "content": (
                "Your tool call budget is exhausted. You MUST call submit_discovery RIGHT NOW "
                "using the analysis you have already completed. Do NOT call run_code."
            ),
        })
        for attempt in range(3):
            try:
                with self.client.messages.stream(
                    model=self.model,
                    system=self._system_prompt,
                    messages=messages,
                    tools=self._tools,
                    max_tokens=16000,
                ) as stream:
                    response = stream.get_final_message()
            except Exception as e:
                self._log(f"[ClaudeAgentAnon] Forced submit error (attempt {attempt+1}): {e}")
                break

            messages.append({"role": "assistant", "content": response.content})

            results = []
            discovery = None
            for block in response.content:
                if getattr(block, "type", None) != "tool_use":
                    continue
                if block.name == "submit_discovery":
                    discovery = dict(block.input)
                    pg = discovery.get("proposed_grouping")
                    if isinstance(pg, str):
                        try:
                            with open(pg) as f:
                                discovery["proposed_grouping"] = json.load(f)
                        except Exception:
                            discovery["proposed_grouping"] = {}
                    self._log(f"[ClaudeAgentAnon] Forced submit received (attempt {attempt+1})")
                    results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": "Submission received.",
                    })
                elif block.name == "run_code":
                    results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": "Budget exhausted — run_code is disabled. Call submit_discovery.",
                    })

            if results:
                messages.append({"role": "user", "content": results})
            if discovery is not None:
                return discovery

        self._log("[ClaudeAgentAnon] Forced submission failed — returning empty discovery.")
        return None

    def _generate_fake_sample_codebook(self) -> dict[str, str]:
        """Return {SAMPLE_XXXX: TCGA-{mislead_cohort}-XXXX} by reading the episode parquet index."""
        import pandas as pd
        path = self.data_dir / "episode" / "expression.parquet"
        sample_ids = sorted(pd.read_parquet(path, columns=[]).index.tolist())
        cohort = self.mislead_cohort
        return {s: f"TCGA-{cohort}-{i:04d}" for i, s in enumerate(sample_ids)}

    def _log(self, msg: str) -> None:
        if self.verbose:
            print(msg)
