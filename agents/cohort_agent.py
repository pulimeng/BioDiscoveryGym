"""
CohortAgent: cohort-discovery agent with per-mode system prompts (G0/G1/G2).
Gene names are replaced with GENE_XXXXX identifiers; the codebook is gated or
pre-revealed depending on mode. All reference-database lookups (DepMap, GTEx,
MSigDB, STRING) are removed — the agent must rely on statistical structure and
clinical metadata.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from agents.adapters import get_adapter

from biodiscoverygym.executor import CodeExecutor
from biodiscoverygym.models import DEFAULT_AGENT_MODEL, DEFAULT_EFFORT
from biodiscoverygym.trace import EpisodeTrace
from biodiscoverygym import protocol as P
from biodiscoverygym.tasks import get_task
from biodiscoverygym.utils.prompts import load as _load_prompt
from biodiscoverygym.utils.skills import CONSULT_SKILL_TOOL as _CONSULT_SKILL_TOOL

# Cancer names, delivery texts, markers and the answer space now come from the task adapter
# (biodiscoverygym/tasks/cohort_identity.py).

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

_RECORD_OBSERVATION_BASE: dict = {
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

def _schema_of(name: str) -> dict:
    return next(t for t in _TOOLS if t["name"] == name)["input_schema"]


_RECORD_MILESTONE_BASE: dict = {
    "name": "record_milestone",
    # Only what the harness cannot observe: the agent's current belief, how firmly it holds it,
    # and what moved it. The prior belief is NOT asked for: the harness records it from the last
    # observation (trace.milestone_declared). No kind enum: it carried no information the scope
    # and the change itself do not.
    "description": (
        "Record a turning point at the moment it happens, not at the end of a stage: your belief "
        "about something changed because of a specific result. Optional; does not count as a "
        "stage checkpoint."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "scope": {"type": "string",
                      "enum": [],   # filled from task.claim_scopes
                      "description": "What the change is about."},
            "belief": {"type": "string", "description": "What you hold now, in one sentence."},
            "confidence": {"type": "string", "enum": ["high", "medium", "low"],
                           "description": "How firmly you hold it."},
            "trigger": {"type": "string",
                        "description": "The specific result that changed your belief."},
            "evidence_steps": {
                "type": "array", "items": {"type": "integer"},
                "description": "Tool-call numbers of the run_code calls behind it.",
            },
        },
        "required": ["scope", "belief", "confidence", "trigger", "evidence_steps"],
    },
}

def observation_tool(task) -> dict:
    """record_observation with the task's answer block appended (last, as before the split). The
    answer is a structured checkpoint asked identically in every arm; the harness stamps each
    observation with what the agent could see at that moment."""
    import copy
    t = copy.deepcopy(_RECORD_OBSERVATION_BASE)
    t["input_schema"]["properties"][task.answer_field] = task.answer_schema()
    t["input_schema"]["required"].append(task.answer_field)
    return t


def milestone_tool(task) -> dict:
    import copy
    t = copy.deepcopy(_RECORD_MILESTONE_BASE)
    t["input_schema"]["properties"]["scope"]["enum"] = list(task.claim_scopes)
    return t


_DEFAULT_TASK = get_task()
_RECORD_OBSERVATION_TOOL = observation_tool(_DEFAULT_TASK)   # module-level copies for imports/tests
_RECORD_MILESTONE_TOOL = milestone_tool(_DEFAULT_TASK)


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
                    "description": "Optional. One testable experiment to validate the hypothesis. Not scored by the TCGA rubric.",
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

_SUBMIT_SCHEMA = _schema_of("submit_discovery")


class CohortAgent:
    """
    Gene-anonymized cohort discovery agent.

    Gene names are replaced with GENE_XXXXX. In G2 mode the codebook is revealed
    on the Nth record_observation call (action-based gate, default N=3 = Stage 2
    partition commit). G1 pre-reveals the codebook; G0 pre-reveals both disease and
    codebook via explicit_cohort.

    The TCGA prompt (agent_system_tcga.txt) is used for every cohort unless a prompt file is given.
    """

    _COHORT_PROMPTS: dict[str, str] = {}
    _DEFAULT_TCGA_PROMPT = "agent_system_tcga.txt"
    _FALLBACK_PROMPT = "agent_system.txt"

    def __init__(
        self,
        model: str = DEFAULT_AGENT_MODEL,
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
        effort: str | None = DEFAULT_EFFORT,
        no_examination: bool = False,
        examination_max_calls: int = 40,
        data_lock_max_calls: int = 20,
        cohort: str | None = None,
        action_based_gate: bool = False,
        skill: str | None = None,
        prompt_file: str | None = None,
        task: str | None = None,
    ):
        self.model = model
        self.task = get_task(task)
        self._obs_tool = observation_tool(self.task)
        self._ms_tool = milestone_tool(self.task)
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
        self.effort = effort  # Anthropic output_config.effort; other adapters ignore it
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

        self._tools = list(_TOOLS) + [self._obs_tool, self._ms_tool]
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
        # Harness-side event log + visibility record (biodiscoverygym/trace.py). Never shown to
        # the agent; lands next to the episode JSON as events.jsonl.
        trace = EpisodeTrace(
            (Path(output_dir) / "events.jsonl") if output_dir else None,
            self.gene_map, true_cohort=self.cohort, planted_cohort=self.mislead_cohort,
            task=self.task,
            config={"model": self.model, "effort": self.effort,
                    "codebook_gate": self.codebook_gate,
                    "explicit_cohort": self.explicit_cohort,
                    "mislead_cohort": self.mislead_cohort,
                    "sample_codebook_ro_gate": self.sample_codebook_ro_gate,
                    "max_tool_calls": self.max_tool_calls,
                    "protocol": P.PROTOCOL_VERSION},
        )
        self._trace = trace

        # Pre-reveal codebook for G0 (explicit cohort) and G1 (codebook_gate == 0)
        pre_reveal_narrative = ""
        pre_reveal_lines: list[str] = []

        if self.gene_map and self.codebook_gate == 0:
            codebook_narrative = self._do_reveal_codebook(output_dir, executor)
            trace.symbols_revealed(0, "opening")
            if self.explicit_cohort:
                trace.label_delivered(0, self.explicit_cohort, "opening")
                pre_reveal_narrative = (self.task.explicit_answer_text(self.explicit_cohort)
                                        + codebook_narrative)
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
            trace.label_delivered(0, self.mislead_cohort, "opening_barcodes")

        # ro_gate == 0: the false label arrives in the opening message (v2 G3a). Same sentence as
        # the Nth-record_observation drop (v2 G3b, ro_gate=3), same prompt (no
        # request_sample_codebook tool, no Stage-5 hint, since ro_gate is set), so the only
        # difference between G3a and G3b is WHEN the label arrives. Placed directly after the
        # begin line, as the G0 preamble is, so G0 and G3a differ only in label truth.
        start_sample_narrative = ""
        if self.mislead_cohort and self.sample_codebook_ro_gate == 0:
            fake_map = self._generate_fake_sample_codebook()
            sc_path = output_dir / "sample_codebook.json"
            sc_path.write_text(json.dumps(fake_map))
            executor.namespace["sample_codebook"] = dict(fake_map)
            start_sample_narrative = self._sample_codebook_narrative(len(fake_map))
            self._log(
                f"[CohortAgent] Sample codebook ({self.mislead_cohort}) dropped at episode start "
                f"(ro_gate=0) → {sc_path}"
            )
            trace.label_delivered(0, self.mislead_cohort, "opening")

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
                self._log(f"[CohortAgent] PrimeKG requested but missing splits: {missing} — run scripts/data/download/download_primekg.py")

        # One opening sentence for every arm. The ICLR harness said "...in order and show your
        # reasoning."; with a label sentence appended (G0, and v2's start-label G3a) that phrase
        # trips the Opus 5 `reasoning_extraction` classifier: empty turn-0 refusal, 8/8 resends
        # (2026-11-10). Dropping it everywhere keeps the arms identical instead of giving the
        # start-label cells their own wording.
        begin_text = "Begin. Work through each stage in order."
        if pre_reveal_narrative:
            begin_text += f"\n\n{pre_reveal_narrative}"
        if start_sample_narrative:
            begin_text += f"\n\n{start_sample_narrative}"
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
        _ro_count = 0                 # VALID observations only (protocol R3)
        _submit_rejections = 0
        rejected_calls: list[dict] = []
        _codebook_injected = self.codebook_gate == 0  # already revealed for G0/G1
        # Sample codebook (G3 mislead): if ro_gate is None, the tool path handles
        # delivery and this flag stays True (no auto-drop). If ro_gate is set, the
        # fake codebook drops at the Nth record_observation.
        _sample_codebook_injected = (
            self.mislead_cohort is None
            or self.sample_codebook_ro_gate is None
            or self.sample_codebook_gate == 0  # already pre-revealed above
            or self.sample_codebook_ro_gate == 0  # dropped at episode start above
        )

        self._log(f"[CohortAgent] Starting episode {episode_id} (model={self.model})")

        _api_kwargs: dict = dict(
            model=self.model,
            system=self._system_prompt,
            tools=self._tools,
            max_tokens=32000,
        )
        if self.effort:
            _api_kwargs["effort"] = self.effort

        while (
            tool_call_count < self.max_tool_calls
            or (data_lock_active and data_lock_call_count < self.data_lock_max_calls)
            or (examination_active and examination_call_count < self.examination_max_calls)
        ):
            _t_api = time.time()
            _retries = 0
            for attempt in range(3):
                try:
                    response = self.adapter.create(messages=messages, **_api_kwargs)
                    break
                except Exception as e:
                    if attempt == 2:
                        raise
                    _retries += 1
                    self._log(f"[CohortAgent] API error (attempt {attempt+1}/3): {e} — retrying")
            # EMPTY REFUSAL = resend the identical request. Opus 5 intermittently returns
            # stop_reason="refusal" with no content on the unchanged TCGA-OV opening request
            # (2026-11-09: 4 of 6 identical requests refused, the other 2 answered normally). The
            # loop below treats any unexpected stop_reason as terminal and forces a submission,
            # which turned 8 rebuttal episodes into one-turn submissions made from the label
            # alone. Resending adds nothing to what the agent sees, and an episode that never
            # refuses behaves exactly as before. Counted in usage_log["refusals"] so it is visible.
            _refusals = 0
            while (getattr(response, "stop_reason", None) == "refusal"
                   and not response.content and _refusals < 8):
                _refusals += 1
                self._log(f"[CohortAgent] Empty refusal ({_refusals}/8, category="
                          f"{getattr(response, 'refusal_category', None)}) — resending the same request")
                time.sleep(min(2 * _refusals, 10))
                response = self.adapter.create(messages=messages, **_api_kwargs)
            # Includes retry backoff by design: a provider that stalls and retries costs real
            # wall-clock, and a turn that took 400s because of backoff should not look like a
            # turn that took 400s of thinking. `retries` is what tells the two apart.
            _api_s = time.time() - _t_api

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
                    "api_s": round(_api_s, 2),
                    "retries": _retries,
                    "refusals": _refusals,
                    "refusal_category": getattr(response, "refusal_category", None),
                    "tool_calls": [b.name for b in response.content if getattr(b, "type", None) == "tool_use"],
                })
            trace.model_turn(
                tool_call_count, stop_reason=response.stop_reason,
                input_tokens=getattr(usage, "input_tokens", None),
                output_tokens=getattr(usage, "output_tokens", None),
                api_s=round(_api_s, 2), retries=_retries, refusals=_refusals,
                refusal_category=getattr(response, "refusal_category", None),
                text="\n".join(getattr(b, "text", "") or "" for b in response.content
                               if getattr(b, "type", None) == "text"),
                tool_calls=[b.name for b in response.content if getattr(b, "type", None) == "tool_use"],
            )

            messages.append({"role": "assistant", "content": response.content})

            # DISPATCH ON CONTENT, NOT ONLY ON stop_reason. A response can carry tool_use blocks
            # while reporting a stop_reason other than "tool_use" — providers differ, and the
            # adapters normalize the blocks but cannot normalize away the discrepancy. Both exits
            # below used to `break` *before* the block loop, silently discarding any tool call in
            # that same response.
            #
            # This cost a real episode: sonnet5 g1_lihc_s7 in the 2026-08-05 run emitted a
            # complete, high-confidence submit_discovery (TP53, CTNNB1, AFP, EPCAM, KRT19 — the
            # right LIHC markers) that was dropped on the floor. The episode then fell through to
            # forced submission, wrote a JSON with `discovery: {}`, and reads downstream as "the
            # agent never answered". Worse, the file EXISTS, so the resume check skips it and the
            # scorer would grade the empty submission as a failure to submit.
            _has_tool_use = any(getattr(b, "type", None) == "tool_use" for b in response.content)

            if response.stop_reason == "end_turn" and not _has_tool_use:
                # If examination is active and Q4 hasn't been injected yet, inject it now
                # instead of breaking — this guarantees Q4 gets its own dedicated turn.
                if examination_active and not q4_injected and self._q4_prompt:
                    q4_injected = True
                    self._log("[CohortAgent] Q1-Q3 complete — injecting Q4 as separate turn")
                    trace.harness_event("q4_injected", tool_call_count)
                    messages.append({"role": "user", "content": self._q4_prompt})
                    continue
                if discovery is None:
                    self._log("[CohortAgent] Model stopped naturally — no submission made.")
                else:
                    self._log("[CohortAgent] Model stopped naturally — using existing submission.")
                trace.harness_event("model_stopped", tool_call_count, submitted=discovery is not None)
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

            if response.stop_reason != "tool_use" and not _has_tool_use:
                self._log(f"[CohortAgent] Unexpected stop_reason: {response.stop_reason}")
                trace.harness_event("unexpected_stop", tool_call_count,
                                    stop_reason=response.stop_reason,
                                    refusal_category=getattr(response, "refusal_category", None))
                break
            if response.stop_reason != "tool_use":
                # Tool calls present under an unexpected stop_reason — process them, but say so.
                # Silence here is what made the dropped submission undiagnosable after the fact.
                self._log(f"[CohortAgent] stop_reason={response.stop_reason} but "
                          f"{sum(1 for b in response.content if getattr(b,'type',None)=='tool_use')} "
                          f"tool_use block(s) present — processing them")

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
                        trace.label_delivered(tool_call_count, self.mislead_cohort, "tool")
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
                    trace.run_code(tool_call_count, code, output,
                                   executor.timing_log[-1] if executor.timing_log else None)
                    tool_results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            # The call number lets the agent cite evidence by step
                            # (cancer_identity.evidence_steps, record_milestone). Same in every arm.
                            "content": f"[call {tool_call_count}]\n{output}",
                        }
                    )

                elif block.name == "record_milestone":
                    payload, errs = P.live_check(
                        "record_milestone", dict(block.input),
                        self._ms_tool["input_schema"], step=tool_call_count,
                        run_code_steps=trace.run_code_steps, n_valid_obs=_ro_count, answer_field=self.task.answer_field)
                    if errs:
                        trace.tool_rejected(tool_call_count, "record_milestone", errs)
                        rejected_calls.append({"call_num": tool_call_count,
                                               "tool": "record_milestone", "errors": errs})
                        tool_results.append({"type": "tool_result", "tool_use_id": block.id,
                                             "content": P.rejection_message("record_milestone", errs)})
                        continue
                    trace.milestone_declared(tool_call_count, payload)
                    self._log(f"[record_milestone] call={tool_call_count} kind={payload.get('kind')} "
                              f"what={str(payload.get('what', ''))[:80]!r}")
                    # The validity check is harness-side only; the agent just gets an ack.
                    tool_results.append({
                        "type": "tool_result", "tool_use_id": block.id,
                        "content": f"Milestone recorded (call {tool_call_count}).",
                    })

                elif block.name == "submit_discovery":
                    norm, errs = P.live_check(
                        "submit_discovery", dict(block.input), _SUBMIT_SCHEMA,
                        step=tool_call_count, run_code_steps=trace.run_code_steps,
                        n_valid_obs=_ro_count, answer_field=self.task.answer_field)
                    if errs:
                        left = self.max_tool_calls - tool_call_count
                        if left <= P.SUBMIT_GRACE_CALLS or _submit_rejections >= P.MAX_SUBMIT_REJECTIONS:
                            # Grace valve: never lose an episode to the protocol. Logged, so the
                            # scorer reports it instead of hiding it.
                            reason = ("budget" if left <= P.SUBMIT_GRACE_CALLS
                                      else f"{_submit_rejections}_rejections")
                            trace.rule_violation_accepted(tool_call_count, "submit_discovery",
                                                          errs, reason=reason)
                            self._log(f"[submit_discovery] accepted despite {errs} ({reason})")
                        else:
                            _submit_rejections += 1
                            trace.tool_rejected(tool_call_count, "submit_discovery", errs)
                            rejected_calls.append({"call_num": tool_call_count,
                                                   "tool": "submit_discovery", "errors": errs})
                            self._log(f"[submit_discovery] REJECTED call={tool_call_count}: {errs}")
                            tool_results.append({"type": "tool_result", "tool_use_id": block.id,
                                                 "content": P.rejection_message("submit_discovery", errs)})
                            continue
                    new_submission = dict(norm) if isinstance(norm, dict) else dict(block.input)
                    if discovery is not None:
                        new_submission["data_lock_report"] = discovery.get("data_lock_report", "")
                    discovery = new_submission
                    discovery["proposed_grouping"] = self._resolve_grouping(
                        discovery.get("proposed_grouping"), output_dir
                    )
                    self._log(
                        f"[submit_discovery] grouping size={len(discovery.get('proposed_grouping', {}))}"
                    )
                    trace.harness_event("submit_discovery", tool_call_count,
                                        grouping_size=len(discovery.get("proposed_grouping") or {}),
                                        confidence=discovery.get("confidence"))
                    if self._data_lock_prompt and not data_lock_active and not examination_active:
                        # Inject clinical codebook for G1/G2 at examination start
                        if not self.explicit_cohort and self.clinical_codebook:
                            executor.namespace["clinical_codebook"] = dict(self.clinical_codebook)
                            self._log("[CohortAgent] Examination start — injecting clinical_codebook for G1/G2")
                            trace.clinical_codebook_injected(tool_call_count)
                        data_lock_active = True
                        trace.harness_event("data_lock_start", tool_call_count)
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
                            trace.clinical_codebook_injected(tool_call_count)
                        examination_active = True
                        trace.harness_event("exam_start", tool_call_count, via="submit_discovery")
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
                    norm, errs = P.live_check(
                        "record_observation", dict(block.input),
                        self._obs_tool["input_schema"], step=tool_call_count,
                        run_code_steps=trace.run_code_steps, n_valid_obs=_ro_count, answer_field=self.task.answer_field)
                    if errs:
                        # R3: not recorded, not counted toward any reveal gate.
                        trace.tool_rejected(tool_call_count, "record_observation", errs)
                        rejected_calls.append({"call_num": tool_call_count,
                                               "tool": "record_observation", "errors": errs})
                        self._log(f"[record_observation] REJECTED call={tool_call_count}: {errs}")
                        tool_results.append({"type": "tool_result", "tool_use_id": block.id,
                                             "content": P.rejection_message("record_observation", errs)})
                        continue
                    obs = dict(norm)
                    obs["call_num"] = tool_call_count
                    # Stamp BEFORE any reveal below: the identity was stated with what the agent
                    # could see up to now, not with what this tool result is about to show it.
                    obs["vis"] = trace.observation(tool_call_count, obs)
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
                        trace.symbols_revealed(tool_call_count, "record_observation")
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
                        sample_narrative = self._sample_codebook_narrative(len(fake_map))
                        ro_content += f"\n\n{sample_narrative}"
                        _sample_codebook_injected = True
                        trace.label_delivered(tool_call_count, self.mislead_cohort, "record_observation")
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
                    trace.harness_event("submit_data_lock", tool_call_count,
                                        report_chars=len(data_lock_report))
                    if self._q1_q3_prompt:
                        examination_active = True
                        trace.harness_event("exam_start", tool_call_count, via="submit_data_lock")
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
                trace.harness_event("budget_warning", tool_call_count, remaining=remaining)

            if tool_results:
                messages.append({"role": "user", "content": tool_results})

            if submitted:
                break

            if data_lock_active:
                data_lock_call_count += 1
                if data_lock_call_count >= self.data_lock_max_calls:
                    self._log(f"[CohortAgent] Data Lock budget exhausted ({self.data_lock_max_calls} calls).")
                    trace.harness_event("data_lock_budget_exhausted", tool_call_count)
                    data_lock_active = False
                    if self._q1_q3_prompt and not examination_active:
                        examination_active = True
                        messages.append({"role": "user", "content": self._q1_q3_prompt})
            elif examination_active:
                examination_call_count += 1
                if examination_call_count >= self.examination_max_calls:
                    self._log(f"[CohortAgent] Examination budget exhausted ({self.examination_max_calls} calls).")
                    trace.harness_event("exam_budget_exhausted", tool_call_count)
                    break

        # Post-loop: if budget exhausted without a submission, do up to 3 forced turns
        if discovery is None and not data_lock_active and not examination_active:
            self._log("[CohortAgent] No submission — attempting forced submission (up to 3 turns).")
            trace.harness_event("forced_submit_start", tool_call_count)
            discovery = self._force_submit(messages, output_dir)
            trace.harness_event("forced_submit_end", tool_call_count, submitted=discovery is not None)
            if discovery is not None:
                # Always accepted (the budget is gone), but checked and logged like any other.
                _, errs = P.live_check("submit_discovery", dict(discovery), _SUBMIT_SCHEMA,
                                       step=tool_call_count + 1,
                                       run_code_steps=trace.run_code_steps, n_valid_obs=_ro_count, answer_field=self.task.answer_field)
                if errs:
                    trace.rule_violation_accepted(tool_call_count, "submit_discovery", errs,
                                                  reason="forced_submit")
                trace.harness_event("submit_discovery", tool_call_count, forced=True,
                                    grouping_size=len(discovery.get("proposed_grouping") or {}))

        run_log = {
            "usage_log": usage_log,
            "timing_log": executor.timing_log,
            "observations": observations,
            "rejected_calls": rejected_calls,
            "trace": trace.close(tool_call_count, submitted=discovery is not None,
                                 n_turns=len(usage_log),
                                 n_refusals=sum(u.get("refusals", 0) or 0 for u in usage_log),
                                 n_exec_timeouts=sum(1 for t in executor.timing_log if t.get("timed_out"))),
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
        if self.effort:
            force_kwargs["effort"] = self.effort

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
            elif attempt < 2:
                # The model answered in prose with no tool call. Without this branch the next
                # attempt would resend a conversation ending in an ASSISTANT turn, which several
                # providers reject outright (Anthropic: 400 "This model does not support assistant
                # message prefill. The conversation must end with a user message."). That killed
                # g3b_ov_mislead_brca_s3 in the 2026-08-05 production run -- a deterministic
                # failure, so the resume re-run would have hit it again.
                messages.append({
                    "role": "user",
                    "content": ("You replied with text but did not call submit_discovery. "
                                "Call the submit_discovery tool now."),
                })
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
        """Write codebook to disk, inject into namespace, unblock genesets. Returns the narrative
        (wording owned by the task adapter)."""
        codebook_path = output_dir / "codebook.json"
        codebook_path.write_text(json.dumps(self.gene_map))
        executor.namespace["codebook"] = dict(self.gene_map)
        executor.unblock_genesets()
        ot_available = (
            Path("data/opentargets/ot_tractability.parquet").exists()
            and Path("data/opentargets/ot_known_drugs.parquet").exists()
        )
        return self.task.symbol_reveal_text(len(self.gene_map), ot_available)

    def _sample_codebook_narrative(self, n_samples: int) -> str:
        """The harness sentence that supplies a (planted) cohort label; wording owned by the task
        adapter (CohortIdentityTask.label_sentence), found by its disclosure_regex."""
        return self.task.label_sentence(self.mislead_cohort, n_samples)

    def _generate_fake_sample_codebook(self) -> dict[str, str]:
        """Return {SAMPLE_XXXX: TCGA-{mislead_cohort}-XXXX} by reading the episode parquet index."""
        import pandas as pd
        from biodiscoverygym.paths import episode_data_dir
        path = episode_data_dir(self.data_dir) / "expression.parquet"
        sample_ids = sorted(pd.read_parquet(path, columns=[]).index.tolist())
        cohort = self.mislead_cohort
        return {s: f"TCGA-{cohort}-{i:04d}" for i, s in enumerate(sample_ids)}

    def _log(self, msg: str) -> None:
        if self.verbose:
            print(msg)
