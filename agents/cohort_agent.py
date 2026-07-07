"""
CohortAgent: cohort-discovery agent with per-mode system prompts (G0/G1/G2).
Gene names are replaced with GENE_XXXXX identifiers; the codebook is gated or
pre-revealed depending on mode. All reference-database lookups (DepMap, GTEx,
MSigDB, STRING) are removed — the agent must rely on statistical structure and
clinical metadata.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agents.adapters import get_adapter

from biodiscoverygym.executor import CodeExecutor
from biodiscoverygym.utils.prompts import load as _load_prompt
from biodiscoverygym.utils.skills import CONSULT_SKILL_TOOL as _CONSULT_SKILL_TOOL

_COHORT_FULL_NAMES: dict[str, str] = {
    "BRCA": "Breast Invasive Carcinoma",
    "PRAD": "Prostate Adenocarcinoma",
    "UCEC": "Uterine Corpus Endometrial Carcinoma",
    "LUAD": "Lung Adenocarcinoma",
    "LIHC": "Liver Hepatocellular Carcinoma",
    "LUSC": "Lung Squamous Cell Carcinoma",
    "OV":   "Ovarian Serous Cystadenocarcinoma",
    "OS":   "Osteosarcoma (SGH-OS, Jia et al. 2022)",
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

_SUBMIT_DATA_LOCK_TOOL: dict = {
    "name": "submit_data_lock",
    "description": (
        "Submit your Data Lock report — the blind quantitative sweep required before "
        "examination questions are revealed. Call once when all required analyses are complete."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "report": {
                "type": "string",
                "description": (
                    "Your full structured data report: PC loadings, survival by subtype, "
                    "mutation enrichment, and unexpected finding. "
                    "Data only — no mechanistic conclusions."
                ),
            }
        },
        "required": ["report"],
    },
}

_RECORD_OBSERVATION_TOOL: dict = {
    "name": "record_observation",
    "description": (
        "Record a structured checkpoint of your evolving hypothesis. "
        "REQUIRED at the end of every stage (0–5) before advancing. "
        "This creates an auditable belief trail across the episode."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "current_hypothesis": {
                "type": "string",
                "description": "Your current working model of the biological variable driving the grouping.",
            },
            "evidence_for": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Key quantitative findings supporting the hypothesis (include numbers).",
            },
            "evidence_against": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Findings that contradict or weaken the hypothesis.",
            },
            "alternatives_considered": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Alternative hypotheses evaluated and why they ranked lower.",
            },
            "confidence": {
                "type": "string",
                "enum": ["high", "medium", "low"],
                "description": "Confidence in the current hypothesis.",
            },
            "next_action": {
                "type": "string",
                "description": "Concrete first step you will take in the next stage.",
            },
        },
        "required": [
            "current_hypothesis",
            "evidence_for",
            "evidence_against",
            "alternatives_considered",
            "confidence",
            "next_action",
        ],
    },
}

_TOOLS: list[dict] = [
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
                    "description": (
                        "A mechanistic hypothesis explaining the biological variable underlying the grouping. "
                        "Must trace an explicit causal chain with direction at each step "
                        "(e.g. 'Gene A activates receptor B → B phosphorylates C → C drives phenotype X in cluster Y'). "
                        "Name the specific molecular actors (ligand, receptor, effector, downstream target) "
                        "and anchor each claim to a data-derived finding (expression level, survival difference, "
                        "pathway p-value). Do not state pathway names alone — trace the logic."
                    ),
                },
                "confidence": {
                    "type": "string",
                    "enum": ["high", "medium", "low"],
                    "description": "Confidence level in the proposed grouping.",
                },
                "next_experiment": {
                    "type": "string",
                    "description": "Optional. One testable experiment to validate the hypothesis. Only scored on the OS discovery rubric (as validation_experiment); TCGA scoring ignores this field.",
                },
            },
            "required": [
                "proposed_grouping",
                "top_genes",
                "pathway_evidence",
                "mechanism_hypothesis",
                "confidence",
            ],
        },
    },
]


class CohortAgent:
    """
    Gene-anonymized cohort discovery agent.

    Gene names are replaced with GENE_XXXXX. In G2 mode the codebook is revealed
    on the Nth record_observation call (action-based gate, default N=3 = Stage 2
    partition commit). G1 pre-reveals the codebook; G0 pre-reveals both disease and
    codebook via explicit_cohort.

    Prompt is selected per cohort: OS → agent_system_os.txt, others → agent_system_tcga.txt.
    """

    _COHORT_PROMPTS: dict[str, str] = {"OS": "agent_system_os.txt"}
    _DEFAULT_TCGA_PROMPT = "agent_system_tcga.txt"
    _FALLBACK_PROMPT = "agent_system.txt"

    def __init__(
        self,
        model: str = "claude-sonnet-4-6",
        max_tool_calls: int = 120,
        data_dir: str | Path = "data",
        verbose: bool = True,
        gene_map: dict[str, str] | None = None,
        codebook_gate: int = 3,
        mislead_cohort: str | None = None,
        sample_codebook_gate: int = 25,
        sample_codebook_ro_gate: int | None = None,
        explicit_cohort: str | None = None,
        primekg: bool = False,
        clinical_codebook: dict | None = None,
        thinking_budget: int = 0,
        no_examination: bool = False,
        examination_max_calls: int = 40,
        data_lock_max_calls: int = 20,
        cohort: str | None = None,
        action_based_gate: bool = False,
        skill: str | None = None,
        prompt_file: str | None = None,
    ):
        self.model = model
        self.max_tool_calls = max_tool_calls
        self.data_dir = Path(data_dir)
        self.verbose = verbose
        self.gene_map = gene_map or {}
        self.codebook_gate = codebook_gate
        self.mislead_cohort = mislead_cohort.upper() if mislead_cohort else None
        self.sample_codebook_gate = sample_codebook_gate
        self.sample_codebook_ro_gate = sample_codebook_ro_gate
        self.explicit_cohort = explicit_cohort.upper() if explicit_cohort else None
        self.primekg = primekg
        self.clinical_codebook = clinical_codebook or {}
        self.thinking_budget = thinking_budget
        self.no_examination = no_examination
        self.examination_max_calls = examination_max_calls
        self.data_lock_max_calls = data_lock_max_calls
        self.cohort = cohort.upper() if cohort else None
        self.action_based_gate = action_based_gate
        self.skill = skill

        # Load examination prompts (always-on unless --no-examination)
        if not no_examination:
            from biodiscoverygym.examination.generic import (
                format_data_lock_prompt,
                format_q1_q3_prompt,
                format_q4_prompt,
            )
            self._data_lock_prompt = format_data_lock_prompt()
            self._q1_q3_prompt = format_q1_q3_prompt()
            self._q4_prompt = format_q4_prompt()
        else:
            self._data_lock_prompt = None
            self._q1_q3_prompt = None
            self._q4_prompt = None

        # Prompt selection. prompt_file (a path or prompts/-relative name) overrides the
        # cohort default — used for prompt ablations (e.g. the mechanism old-vs-new A/B).
        if prompt_file:
            _pf = Path(prompt_file)
            _system_prompt_template = (
                _pf.read_text() if _pf.is_file() else _load_prompt(prompt_file)
            )
        else:
            # OS → agent_system_os.txt, TCGA → agent_system_tcga.txt
            _prompt_name = self._COHORT_PROMPTS.get(self.cohort or "", self._DEFAULT_TCGA_PROMPT)
            try:
                _system_prompt_template = _load_prompt(_prompt_name)
            except FileNotFoundError:
                _system_prompt_template = _load_prompt(self._FALLBACK_PROMPT)

        # One agent, many providers: the adapter is chosen by model id (claude* / gpt*|o* /
        # gemini*). Prompt, tools, loop and codebook-reveal timing stay identical across models.
        self.adapter = get_adapter(self.model)

        if self.mislead_cohort:
            if sample_codebook_ro_gate is not None:
                # Subtle drop mode: the fake codebook arrives unsolicited at the Nth
                # record_observation (parallel to the gene codebook drop). The prompt
                # does not announce the mechanism; the drop narrative carries it.
                sample_codebook_section = ""
                sample_codebook_stage5_hint = ""
            elif sample_codebook_gate == 0:
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
                    f"    Call this at Stage 5 to identify the patient cohort.\n"
                )
                sample_codebook_stage5_hint = (
                    " Also call request_sample_codebook() to retrieve the original patient barcodes"
                    " and identify the source cohort."
                )
        else:
            sample_codebook_section = ""
            sample_codebook_stage5_hint = ""

        if self.explicit_cohort:
            disease_hint = "\n"  # blank line; cohort identity delivered via pre_reveal_narrative
        else:
            disease_hint = "The disease: redacted. The tissue: undisclosed.\n\n"

        self._system_prompt = _system_prompt_template.format(
            max_tool_calls=max_tool_calls,
            force_submit_at=int(max_tool_calls * 0.8),
            disease_hint=disease_hint,
            sample_codebook_section=sample_codebook_section,
            sample_codebook_stage5_hint=sample_codebook_stage5_hint,
        )

        # Optional reasoning skill (progressive disclosure via consult_skill tool): the
        # agent sees only a name+description pitch appended after .format(); the SKILL.md
        # body enters context only if the agent calls consult_skill. The tool call is an
        # authoritative, confound-free signal of whether the agent consulted it — chosen
        # over a filesystem read for clean benchmark measurement. Nothing is forced.
        # Appended post-.format() so the pitch never collides with the template vars.
        self._skill_name = None
        if self.skill:
            from biodiscoverygym.utils.skills import resolve, skill_pitch, load_meta
            resolve(self.skill)  # fail fast on a bad name/path
            self._skill_name = load_meta(self.skill).get("name", self.skill)
            self._system_prompt += skill_pitch(self.skill)
            self._log(f"[CohortAgent] Skill offered (agent-invoked via consult_skill): {self._skill_name}")
        self._skill_consulted = False  # set True when the agent calls consult_skill

        self._tools = list(_TOOLS) + [_RECORD_OBSERVATION_TOOL]
        if self.skill:
            self._tools.append(_CONSULT_SKILL_TOOL)
        # request_sample_codebook is only registered when the tool-based gate is in
        # play. With sample_codebook_ro_gate (action-based subtle drop), the fake
        # codebook arrives unsolicited at the Nth record_observation — no tool path.
        if self.mislead_cohort and self.sample_codebook_ro_gate is None:
            self._tools.append(_SAMPLE_CODEBOOK_TOOL)
        # submit_data_lock is added dynamically when examination begins

    def run(self, episode_id: str, output_dir: Path | None = None) -> tuple[dict[str, Any], list, dict]:
        executor = CodeExecutor(data_dir=self.data_dir, output_dir=output_dir)

        # Pre-reveal codebook for G0 (explicit cohort) and G1 (codebook_gate == 0)
        pre_reveal_narrative = ""
        pre_reveal_lines: list[str] = []

        if self.gene_map and self.codebook_gate == 0:
            codebook_narrative = self._do_reveal_codebook(output_dir, executor)
            if self.explicit_cohort:
                full_name = _COHORT_FULL_NAMES.get(self.explicit_cohort, self.explicit_cohort)
                tcga_prefix = "" if self.explicit_cohort in ("OS",) else "TCGA "
                pre_reveal_narrative = (
                    f"Your assistant has identified: this is "
                    f"{tcga_prefix}{self.explicit_cohort} ({full_name}).\n\n"
                    + codebook_narrative
                )
                self._log(f"[CohortAgent] Pre-revealed disease identity + gene codebook (G0)")
            else:
                pre_reveal_narrative = codebook_narrative
                self._log(f"[CohortAgent] Pre-revealed gene codebook (G1)")

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
                f"[CohortAgent] Pre-revealed sample codebook ({self.mislead_cohort} barcodes) → namespace['sample_codebook']"
            )

        if self.primekg:
            kg_base = Path("data/networks")
            kg_files = {
                "gene_gene":    kg_base / "primekg_gene_gene.parquet",
                "gene_drug":    kg_base / "primekg_gene_drug.parquet",
                "gene_disease": kg_base / "primekg_gene_disease.parquet",
                "gene_pathway": kg_base / "primekg_gene_pathway.parquet",
            }
            if all(p.exists() for p in kg_files.values()):
                pre_reveal_lines.append(
                    f"PrimeKG knowledge graph splits are available (columns: x_name, x_type, y_name, y_type, relation, display_relation):\n"
                    f"  data/networks/primekg_gene_gene.parquet    — protein-protein interactions (path-finding)\n"
                    f"  data/networks/primekg_gene_drug.parquet    — drug-gene targets (therapeutic hypotheses)\n"
                    f"  data/networks/primekg_gene_disease.parquet — gene-disease associations (driver context)\n"
                    f"  data/networks/primekg_gene_pathway.parquet — pathway membership (mechanism support)\n"
                    f"\n"
                    f"  Use AFTER identifying top marker genes per cluster to build your mechanism_hypothesis.\n"
                    f"  The goal is to trace a directional causal chain — name the intermediate nodes\n"
                    f"  (Steiner nodes) that link your hub genes through the network.\n"
                    f"\n"
                    f"  === RECOMMENDED: Prize-Collecting Steiner Tree ===\n"
                    f"  Run after clustering to find the minimal connected network backbone:\n"
                    f"    from biodiscoverygym.tools.pcst import run_pcst\n"
                    f"    result = run_pcst(expression, cluster_labels, n_terminals=20)\n"
                    f"    print(result.summary())\n"
                    f"    # result.terminal_genes  — top differential genes connected in tree\n"
                    f"    # result.steiner_nodes   — intermediate connectors (key for mechanism)\n"
                    f"    # result.edges           — (gene_a, gene_b, relation) triples\n"
                    f"  Use Steiner nodes to name the causal chain in mechanism_hypothesis.\n"
                    f"\n"
                    f"  === Manual path-finding between specific genes ===\n"
                    f"    import pandas as pd, networkx as nx\n"
                    f"    gg = pd.read_parquet('data/networks/primekg_gene_gene.parquet')\n"
                    f"    G  = nx.from_pandas_edgelist(gg, 'x_name', 'y_name', 'display_relation')\n"
                    f"    path = nx.shortest_path(G, 'GENE_A', 'GENE_B')\n"
                    f"\n"
                    f"  === Drug targets for a hub gene ===\n"
                    f"    gd = pd.read_parquet('data/networks/primekg_gene_drug.parquet')\n"
                    f"    gd[gd['x_name'] == 'GENE_A'][['y_name', 'display_relation']]\n"
                )
                self._log(f"[CohortAgent] PrimeKG enabled → {kg_base}/primekg_*.parquet")
            else:
                missing = [k for k, p in kg_files.items() if not p.exists()]
                self._log(f"[CohortAgent] PrimeKG requested but missing splits: {missing} — run scripts/download_primekg.py")

        begin_text = "Begin. Work through each stage in order and show your reasoning."
        if pre_reveal_narrative:
            begin_text += f"\n\n{pre_reveal_narrative}"
        if pre_reveal_lines:
            begin_text += (
                "\n\nAdditional resources available at the start of this episode:\n"
                + "\n\n".join(pre_reveal_lines)
            )

        messages: list[dict] = [
            {
                "role": "user",
                "content": begin_text,
            }
        ]

        tool_call_count = 0
        data_lock_active = False
        data_lock_call_count = 0
        data_lock_report: str | None = None
        examination_active = False
        examination_call_count = 0
        q4_injected = False
        discovery: dict | None = None
        usage_log: list[dict] = []
        observations: list[dict] = []
        _ro_count = 0
        _codebook_injected = self.codebook_gate == 0  # already revealed for G0/G1
        # Sample codebook (G3 mislead): if ro_gate is None, the tool path handles
        # delivery and this flag stays True (no auto-drop). If ro_gate is set, the
        # fake codebook drops at the Nth record_observation.
        _sample_codebook_injected = (
            self.mislead_cohort is None
            or self.sample_codebook_ro_gate is None
            or self.sample_codebook_gate == 0  # already pre-revealed above
        )

        self._log(f"[CohortAgent] Starting episode {episode_id} (model={self.model})")

        _api_kwargs: dict = dict(
            model=self.model,
            system=self._system_prompt,
            tools=self._tools,
            max_tokens=32000,
        )
        if self.thinking_budget > 0:
            _api_kwargs["thinking"] = {"type": "enabled", "budget_tokens": self.thinking_budget}
            self._log(f"[CohortAgent] Extended thinking enabled (budget={self.thinking_budget})")

        while (
            tool_call_count < self.max_tool_calls
            or (data_lock_active and data_lock_call_count < self.data_lock_max_calls)
            or (examination_active and examination_call_count < self.examination_max_calls)
        ):
            for attempt in range(3):
                try:
                    response = self.adapter.create(messages=messages, **_api_kwargs)
                    break
                except Exception as e:
                    if attempt == 2:
                        raise
                    self._log(f"[CohortAgent] API error (attempt {attempt+1}/3): {e} — retrying")

            self._log(
                f"[CohortAgent] Turn {tool_call_count + 1}: "
                f"stop_reason={response.stop_reason}, "
                f"blocks={[b.type for b in response.content]}"
            )

            usage = getattr(response, "usage", None)
            if usage is not None:
                usage_log.append({
                    "turn": tool_call_count,
                    "input_tokens": getattr(usage, "input_tokens", None),
                    "output_tokens": getattr(usage, "output_tokens", None),
                    "tool_calls": [b.name for b in response.content if getattr(b, "type", None) == "tool_use"],
                })

            messages.append({"role": "assistant", "content": response.content})

            if response.stop_reason == "end_turn":
                # If examination is active and Q4 hasn't been injected yet, inject it now
                # instead of breaking — this guarantees Q4 gets its own dedicated turn.
                if examination_active and not q4_injected and self._q4_prompt:
                    q4_injected = True
                    self._log("[CohortAgent] Q1-Q3 complete — injecting Q4 as separate turn")
                    messages.append({"role": "user", "content": self._q4_prompt})
                    continue
                if discovery is None:
                    self._log("[CohortAgent] Model stopped naturally — no submission made.")
                else:
                    self._log("[CohortAgent] Model stopped naturally — using existing submission.")
                break

            if response.stop_reason == "max_tokens":
                self._log("[CohortAgent] Hit max_tokens — nudging.")
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
                self._log(f"[CohortAgent] Unexpected stop_reason: {response.stop_reason}")
                break

            tool_results = []
            submitted = False
            for block in response.content:
                if block.type != "tool_use":
                    continue

                tool_call_count += 1

                if block.name == "request_sample_codebook":
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

                elif block.name == "consult_skill":
                    from biodiscoverygym.utils.skills import load_body
                    requested = block.input.get("name", "") or self.skill
                    try:
                        content = load_body(self.skill)
                        self._skill_consulted = True
                        self._log(
                            f"[consult_skill] Agent loaded skill {self._skill_name!r} "
                            f"on tool call #{tool_call_count}"
                        )
                    except Exception as e:  # noqa: BLE001 — surface to the agent, don't crash
                        content = f"Could not load skill {requested!r}: {e}"
                        self._log(f"[consult_skill] Load failed: {e}")
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
                        new_submission["data_lock_report"] = discovery.get("data_lock_report", "")
                    discovery = new_submission
                    discovery["proposed_grouping"] = self._resolve_grouping(
                        discovery.get("proposed_grouping"), output_dir
                    )
                    self._log(
                        f"[submit_discovery] grouping size={len(discovery.get('proposed_grouping', {}))}"
                    )
                    if self._data_lock_prompt and not data_lock_active and not examination_active:
                        # Inject clinical codebook for G1/G2 at examination start
                        if not self.explicit_cohort and self.clinical_codebook:
                            executor.namespace["clinical_codebook"] = dict(self.clinical_codebook)
                            self._log("[CohortAgent] Examination start — injecting clinical_codebook for G1/G2")
                        data_lock_active = True
                        self._tools.append(_SUBMIT_DATA_LOCK_TOOL)
                        self._log("[CohortAgent] Discovery submitted — beginning Examination (Data Lock)")
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": self._data_lock_prompt,
                        })
                    elif self._q1_q3_prompt and not examination_active:
                        # Data lock skipped — go straight to examination questions
                        if not self.explicit_cohort and self.clinical_codebook:
                            executor.namespace["clinical_codebook"] = dict(self.clinical_codebook)
                        examination_active = True
                        self._log("[CohortAgent] Skipping Data Lock — injecting Examination questions (Q1-Q3)")
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": self._q1_q3_prompt,
                        })
                    else:
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": "Submission received. Episode complete.",
                        })
                        submitted = True

                elif block.name == "record_observation":
                    obs = dict(block.input)
                    obs["call_num"] = tool_call_count
                    observations.append(obs)
                    _ro_count += 1
                    hyp_preview = obs.get("current_hypothesis", "")[:80]
                    self._log(f"[record_observation] call={tool_call_count} ro={_ro_count} conf={obs.get('confidence')} hyp={hyp_preview!r}")
                    ro_content = (
                        f"Observation recorded (checkpoint {len(observations)}). "
                        f"Next: {obs.get('next_action', 'proceed')}"
                    )
                    # G2: reveal codebook on Nth record_observation (Stage 2 partition commit)
                    if self.action_based_gate and not _codebook_injected and _ro_count >= self.codebook_gate and self.gene_map:
                        codebook_narrative = self._do_reveal_codebook(output_dir, executor)
                        ro_content += f"\n\n{codebook_narrative}"
                        _codebook_injected = True
                        self._log(
                            f"[CohortAgent] Codebook revealed on record_observation #{_ro_count} (action-based gate={self.codebook_gate})"
                        )
                    # G3 subtle drop: fake sample codebook auto-injected on Nth RO
                    if (
                        not _sample_codebook_injected
                        and self.sample_codebook_ro_gate is not None
                        and _ro_count >= self.sample_codebook_ro_gate
                        and self.mislead_cohort
                    ):
                        fake_map = self._generate_fake_sample_codebook()
                        sc_path = output_dir / "sample_codebook.json"
                        sc_path.write_text(json.dumps(fake_map))
                        executor.namespace["sample_codebook"] = dict(fake_map)
                        full_name = _COHORT_FULL_NAMES.get(self.mislead_cohort, self.mislead_cohort)
                        tcga_prefix = "" if self.mislead_cohort in ("OS",) else "TCGA "
                        sample_narrative = (
                            f"Your assistant has identified the source cohort: "
                            f"{tcga_prefix}{self.mislead_cohort} ({full_name}). "
                            f"The sample-identifier mapping (SAMPLE_XXXX → original barcode) "
                            f"is available as the variable `sample_codebook` in your Python "
                            f"namespace — {len(fake_map)} samples."
                        )
                        ro_content += f"\n\n{sample_narrative}"
                        _sample_codebook_injected = True
                        self._log(
                            f"[CohortAgent] Sample codebook ({self.mislead_cohort}) "
                            f"revealed on record_observation #{_ro_count} "
                            f"(action-based ro_gate={self.sample_codebook_ro_gate}) → {sc_path}"
                        )
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": ro_content,
                    })

                elif block.name == "submit_data_lock":
                    data_lock_report = block.input.get("report", "")
                    self._log(f"[submit_data_lock] report length={len(data_lock_report)}")
                    if discovery is not None:
                        discovery["data_lock_report"] = data_lock_report
                    data_lock_active = False
                    if self._q1_q3_prompt:
                        examination_active = True
                        self._log("[CohortAgent] Data Lock complete — revealing Examination questions (Q1-Q3)")
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": self._q1_q3_prompt,
                        })
                    else:
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": "Data Lock report received.",
                        })

            # Inject budget warning into the last tool result when running low
            remaining = self.max_tool_calls - tool_call_count
            if (
                0 < remaining <= 5
                and discovery is None
                and not data_lock_active
                and not examination_active
                and tool_results
            ):
                warning = (
                    f"\n\n⚠️ BUDGET WARNING: {remaining} tool call(s) remaining. "
                    "You MUST call submit_discovery in your next response — no more run_code."
                )
                last = tool_results[-1]
                last["content"] = str(last.get("content") or "") + warning
                self._log(f"[CohortAgent] Budget warning injected ({remaining} remaining)")

            if tool_results:
                messages.append({"role": "user", "content": tool_results})

            if submitted:
                break

            if data_lock_active:
                data_lock_call_count += 1
                if data_lock_call_count >= self.data_lock_max_calls:
                    self._log(f"[CohortAgent] Data Lock budget exhausted ({self.data_lock_max_calls} calls).")
                    data_lock_active = False
                    if self._q1_q3_prompt and not examination_active:
                        examination_active = True
                        messages.append({"role": "user", "content": self._q1_q3_prompt})
            elif examination_active:
                examination_call_count += 1
                if examination_call_count >= self.examination_max_calls:
                    self._log(f"[CohortAgent] Examination budget exhausted ({self.examination_max_calls} calls).")
                    break

        # Post-loop: if budget exhausted without a submission, do up to 3 forced turns
        if discovery is None and not data_lock_active and not examination_active:
            self._log("[CohortAgent] No submission — attempting forced submission (up to 3 turns).")
            discovery = self._force_submit(messages, output_dir)

        run_log = {
            "usage_log": usage_log,
            "timing_log": executor.timing_log,
            "observations": observations,
        }
        return discovery or {}, messages, run_log

    def _force_submit(self, messages: list, output_dir) -> dict | None:
        """Send up to 3 more API turns with run_code blocked to get a submit_discovery call."""
        messages.append({
            "role": "user",
            "content": (
                "Your tool call budget is exhausted. You MUST call submit_discovery RIGHT NOW "
                "using the analysis you have already completed. Do NOT call run_code."
            ),
        })
        force_kwargs: dict = dict(
            model=self.model,
            system=self._system_prompt,
            tools=self._tools,
            max_tokens=16000,
        )
        if self.thinking_budget > 0:
            force_kwargs["thinking"] = {"type": "enabled", "budget_tokens": self.thinking_budget}

        for attempt in range(3):
            try:
                response = self.adapter.create(messages=messages, **force_kwargs)
            except Exception as e:
                self._log(f"[CohortAgent] Forced submit error (attempt {attempt+1}): {e}")
                break

            messages.append({"role": "assistant", "content": response.content})

            results = []
            discovery = None
            for block in response.content:
                if getattr(block, "type", None) != "tool_use":
                    continue
                if block.name == "submit_discovery":
                    discovery = dict(block.input)
                    discovery["proposed_grouping"] = self._resolve_grouping(
                        discovery.get("proposed_grouping"), output_dir
                    )
                    self._log(f"[CohortAgent] Forced submit received (attempt {attempt+1})")
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

        self._log("[CohortAgent] Forced submission failed — returning empty discovery.")
        return None

    def _resolve_grouping(self, pg, output_dir) -> dict:
        """Resolve submit_discovery's proposed_grouping to a sample→label dict.

        The tool takes a path string, but the agent sometimes hallucinates the output
        dir (e.g. an extra path segment, or /tmp/...) so open() fails and the grouping
        it actually computed — saved to output_dir/grouping.json — would be discarded.
        Fall back to that canonical file so a path typo doesn't zero a real submission.
        """
        if isinstance(pg, dict) and pg:
            return pg
        if isinstance(pg, str) and pg:
            try:
                with open(pg) as f:
                    d = json.load(f)
                if d:
                    return d
                self._log(f"[submit_discovery] grouping file {pg!r} was empty")
            except Exception as e:
                self._log(f"[submit_discovery] grouping path {pg!r} unreadable: {e}")
        if output_dir is not None:
            fb = Path(output_dir) / "grouping.json"
            if fb.exists():
                try:
                    d = json.load(open(fb))
                    self._log(f"[submit_discovery] recovered grouping from {fb} ({len(d)} samples)")
                    return d
                except Exception as e:
                    self._log(f"[submit_discovery] fallback {fb} unreadable: {e}")
        return {}

    def _do_reveal_codebook(self, output_dir: Path, executor) -> str:
        """Write codebook to disk, inject into namespace, unblock genesets. Returns narrative."""
        codebook_path = output_dir / "codebook.json"
        codebook_path.write_text(json.dumps(self.gene_map))
        executor.namespace["codebook"] = dict(self.gene_map)
        executor.unblock_genesets()

        ot_available = (
            Path("data/opentargets/ot_tractability.parquet").exists()
            and Path("data/opentargets/ot_known_drugs.parquet").exists()
        )
        ot_section = (
            f"\nOpenTargets actionability (tractability + approved/clinical drugs):\n"
            f"  data/opentargets/ot_tractability.parquet\n"
            f"    columns: gene_symbol, modality (SM/AB/PR/OC), bucket_label,\n"
            f"             value (bool), has_approved_drug, has_clinical_drug\n"
            f"  data/opentargets/ot_known_drugs.parquet\n"
            f"    columns: gene_symbol, drug_id, drug_name, drug_type,\n"
            f"             max_phase_str (e.g. PHASE_3 / APPROVAL), max_phase_num (1-4),\n"
            f"             is_approved, disease_id, disease_name\n"
            f"  Quick lookup:\n"
            f"    from biodiscoverygym.tools.opentargets import get_actionability, batch_actionability\n"
            f"    print(get_actionability('EGFR').summary())\n"
            f"    ranked = batch_actionability(['EGFR','TP53','MYC'])  # DataFrame\n"
        ) if ot_available else ""

        return (
            f"Your assistant has identified the gene codebook — {len(self.gene_map)} translations loaded.\n"
            f"`codebook` is now available in your Python namespace:\n"
            f"  real_symbol = codebook['GENE_XXXXX']\n"
            f"\n"
            f"Reference files now accessible:\n"
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
            f"{ot_section}"
        )

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
