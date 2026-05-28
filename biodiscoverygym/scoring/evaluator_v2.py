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

Phase 2 component weights (sum = 5) — only scored when Phase 2 data exists:
  p2_commit_quality           1
  p2_experiment_depth         2
  p2_mechanistic_integration  2
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
    score_marker_evidence,
    score_p2_commit_quality,
    score_pathway_validity,
    score_reference_concordance,
    score_rppa_concordance,
    score_structure_validity,
)
from .judge import (
    score_experiment_quality,
    score_mechanism_grounding,
    score_p2_experiment_depth,
    score_p2_mechanistic_integration,
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

PHASE2_WEIGHTS: dict[str, float] = {
    "p2_commit_quality": 1.0,
    "p2_experiment_depth": 2.0,
    "p2_mechanistic_integration": 2.0,
}
PHASE2_MAX: float = sum(PHASE2_WEIGHTS.values())  # 5.0


@dataclass
class Phase2Report:
    """Scoring results for the Phase 2 commit + Q&A track."""
    raw_scores: dict[str, float] = field(default_factory=dict)
    weighted_scores: dict[str, float] = field(default_factory=dict)
    diagnostics: dict[str, dict] = field(default_factory=dict)
    total_raw: float = 0.0
    total_max: float = PHASE2_MAX
    normalized: float = 0.0
    commit_report_length: int = 0
    n_phase2_answers: int = 0

    def to_dict(self) -> dict:
        return {
            "raw_scores": self.raw_scores,
            "weighted_scores": self.weighted_scores,
            "diagnostics": self.diagnostics,
            "total_raw": self.total_raw,
            "total_max": self.total_max,
            "normalized": self.normalized,
            "commit_report_length": self.commit_report_length,
            "n_phase2_answers": self.n_phase2_answers,
        }

    def pretty_print(self) -> str:
        if self.commit_report_length == 0 and self.n_phase2_answers == 0:
            return "  Phase 2 : not run"
        lines = [
            f"  {'Phase 2 Component':<33} {'Raw':>6}  {'Weight':>6}  {'Pts':>6}",
            "  " + "-" * 58,
        ]
        for key, raw in self.raw_scores.items():
            w = PHASE2_WEIGHTS.get(key, 0)
            pts = self.weighted_scores.get(key, 0)
            lines.append(f"  {key:<35} {raw:>6.3f}  {w:>6.1f}  {pts:>6.3f}")
        lines += [
            "  " + "-" * 58,
            f"  {'PHASE2 TOTAL':<35} {'':>6}  {self.total_max:>6.1f}  {self.total_raw:>6.3f}",
            f"  {'PHASE2 NORMALIZED (0-1)':<35} {'':>6}  {'':>6}  {self.normalized:>6.4f}",
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
    phase2: Phase2Report | None = None

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
        if self.phase2 is not None:
            d["phase2"] = self.phase2.to_dict()
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
        if self.phase2 is not None:
            lines += ["", self.phase2.pretty_print()]
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

    def score_phase2(
        self,
        commit_report: str,
        phase2_answers: list[str],
    ) -> Phase2Report:
        """
        Score Phase 2 (commit + Q1-Q4) data if present. Returns an empty
        Phase2Report (all zeros) when no Phase 2 data was collected.
        """
        report = Phase2Report()
        report.commit_report_length = len(commit_report)
        report.n_phase2_answers = len(phase2_answers)

        if not commit_report and not phase2_answers:
            return report

        phase2_text = "\n\n".join(phase2_answers)

        def _record(key: str, score: float, diag: dict):
            w = PHASE2_WEIGHTS[key]
            report.raw_scores[key] = score
            report.weighted_scores[key] = score * w
            report.diagnostics[key] = diag

        # 1. Commit quality (computational)
        s, d = score_p2_commit_quality(commit_report)
        _record("p2_commit_quality", s, d)

        # 2. Experiment depth (LLM judge on Q4)
        s, d = score_p2_experiment_depth(phase2_text, commit_report, model=self.llm_model)
        _record("p2_experiment_depth", s, d)

        # 3. Mechanistic integration (LLM judge on all Q1-Q4)
        s, d = score_p2_mechanistic_integration(phase2_answers, commit_report, model=self.llm_model)
        _record("p2_mechanistic_integration", s, d)

        report.total_raw = sum(report.weighted_scores.values())
        report.normalized = report.total_raw / PHASE2_MAX
        return report
