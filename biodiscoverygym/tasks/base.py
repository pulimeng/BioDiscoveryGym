"""Task adapter interface: everything the harness core needs to know about a domain.

CORE (task-agnostic): agent loop, provider adapters, sandbox, event log + visibility mechanics,
checkpoint / milestone protocol, validator and rules, claim extraction, evidence judge, summaries,
reports. ADAPTER (domain knowledge): data, what can be hidden and revealed, the answer space and its
classifier, the tokens worth watching in outputs, claim scopes, the text of every delivery, leak
patterns, outcome scoring, and the domain wording the judge needs.

Test of the split: a new adapter must not require any change to core.

Vocabulary used throughout core:
    answer          the task's main structured claim (cohort_identity: the cancer type). Recorded at
                    every checkpoint under `answer_field`.
    answer code     the adapter's canonical form of an answer, from `classify_answer`, or one of the
                    sentinels UNDETERMINED / AMBIGUOUS / OTHER.
    basis           what an answer rests on. Agent-facing values are adapter-defined; each maps to one
                    of the core BASIS_CLASSES so core rules can reason about it.
    salient tokens  strings whose appearance in a tool output the trace records (cohort_identity:
                    lineage marker genes, under their real or anonymized names).
"""
from __future__ import annotations

import re

UNDETERMINED, AMBIGUOUS, OTHER = "UNDETERMINED", "AMBIGUOUS", "OTHER"
SENTINELS = (UNDETERMINED, AMBIGUOUS, OTHER)

# Core basis classes. Adapter basis values each map to exactly one.
BASIS_CLASSES = ("computed_from_data", "prior_knowledge", "provided_information", "none")

EVIDENCE_STEPS_DESCRIPTION = (
    "Tool-call numbers of the run_code calls that produced the evidence "
    "(each run_code result is numbered 'call N'). Empty if none."
)


class TaskAdapter:
    """Subclass and fill in the class attributes and methods marked ADAPTER."""

    # ---- identity (ADAPTER) -------------------------------------------------------------------
    name: str = "base"
    answer_field: str = "answer"            # key of the answer block in record_observation
    answer_description: str = ""            # shown to the agent (schema description)
    call_description: str = ""              # shown to the agent for answer.call
    basis_values: tuple[str, ...] = ()      # agent-facing enum
    basis_description: str = ""
    basis_class: dict[str, str] = {}        # basis value -> one of BASIS_CLASSES
    claim_scopes: tuple[str, ...] = ()      # record_milestone scope enum
    answer_codes: tuple[str, ...] = ()      # canonical answer space (never shown to the agent)

    # ---- answers (ADAPTER) --------------------------------------------------------------------
    def classify_answer(self, text: str) -> str:
        raise NotImplementedError

    def mentioned_answers(self, text: str) -> list[str]:
        raise NotImplementedError

    def answer_name(self, code: str) -> str:
        return code

    # ---- visibility (ADAPTER) -----------------------------------------------------------------
    def salient_tokens(self) -> frozenset[str]:
        """Entities whose appearance in tool outputs the trace records."""
        return frozenset()

    def salient_for(self, code: str) -> list[str]:
        """Salient tokens that indicate answer `code` (used by the anchoring flag)."""
        return []

    # ---- blinding (ADAPTER) -------------------------------------------------------------------
    disclosure_regex: re.Pattern | None = None   # the harness sentence that delivers an answer
    def leak_patterns(self, code: str) -> list[str]:
        return []

    # ---- judge wording (ADAPTER) --------------------------------------------------------------
    judge_domain: str = "a scientific dataset"
    judge_partly_example: str = ""
    judge_contradicts_example: str = ""

    # ---- derived (CORE: do not override) ------------------------------------------------------
    def basis_is_computed(self, basis: str | None) -> bool:
        return self.basis_class.get(basis or "") == "computed_from_data"

    def is_named(self, code: str | None) -> bool:
        return code is not None and code not in SENTINELS

    def answer_schema(self) -> dict:
        """The record_observation answer block, built from the adapter's wording."""
        return {
            "type": "object",
            "description": self.answer_description,
            "properties": {
                "call": {"type": "string", "description": self.call_description},
                "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
                "basis": {"type": "string", "enum": list(self.basis_values),
                          "description": self.basis_description},
                "evidence_steps": {"type": "array", "items": {"type": "integer"},
                                   "description": EVIDENCE_STEPS_DESCRIPTION},
            },
            "required": ["call", "confidence", "basis", "evidence_steps"],
        }

    def check(self) -> None:
        """Fail fast on an inconsistent adapter."""
        missing = [b for b in self.basis_values if self.basis_class.get(b) not in BASIS_CLASSES]
        if missing:
            raise ValueError(f"{self.name}: basis values without a valid core class: {missing}")
        if not self.answer_field or not self.claim_scopes:
            raise ValueError(f"{self.name}: answer_field and claim_scopes are required")
