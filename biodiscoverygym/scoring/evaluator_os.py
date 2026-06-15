"""
BioDiscoveryGym OS discovery scorer.

DISCOVERY framing — for SGH-OS (Jia et al. 2022) and external osteosarcoma cohorts
where the goal is finding prognostic biomarkers beyond what the reference paper reports.

For TCGA cohorts (faithfulness framing, known answer), use evaluator_v3.EvaluatorV3.

Phase 1 — structural + computational (15 pts):
  structure_validity         2
  survival_stratification    3
  provenance_integrity       3
  mechanistic_grounding      3
  cross_modal_support        2
  validation_experiment      2

Phase 2 — Examination (3 pts), scored only when post-submission data exists:
  exam_data_lock_quality          1
  exam_mechanistic_integration    2

Phase 3 — External validation in TARGET-OS (5 pts), scored only when TARGET data available:
  target_coexpr_replication    2
  target_survival_replication  3

Total max = 23 pts.
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd

from .components import (
    score_exam_data_lock_quality,
    score_structure_validity,
)
from .components_os import (
    score_cross_modal_support,
    score_provenance_integrity,
    score_survival_stratification,
    score_target_coexpr_replication,
    score_target_survival_replication,
)
from .judge import (
    score_experiment_quality,
)
from .judge_os import (
    score_exam_mechanistic_integration_os,
    score_mechanism_grounding_os,
)
from .evaluator_v3 import TraceReport, extract_examination_data, trace_episode


# ---------------------------------------------------------------------------
# Weights
# ---------------------------------------------------------------------------

OS_COMPONENT_WEIGHTS: dict[str, float] = {
    "structure_validity": 2.0,
    "survival_stratification": 3.0,
    "provenance_integrity": 3.0,
    "mechanistic_grounding": 3.0,
    "cross_modal_support": 2.0,
    "validation_experiment": 2.0,
}
OS_TOTAL_MAX: float = sum(OS_COMPONENT_WEIGHTS.values())  # 15.0

OS_EXAMINATION_WEIGHTS: dict[str, float] = {
    "exam_data_lock_quality": 1.0,
    "exam_mechanistic_integration": 2.0,
}
OS_EXAMINATION_MAX: float = sum(OS_EXAMINATION_WEIGHTS.values())  # 3.0

OS_VALIDATION_WEIGHTS: dict[str, float] = {
    "target_coexpr_replication": 2.0,
    "target_survival_replication": 3.0,
}
OS_VALIDATION_MAX: float = sum(OS_VALIDATION_WEIGHTS.values())  # 5.0


# ---------------------------------------------------------------------------
# Report dataclasses
# ---------------------------------------------------------------------------

@dataclass
class OSExaminationReport:
    raw_scores: dict[str, float] = field(default_factory=dict)
    weighted_scores: dict[str, float] = field(default_factory=dict)
    diagnostics: dict[str, dict] = field(default_factory=dict)
    total_raw: float = 0.0
    total_max: float = OS_EXAMINATION_MAX
    normalized: float = 0.0
    data_lock_length: int = 0
    n_examination_answers: int = 0

    def to_dict(self) -> dict:
        return {
            "raw_scores": self.raw_scores,
            "weighted_scores": self.weighted_scores,
            "diagnostics": self.diagnostics,
            "total_raw": self.total_raw,
            "total_max": self.total_max,
            "normalized": self.normalized,
            "data_lock_length": self.data_lock_length,
            "n_examination_answers": self.n_examination_answers,
        }

    def pretty_print(self) -> str:
        if self.data_lock_length == 0 and self.n_examination_answers == 0:
            return "  Examination : not run"
        lines = [
            f"  {'Examination Component':<33} {'Raw':>8}  {'Weight':>6}  {'Pts':>6}",
            "  " + "-" * 60,
        ]
        for key, raw in self.raw_scores.items():
            w = OS_EXAMINATION_WEIGHTS.get(key, 0)
            pts = self.weighted_scores.get(key, 0)
            diag = self.diagnostics.get(key, {})
            raw_str = " LLM_ERR" if isinstance(diag, dict) and diag.get("error") else f"{raw:>8.3f}"
            lines.append(f"  {key:<35} {raw_str}  {w:>6.1f}  {pts:>6.3f}")
        lines += [
            "  " + "-" * 60,
            f"  {'EXAMINATION TOTAL':<35} {'':>8}  {self.total_max:>6.1f}  {self.total_raw:>6.3f}",
            f"  {'EXAMINATION NORMALIZED (0-1)':<35} {'':>8}  {'':>6}  {self.normalized:>6.4f}",
        ]
        return "\n".join(lines)


@dataclass
class OSExternalValidationReport:
    raw_scores: dict[str, float] = field(default_factory=dict)
    weighted_scores: dict[str, float] = field(default_factory=dict)
    diagnostics: dict[str, dict] = field(default_factory=dict)
    total_raw: float = 0.0
    total_max: float = OS_VALIDATION_MAX
    normalized: float = 0.0
    target_available: bool = False

    def to_dict(self) -> dict:
        return {
            "raw_scores": self.raw_scores,
            "weighted_scores": self.weighted_scores,
            "diagnostics": self.diagnostics,
            "total_raw": self.total_raw,
            "total_max": self.total_max,
            "normalized": self.normalized,
            "target_available": self.target_available,
        }

    def pretty_print(self) -> str:
        if not self.target_available:
            return "  External Validation : TARGET-OS data not available"
        lines = [
            f"  {'External Validation Component':<33} {'Raw':>6}  {'Weight':>6}  {'Pts':>6}",
            "  " + "-" * 58,
        ]
        for key, raw in self.raw_scores.items():
            w = OS_VALIDATION_WEIGHTS.get(key, 0)
            pts = self.weighted_scores.get(key, 0)
            lines.append(f"  {key:<35} {raw:>6.3f}  {w:>6.1f}  {pts:>6.3f}")
        lines += [
            "  " + "-" * 58,
            f"  {'EXTERNAL VAL TOTAL':<35} {'':>6}  {self.total_max:>6.1f}  {self.total_raw:>6.3f}",
            f"  {'EXTERNAL VAL NORMALIZED (0-1)':<35} {'':>6}  {'':>6}  {self.normalized:>6.4f}",
        ]
        return "\n".join(lines)


@dataclass
class OSScoreReport:
    raw_scores: dict[str, float] = field(default_factory=dict)
    weighted_scores: dict[str, float] = field(default_factory=dict)
    diagnostics: dict[str, dict] = field(default_factory=dict)
    total_raw: float = 0.0
    total_max: float = OS_TOTAL_MAX
    normalized: float = 0.0
    wall_time_s: float = 0.0
    examination: OSExaminationReport | None = None
    external_validation: OSExternalValidationReport | None = None

    def to_dict(self) -> dict:
        d = {
            "raw_scores": self.raw_scores,
            "weighted_scores": self.weighted_scores,
            "diagnostics": self.diagnostics,
            "total_raw": self.total_raw,
            "total_max": self.total_max,
            "normalized": self.normalized,
            "wall_time_s": self.wall_time_s,
        }
        if self.examination is not None:
            d["examination"] = self.examination.to_dict()
        if self.external_validation is not None:
            d["external_validation"] = self.external_validation.to_dict()
        # Composite metrics — discovery = internal × external transfer
        d["internal_norm"] = self.internal_norm
        d["external_norm"] = self.external_norm
        d["composite_discovery"] = self.composite_discovery
        return d

    @property
    def grand_total_raw(self) -> float:
        """Sum of Phase 1 + Phase 2 + Phase 3 raw weighted points."""
        t = self.total_raw
        if self.examination is not None:
            t += self.examination.total_raw
        if self.external_validation is not None:
            t += self.external_validation.total_raw
        return t

    @property
    def grand_total_max(self) -> float:
        t = self.total_max
        if self.examination is not None:
            t += self.examination.total_max
        if self.external_validation is not None:
            t += self.external_validation.total_max
        return t

    @property
    def internal_norm(self) -> float:
        """(Phase 1 + Phase 2) normalized to [0,1]."""
        num = self.total_raw + (self.examination.total_raw if self.examination else 0.0)
        denom = self.total_max + (self.examination.total_max if self.examination else 0.0)
        return num / denom if denom > 0 else 0.0

    @property
    def external_norm(self) -> float:
        """Phase 3 normalized to [0,1]."""
        if self.external_validation is None or self.external_validation.total_max <= 0:
            return 0.0
        return self.external_validation.total_raw / self.external_validation.total_max

    @property
    def composite_discovery(self) -> float:
        """Geometric mean of internal and external normalized scores.

        Discovery = rigorous methodology AND external transferability.
        Geometric mean punishes any axis being low — a perfect internal score
        with failed TARGET replication is bounded by sqrt(1 * 0.05) ≈ 0.22.
        Symmetric: strong external with weak internal is also dampened.
        """
        i, e = self.internal_norm, self.external_norm
        if i <= 0 or e <= 0:
            return 0.0
        return math.sqrt(i * e)

    def pretty_print(self) -> str:
        lines = [
            f"{'Component':<35} {'Raw':>8}  {'Weight':>6}  {'Pts':>6}",
            "-" * 62,
        ]
        for key, raw in self.raw_scores.items():
            w = OS_COMPONENT_WEIGHTS.get(key, 0)
            pts = self.weighted_scores.get(key, 0)
            diag = self.diagnostics.get(key, {})
            # Distinguish "real 0" from "errored to 0" — an LLM judge that
            # crashed should not look identical to a genuinely scored 0.
            raw_str = " LLM_ERR" if isinstance(diag, dict) and diag.get("error") else f"{raw:>8.3f}"
            lines.append(f"  {key:<33} {raw_str}  {w:>6.1f}  {pts:>6.3f}")
        lines += [
            "-" * 62,
            f"  {'PHASE 1 TOTAL':<33} {'':>8}  {self.total_max:>6.1f}  {self.total_raw:>6.3f}",
            f"  {'PHASE 1 NORMALIZED (0-1)':<33} {'':>8}  {'':>6}  {self.normalized:>6.4f}",
        ]
        if self.examination is not None:
            lines += ["", self.examination.pretty_print()]
        if self.external_validation is not None:
            lines += ["", self.external_validation.pretty_print()]
        lines += [
            "",
            "=" * 62,
            f"  GRAND TOTAL                       {self.grand_total_max:>8.1f}  {self.grand_total_raw:>6.3f}",
            f"  GRAND NORMALIZED (0-1)                            {self.grand_total_raw / self.grand_total_max if self.grand_total_max > 0 else 0.0:>6.4f}",
            "",
            f"  Internal norm (Phase 1+2)                         {self.internal_norm:>6.4f}",
            f"  External norm (Phase 3)                           {self.external_norm:>6.4f}",
            f"  COMPOSITE DISCOVERY  √(int × ext)                 {self.composite_discovery:>6.4f}",
        ]
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Stub components — replaced with real implementations in steps 2-4
# ---------------------------------------------------------------------------

def _stub(reason: str = "not yet implemented") -> tuple[float, dict]:
    return 0.0, {"skipped": True, "reason": reason}


# ---------------------------------------------------------------------------
# EvaluatorOS
# ---------------------------------------------------------------------------

class EvaluatorOS:
    """
    OS discovery scorer.

    Three phases:
      Phase 1 — structural + computational (score())
      Phase 2 — post-submission Examination (score_examination())
      Phase 3 — TARGET-OS external validation (score_external_validation())

    Use score_full() to run all three phases plus trace extraction.
    """

    def __init__(
        self,
        data_dir: str | Path = "data",
        llm_model: str = "claude-sonnet-4-6",
        target_data_dir: str | Path = "data/external/TARGET",
    ):
        self.data_dir = Path(data_dir)
        self.llm_model = llm_model
        self.target_data_dir = Path(target_data_dir)

    # ------------------------------------------------------------------
    # Phase 1
    # ------------------------------------------------------------------

    def score(
        self,
        discovery: dict[str, Any],
        expression: pd.DataFrame,
        metadata: pd.DataFrame,
        mutation: pd.DataFrame | None,
        methylation: pd.DataFrame | None = None,
        cna: pd.DataFrame | None = None,
    ) -> OSScoreReport:
        t0 = time.time()
        report = OSScoreReport()

        grouping: dict[str, str] = discovery.get("proposed_grouping", {})
        top_genes: list[str] = discovery.get("top_genes", [])
        pathway_evidence: list[str] = discovery.get("pathway_evidence", [])
        mechanism_hypothesis: str = discovery.get("mechanism_hypothesis", "")
        next_experiment: str = discovery.get("next_experiment", "")

        if not grouping:
            report.wall_time_s = time.time() - t0
            return report

        def _record(key: str, score: float, diag: dict):
            w = OS_COMPONENT_WEIGHTS[key]
            report.raw_scores[key] = score
            report.weighted_scores[key] = score * w
            report.diagnostics[key] = diag

        # 1. Structure validity (reused from TCGA stack)
        s, d = score_structure_validity(grouping, expression)
        _record("structure_validity", s, d)

        # 2. Survival stratification
        s, d = score_survival_stratification(grouping, metadata)
        _record("survival_stratification", s, d)

        # 3. Provenance integrity
        s, d = score_provenance_integrity(
            top_genes, grouping, expression, metadata, methylation, cna
        )
        _record("provenance_integrity", s, d)

        # 4. Mechanistic grounding (OS-specific LLM judge)
        s, d = score_mechanism_grounding_os(
            mechanism_hypothesis, pathway_evidence, top_genes, model=self.llm_model
        )
        _record("mechanistic_grounding", s, d)

        # 5. Cross-modal support
        s, d = score_cross_modal_support(
            top_genes, grouping, expression, metadata, methylation, cna
        )
        _record("cross_modal_support", s, d)

        # 6. Validation experiment (reused from TCGA stack)
        s, d = score_experiment_quality(next_experiment, model=self.llm_model)
        _record("validation_experiment", s, d)

        report.total_raw = sum(report.weighted_scores.values())
        report.normalized = report.total_raw / OS_TOTAL_MAX if OS_TOTAL_MAX > 0 else 0.0
        report.wall_time_s = time.time() - t0
        return report

    # ------------------------------------------------------------------
    # Phase 2 — Examination
    # ------------------------------------------------------------------

    def score_examination(
        self,
        data_lock_report: str,
        examination_answers: list[str],
    ) -> OSExaminationReport:
        report = OSExaminationReport()
        report.data_lock_length = len(data_lock_report)
        report.n_examination_answers = len(examination_answers)

        if not data_lock_report and not examination_answers:
            return report

        def _record(key: str, score: float, diag: dict):
            w = OS_EXAMINATION_WEIGHTS[key]
            report.raw_scores[key] = score
            report.weighted_scores[key] = score * w
            report.diagnostics[key] = diag

        # 1. Data Lock quality (reused from TCGA stack)
        s, d = score_exam_data_lock_quality(data_lock_report)
        _record("exam_data_lock_quality", s, d)

        # 2. Mechanistic integration (OS-specific LLM judge)
        s, d = score_exam_mechanistic_integration_os(
            examination_answers, data_lock_report, model=self.llm_model
        )
        _record("exam_mechanistic_integration", s, d)

        report.total_raw = sum(report.weighted_scores.values())
        report.normalized = report.total_raw / OS_EXAMINATION_MAX if OS_EXAMINATION_MAX > 0 else 0.0
        return report

    # ------------------------------------------------------------------
    # Phase 3 — TARGET-OS external validation
    # ------------------------------------------------------------------

    def score_external_validation(
        self,
        discovery: dict[str, Any],
        expression: pd.DataFrame,
        metadata: pd.DataFrame,
    ) -> OSExternalValidationReport:
        report = OSExternalValidationReport()

        target_expr_path = self.target_data_dir / "expression.parquet"
        if not target_expr_path.exists():
            report.diagnostics["_setup"] = {
                "reason": f"TARGET data not found at {target_expr_path}"
            }
            return report

        report.target_available = True

        def _record(key: str, score: float, diag: dict):
            w = OS_VALIDATION_WEIGHTS[key]
            report.raw_scores[key] = score
            report.weighted_scores[key] = score * w
            report.diagnostics[key] = diag

        top_genes: list[str] = discovery.get("top_genes", [])

        # 1. Co-expression replication
        s, d = score_target_coexpr_replication(
            top_genes=top_genes,
            sgh_expression=expression,
            sgh_metadata=metadata,
            target_data_dir=self.target_data_dir,
        )
        _record("target_coexpr_replication", s, d)

        # 2. Survival replication
        s, d = score_target_survival_replication(
            top_genes=top_genes,
            sgh_expression=expression,
            sgh_metadata=metadata,
            target_data_dir=self.target_data_dir,
        )
        _record("target_survival_replication", s, d)

        report.total_raw = sum(report.weighted_scores.values())
        report.normalized = report.total_raw / OS_VALIDATION_MAX if OS_VALIDATION_MAX > 0 else 0.0
        return report

    # ------------------------------------------------------------------
    # Combined entry point
    # ------------------------------------------------------------------

    def score_full(
        self,
        discovery: dict[str, Any],
        expression: pd.DataFrame,
        metadata: pd.DataFrame,
        mutation: pd.DataFrame | None,
        methylation: pd.DataFrame | None,
        cna: pd.DataFrame | None,
        messages: list[dict],
        run_log: dict | None = None,
    ) -> tuple[OSScoreReport, TraceReport]:
        """Run Phase 1 + 2 + 3 + trace extraction. Returns (score, trace)."""
        score_report = self.score(
            discovery=discovery,
            expression=expression,
            metadata=metadata,
            mutation=mutation,
            methylation=methylation,
            cna=cna,
        )

        # Phase 2: prefer runtime-captured Data Lock; fall back to message extraction
        data_lock_report = discovery.get("data_lock_report", "")
        extracted_lock, examination_answers = extract_examination_data(messages)
        data_lock_report = data_lock_report or extracted_lock

        score_report.examination = self.score_examination(data_lock_report, examination_answers)

        # Phase 3: TARGET external validation
        score_report.external_validation = self.score_external_validation(
            discovery=discovery,
            expression=expression,
            metadata=metadata,
        )

        trace_report = trace_episode(messages, run_log=run_log)
        return score_report, trace_report
