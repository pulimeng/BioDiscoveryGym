"""
BioDiscoveryGym v2 scoring orchestrator (TCGA faithfulness rubric).

Calls all component scorers, applies weights, returns a ScoreReport.

Phase 1 component weights (sum = 16):
  structure_validity          2
  clinical_signal             3
  genomic_coherence_drivers   2  ─┐ "genomic coherence" block
  genomic_coherence_rppa      2  ─┘
  reference_concordance       2
  marker_evidence             2
  pathway_validity            1
  mechanism_grounding         2  ← only LLM judge for TCGA; tests data-grounding axis

experiment_quality removed 2026-06-15: it scored "scientific competence at
experimental design" (named model + CRISPR + assay + magnitude) which is
orthogonal to faithfulness recovery of known subtypes. mechanism_grounding's
data_grounding axis is the LLM-judge component that actually distinguishes
data-derivation from literature recall — the signal we want for TCGA.

Examination component weights (sum = 5) — only attached when Examination data
exists (i.e., agent ran without --no-examination). TCGA runs no longer use
Examination by default; these weights remain for back-compat scoring of
historical episodes:
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
    score_cohort_identity,
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
}
TOTAL_MAX: float = sum(COMPONENT_WEIGHTS.values())  # 16.0

# Cohort-identity gate (NOT a scored dimension — it would be meaningless for G0-G2,
# where the cohort is given or uncontested). If the agent commits to the WRONG cancer
# type, the disease-INTERPRETATION dimensions are built on a false premise and are
# zeroed; the objective computational dims stand, since a fooled agent can still have
# produced a valid partition. In practice this fires only in the G3 mislead arms. The
# un-gated raw component scores are retained in `raw_scores` for transparency.
_FOOLED_NARRATIVE_KEYS: tuple[str, ...] = ("mechanism_grounding", "pathway_validity")

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
    # Cohort-identity gate
    gated: bool = False                 # True → narrative dims zeroed (wrong cohort)
    cohort_identity_verdict: str = ""   # true_cohort | mislead_cohort | other | hedged | error

    def to_dict(self) -> dict:
        d = {
            "raw_scores": self.raw_scores,
            "weighted_scores": self.weighted_scores,
            "diagnostics": self.diagnostics,
            "total_raw": self.total_raw,
            "total_max": self.total_max,
            "normalized": self.normalized,
            "wall_time_s": self.wall_time_s,
            "gated": self.gated,
            "cohort_identity_verdict": self.cohort_identity_verdict,
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
        if self.gated:
            lines.append(
                f"  >> GATED: wrong cohort identity ({self.cohort_identity_verdict}) "
                f"— narrative dims (mechanism_grounding, pathway_validity) zeroed "
                f"(raw shown above)"
            )
        lines += [
            "-" * 60,
            f"  {'TOTAL':<33} {'':>6}  {self.total_max:>6.1f}  {self.total_raw:>6.3f}",
            f"  {'NORMALIZED (0-1)':<33} {'':>6}  {'':>6}  {self.normalized:>6.4f}",
        ]
        if self.gated:
            lines.append(f"  {'(cohort identity verdict)':<33} {self.cohort_identity_verdict:>21}")
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
        mislead_cohort: str | None = None,
    ) -> ScoreReport:
        t0 = time.time()
        report = ScoreReport()

        # --- Unpack discovery fields ---
        grouping: dict[str, str] = discovery.get("proposed_grouping", {})
        top_genes: list[str] = discovery.get("top_genes", [])
        pathway_evidence: list[str] = discovery.get("pathway_evidence", [])
        mechanism_hypothesis: str = discovery.get("mechanism_hypothesis", "")
        # next_experiment is preserved in the discovery payload for downstream
        # analysis but no longer scored (Option B, 2026-06-15).

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

        # experiment_quality removed 2026-06-15 (Option B) — see module docstring.
        # score_experiment_quality is still imported because the OS scorer
        # uses it as its `validation_experiment` component.

        # --- Cohort-identity gate ---
        # Detect (via LLM judge) which cancer type the agent committed to.
        # If it is the WRONG one (the mislead, or any other wrong cancer), the disease-
        # interpretation dims rest on a false premise → zero mechanism_grounding +
        # pathway_validity. The objective computational dims (clustering, survival,
        # driver/RPPA coherence, reference concordance, markers) stand — a fooled agent
        # can still have produced a valid partition. Not a scored dimension; a gate.
        # raw_scores are kept intact so the un-gated component breakdown stays visible.
        subtype_labels = sorted({str(v) for v in grouping.values()}) if grouping else []
        _, id_diag = score_cohort_identity(
            mechanism_hypothesis,
            subtype_labels,
            cohort,
            mislead_cohort,
            model=self.llm_model,
        )
        report.diagnostics["cohort_identity"] = id_diag
        report.cohort_identity_verdict = str(id_diag.get("verdict", ""))
        if id_diag.get("fooled"):
            report.gated = True
            for key in _FOOLED_NARRATIVE_KEYS:
                if key in report.weighted_scores:
                    report.weighted_scores[key] = 0.0
            id_diag["gate"] = (
                "narrative dims (mechanism_grounding, pathway_validity) ZEROED — "
                "agent committed to the wrong cohort identity"
            )

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
