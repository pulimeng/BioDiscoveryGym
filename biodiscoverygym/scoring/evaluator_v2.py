"""
BioDiscoveryGym v2 scoring orchestrator.

Calls all component scorers, applies weights, returns a ScoreReport.

Phase 1 component weights (sum = 18):
  structure_validity          2
  clinical_signal             3
  genomic_coherence_drivers   2  ─┐ "genomic coherence" block
  genomic_coherence_rppa      2  ─┘
  reference_concordance       2
  marker_evidence             2
  pathway_validity            1
  mechanism_grounding         2
  experiment_quality          2

Examination component weights (sum = 5) — only scored when Examination data exists:
  exam_data_lock_quality      1
  exam_experiment_depth       2
  exam_mechanistic_integration 2
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd

from .components import (
    score_clinical_signal,
    score_driver_enrichment,
    score_exam_data_lock_quality,
    score_marker_evidence,
    score_pathway_validity,
    score_reference_concordance,
    score_rppa_concordance,
    score_structure_validity,
)
from .judge import (
    score_exam_experiment_depth,
    score_exam_mechanistic_integration,
    score_experiment_quality,
    score_mechanism_grounding,
)

COMPONENT_WEIGHTS: dict[str, float] = {
    "structure_validity": 2.0,
    "clinical_signal": 3.0,
    "genomic_coherence_drivers": 2.0,
    "genomic_coherence_rppa": 2.0,
    "reference_concordance": 2.0,
    "marker_evidence": 2.0,
    "pathway_validity": 1.0,
    "mechanism_grounding": 2.0,
    "experiment_quality": 2.0,
}
TOTAL_MAX: float = sum(COMPONENT_WEIGHTS.values())  # 18.0

EXAMINATION_WEIGHTS: dict[str, float] = {
    "exam_data_lock_quality": 1.0,
    "exam_experiment_depth": 2.0,
    "exam_mechanistic_integration": 2.0,
}
EXAMINATION_MAX: float = sum(EXAMINATION_WEIGHTS.values())  # 5.0


@dataclass
class ExaminationReport:
    """Scoring results for the Examination stage (Data Lock + Q1-Q4)."""
    raw_scores: dict[str, float] = field(default_factory=dict)
    weighted_scores: dict[str, float] = field(default_factory=dict)
    diagnostics: dict[str, dict] = field(default_factory=dict)
    total_raw: float = 0.0
    total_max: float = EXAMINATION_MAX
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
            f"  {'Examination Component':<33} {'Raw':>6}  {'Weight':>6}  {'Pts':>6}",
            "  " + "-" * 58,
        ]
        for key, raw in self.raw_scores.items():
            w = EXAMINATION_WEIGHTS.get(key, 0)
            pts = self.weighted_scores.get(key, 0)
            lines.append(f"  {key:<35} {raw:>6.3f}  {w:>6.1f}  {pts:>6.3f}")
        lines += [
            "  " + "-" * 58,
            f"  {'EXAMINATION TOTAL':<35} {'':>6}  {self.total_max:>6.1f}  {self.total_raw:>6.3f}",
            f"  {'EXAMINATION NORMALIZED (0-1)':<35} {'':>6}  {'':>6}  {self.normalized:>6.4f}",
        ]
        return "\n".join(lines)


@dataclass
class ScoreReport:
    raw_scores: dict[str, float] = field(default_factory=dict)
    weighted_scores: dict[str, float] = field(default_factory=dict)
    diagnostics: dict[str, dict] = field(default_factory=dict)
    total_raw: float = 0.0
    total_max: float = TOTAL_MAX
    normalized: float = 0.0
    wall_time_s: float = 0.0
    examination: ExaminationReport | None = None

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
        return d

    def pretty_print(self) -> str:
        lines = [
            f"{'Component':<35} {'Raw':>6}  {'Weight':>6}  {'Pts':>6}",
            "-" * 60,
        ]
        for key, raw in self.raw_scores.items():
            w = COMPONENT_WEIGHTS.get(key, 0)
            pts = self.weighted_scores.get(key, 0)
            lines.append(f"  {key:<33} {raw:>6.3f}  {w:>6.1f}  {pts:>6.3f}")
        lines += [
            "-" * 60,
            f"  {'TOTAL':<33} {'':>6}  {self.total_max:>6.1f}  {self.total_raw:>6.3f}",
            f"  {'NORMALIZED (0-1)':<33} {'':>6}  {'':>6}  {self.normalized:>6.4f}",
        ]
        if self.examination is not None:
            lines += ["", self.examination.pretty_print()]
        return "\n".join(lines)


class EvaluatorV2:
    def __init__(
        self,
        data_dir: str | Path = "data",
        llm_model: str = "claude-sonnet-4-6",
    ):
        self.data_dir = Path(data_dir)
        self.llm_model = llm_model

        self.cancer_genes_path = self.data_dir / "cancer_genes" / "oncokb_cancer_gene_list.tsv"
        self.genesets_dir = self.data_dir / "genesets"
        self.pancan_path = self.data_dir / "subtypes" / "pancan_subtypes.tsv"
        self.tcgasubtype_path = self.data_dir / "subtypes" / "TCGASubtype.20170308.tsv.gz"

    def score(
        self,
        discovery: dict[str, Any],
        expression: pd.DataFrame,
        metadata: pd.DataFrame,
        mutation: pd.DataFrame | None,
        rppa: pd.DataFrame | None,
        sample_id_map: dict[str, str],
        cohort: str,
    ) -> ScoreReport:
        t0 = time.time()
        report = ScoreReport()

        # --- Unpack discovery fields ---
        grouping: dict[str, str] = discovery.get("proposed_grouping", {})
        top_genes: list[str] = discovery.get("top_genes", [])
        pathway_evidence: list[str] = discovery.get("pathway_evidence", [])
        mechanism_hypothesis: str = discovery.get("mechanism_hypothesis", "")
        next_experiment: str = discovery.get("next_experiment", "")

        if not grouping:
            report.wall_time_s = time.time() - t0
            return report

        def _record(key: str, score: float, diag: dict):
            w = COMPONENT_WEIGHTS[key]
            report.raw_scores[key] = score
            report.weighted_scores[key] = score * w
            report.diagnostics[key] = diag

        # 1. Structure validity
        s, d = score_structure_validity(grouping, expression)
        _record("structure_validity", s, d)

        # 2. Clinical signal
        s, d = score_clinical_signal(grouping, metadata)
        _record("clinical_signal", s, d)

        # 3. Genomic coherence — drivers
        s, d = score_driver_enrichment(grouping, mutation, self.cancer_genes_path)
        _record("genomic_coherence_drivers", s, d)

        # 4. Genomic coherence — RPPA
        s, d = score_rppa_concordance(grouping, rppa)
        _record("genomic_coherence_rppa", s, d)

        # 5. Reference concordance
        s, d = score_reference_concordance(
            grouping,
            sample_id_map,
            cohort,
            self.pancan_path,
            self.tcgasubtype_path,
        )
        _record("reference_concordance", s, d)

        # 6. Marker evidence
        s, d = score_marker_evidence(top_genes, grouping, expression, self.cancer_genes_path)
        _record("marker_evidence", s, d)

        # 7. Pathway validity
        s, d = score_pathway_validity(pathway_evidence, top_genes, self.genesets_dir)
        _record("pathway_validity", s, d)

        # 8. Mechanism grounding (LLM judge)
        s, d = score_mechanism_grounding(
            mechanism_hypothesis,
            pathway_evidence,
            top_genes,
            model=self.llm_model,
        )
        _record("mechanism_grounding", s, d)

        # 9. Experiment quality (LLM judge)
        s, d = score_experiment_quality(next_experiment, model=self.llm_model)
        _record("experiment_quality", s, d)

        report.total_raw = sum(report.weighted_scores.values())
        report.normalized = report.total_raw / TOTAL_MAX
        report.wall_time_s = time.time() - t0
        return report

    def score_examination(
        self,
        data_lock_report: str,
        examination_answers: list[str],
    ) -> ExaminationReport:
        """
        Score the Examination stage (Data Lock + Q1-Q4). Returns an empty
        ExaminationReport (all zeros) when no Examination data was collected.
        """
        report = ExaminationReport()
        report.data_lock_length = len(data_lock_report)
        report.n_examination_answers = len(examination_answers)

        if not data_lock_report and not examination_answers:
            return report

        def _record(key: str, score: float, diag: dict):
            w = EXAMINATION_WEIGHTS[key]
            report.raw_scores[key] = score
            report.weighted_scores[key] = score * w
            report.diagnostics[key] = diag

        # 1. Data Lock quality (computational)
        s, d = score_exam_data_lock_quality(data_lock_report)
        _record("exam_data_lock_quality", s, d)

        # 2. Experiment depth (LLM judge on Q4 only — always the last answer block)
        q4_text = examination_answers[-1] if examination_answers else ""
        s, d = score_exam_experiment_depth(q4_text, data_lock_report, model=self.llm_model)
        _record("exam_experiment_depth", s, d)

        # 3. Mechanistic integration (LLM judge on Q1-Q4)
        s, d = score_exam_mechanistic_integration(examination_answers, data_lock_report, model=self.llm_model)
        _record("exam_mechanistic_integration", s, d)

        report.total_raw = sum(report.weighted_scores.values())
        report.normalized = report.total_raw / EXAMINATION_MAX
        return report
