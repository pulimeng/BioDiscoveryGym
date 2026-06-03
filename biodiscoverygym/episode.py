"""
Episode: orchestrates a single BioDiscoveryGym episode.

Responsibilities:
  1. Load TCGA dataset via DataLoader
  2. Strip leaky columns via DataAnonymizer
  3. Replace TCGA barcodes with SAMPLE_XXXX
  4. Write anonymized data to data/episode/ for agent access
  5. Run the agent (tool-use loop)
  6. Return EpisodeResult — scoring is post-hoc via scripts/score_episode_v2.py
"""

from __future__ import annotations

import shutil
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd

from biodiscoverygym.seeds import set_global_seed
from biodiscoverygym.utils.data_loader import DataLoader
from biodiscoverygym.utils.hidden_context import DataAnonymizer
import biodiscoverygym.sandbox as sandbox

EPISODE_DATA_DIR = Path("data/episode")


@dataclass
class DiscoveryPackage:
    proposed_grouping: dict[str, str]   # {SAMPLE_XXXX: agent-assigned label}
    top_genes: list[str]
    pathway_evidence: list[str]
    mechanism_hypothesis: str
    confidence: str                      # "high" | "medium" | "low"
    next_experiment: str
    data_lock_report: str = ""
    raw: dict = field(default_factory=dict)

    @classmethod
    def from_dict(cls, d: dict) -> "DiscoveryPackage":
        return cls(
            proposed_grouping=d.get("proposed_grouping", {}),
            top_genes=d.get("top_genes", []),
            pathway_evidence=d.get("pathway_evidence", []),
            mechanism_hypothesis=d.get("mechanism_hypothesis", ""),
            confidence=d.get("confidence", "low"),
            next_experiment=d.get("next_experiment", ""),
            data_lock_report=d.get("data_lock_report", d.get("commit_phase_report", "")),
            raw=d,
        )


@dataclass
class EpisodeResult:
    wall_time_s: float = 0.0
    discovery: dict | None = None
    messages: list = field(default_factory=list)
    output_dir: str = ""
    run_log: dict = field(default_factory=dict)  # usage_log + timing_log from runtime


class Episode:
    """
    Runs one full discovery episode.

    Usage:
        episode = Episode.from_cohort("BRCA", seed=42)
        result = episode.run(agent)
    """

    def __init__(
        self,
        dataset: dict,
        episode_id: str,
        cohort: str,
        seed: int,
        episode_data_dir: Path = EPISODE_DATA_DIR,
    ):
        self.dataset = dataset
        self.episode_id = episode_id
        self.cohort = cohort
        self.seed = seed
        self.episode_data_dir = Path(episode_data_dir)
        self._gene_map: dict[str, str] = {}      # populated if anonymize_genes=True
        self._sample_id_map: dict[str, str] = {} # {SAMPLE_XXXX: original_barcode}

    # ------------------------------------------------------------------
    # Factory
    # ------------------------------------------------------------------

    @classmethod
    def from_cohort(
        cls,
        cohort: str,
        seed: int = 42,
        data_dir: str | Path = "data",
        anonymize_genes: bool = False,
        perturb: bool = False,
        tcga_dir: str | Path | None = None,
        rename_clinical: bool = True,
    ) -> "Episode":
        """
        Load a cohort and set up a fully anonymized episode.

        anonymize_genes=True replaces gene symbols with GENE_XXXX identifiers.
        perturb=True loads survival-inverted + mutation-swapped data files
        (must run scripts/perturb_lihc.py first).
        tcga_dir overrides the default data/tcga/<cohort> path (for external cohorts).
        """
        data_dir = Path(data_dir)
        cohort = cohort.upper()
        cohort_lower = cohort.lower()

        # 1. Load dataset
        loader = DataLoader(data_dir)
        resolved_tcga_dir = Path(tcga_dir) if tcga_dir else data_dir / "tcga" / cohort_lower
        dataset = loader.load_tcga(cohort, tcga_dir=resolved_tcga_dir,
                                   perturb=perturb)

        # 2. Strip leaky columns
        anon_dataset = DataAnonymizer.mask(dataset, rename_clinical=rename_clinical)

        # 3. Replace TCGA barcodes with SAMPLE_XXXX
        anon_dataset, sample_id_map = cls._anonymize_sample_ids(anon_dataset, seed)

        # 4. Optionally replace gene symbols with GENE_XXXX
        gene_map: dict[str, str] = {}
        if anonymize_genes:
            anon_dataset, gene_map = cls._anonymize_gene_ids(anon_dataset, seed)

        episode_id = str(uuid.uuid4())[:8]

        inst = cls(
            dataset=anon_dataset,
            episode_id=episode_id,
            cohort=cohort,
            seed=seed,
        )
        inst._gene_map = gene_map
        inst._sample_id_map = sample_id_map
        return inst

    # ------------------------------------------------------------------
    # Run
    # ------------------------------------------------------------------

    def run(self, agent: Any, results_base: str | Path | None = None) -> "EpisodeResult":
        import json

        set_global_seed(self.seed)
        t0 = time.time()

        self._write_episode_data()

        base = Path(results_base) if results_base else Path("results") / "cohort"
        output_dir = base / self.episode_id
        output_dir.mkdir(parents=True, exist_ok=True)

        if self._gene_map:
            (output_dir / "gene_map.json").write_text(json.dumps(self._gene_map, indent=2))

        clinical_codebook = self.dataset.get("clinical_codebook", {})
        if clinical_codebook:
            (output_dir / "clinical_codebook.json").write_text(
                json.dumps(clinical_codebook, indent=2)
            )

        sandbox.enable()
        try:
            discovery_raw, messages, run_log = agent.run(self.episode_id, output_dir=output_dir)
        finally:
            sandbox.disable()

        self._cleanup_episode_data()

        return EpisodeResult(
            wall_time_s=time.time() - t0,
            discovery=discovery_raw,
            messages=messages,
            output_dir=str(output_dir),
            run_log=run_log,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _anonymize_sample_ids(
        dataset: dict, seed: int
    ) -> tuple[dict, dict[str, str]]:
        """
        Replace TCGA barcodes with SAMPLE_XXXX.
        Returns (anonymized_dataset, sample_id_map) where
        sample_id_map is {SAMPLE_XXXX: original_barcode}.
        """
        import numpy as np

        rng = np.random.default_rng(seed)
        expr = dataset.get("expression")
        if expr is None:
            return dataset, {}

        original_ids = expr.index.tolist()
        shuffled = original_ids.copy()
        rng.shuffle(shuffled)
        anon_ids = [f"SAMPLE_{i:04d}" for i in range(len(shuffled))]
        sample_id_map = dict(zip(anon_ids, shuffled))  # SAMPLE_XXXX → original

        rename = {orig: anon for anon, orig in sample_id_map.items()}
        anon_dataset = {}
        for key, val in dataset.items():
            if isinstance(val, pd.DataFrame) and val is not None:
                anon_dataset[key] = val.rename(index=rename)
            else:
                anon_dataset[key] = val

        return anon_dataset, sample_id_map

    @staticmethod
    def _anonymize_gene_ids(
        dataset: dict, seed: int
    ) -> tuple[dict, dict[str, str]]:
        """
        Replace gene symbols with GENE_XXXX identifiers.
        Returns (anonymized_dataset, gene_map) where
        gene_map is {GENE_XXXX: original_symbol}.
        """
        import numpy as np

        rng = np.random.default_rng(seed + 1)  # different seed from sample anonymization
        expr = dataset.get("expression")
        if expr is None:
            return dataset, {}

        # Build rename map from the union of all modality column sets that will be renamed.
        # Using expression columns only leaves mutation-only or CNA-only genes unrenamed (real symbols leak).
        expr_genes = expr.columns.tolist()
        mutation = dataset.get("mutation")
        cna = dataset.get("cna")
        extra_genes: set[str] = set()
        if mutation is not None and isinstance(mutation, pd.DataFrame):
            extra_genes.update(set(mutation.columns) - set(expr_genes))
        if cna is not None and isinstance(cna, pd.DataFrame):
            extra_genes.update(set(cna.columns) - set(expr_genes))
        original_genes = expr_genes + sorted(extra_genes)  # expression order first, then extras sorted

        shuffled = original_genes.copy()
        rng.shuffle(shuffled)
        anon_genes = [f"GENE_{i:05d}" for i in range(len(shuffled))]
        gene_map = dict(zip(anon_genes, shuffled))  # GENE_XXXX → original_symbol

        symbol_to_anon = {v: k for k, v in gene_map.items()}  # real_symbol → GENE_XXXXX

        anon_dataset = {}
        for key, val in dataset.items():
            if not isinstance(val, pd.DataFrame) or val is None:
                anon_dataset[key] = val
            elif key in ("expression", "mutation", "cna"):
                # Columns are gene symbols — rename directly
                anon_dataset[key] = val.rename(columns=symbol_to_anon)
            elif key == "rppa":
                # RPPA uses protein aliases (ERALPHA, BETACATENIN) not gene symbols —
                # leave column names intact to avoid inconsistent partial anonymization
                anon_dataset[key] = val
            elif key == "methylation":
                # CpG IDs (cg######) are not gene symbols — pass through unchanged
                anon_dataset[key] = val
            else:
                anon_dataset[key] = val

        # Verify complete anonymization — any real symbol passing through is a bug
        for _check_key in ("mutation", "cna"):
            if _check_key in anon_dataset and anon_dataset[_check_key] is not None:
                leaked = [c for c in anon_dataset[_check_key].columns if not c.startswith("GENE_")]
                assert not leaked, f"Gene anonymization leak in {_check_key} matrix: {leaked}"

        return anon_dataset, gene_map

    def _write_episode_data(self) -> None:
        """Write anonymized data to data/episode/ for agent access."""
        self.episode_data_dir.mkdir(parents=True, exist_ok=True)
        written = []

        expr = self.dataset.get("expression")
        if expr is not None:
            expr.to_parquet(self.episode_data_dir / "expression.parquet")
            written.append("expression")

        meta = self.dataset.get("metadata")
        if meta is not None:
            meta.to_csv(self.episode_data_dir / "metadata.tsv", sep="\t")
            written.append("metadata")

        mut = self.dataset.get("mutation")
        if mut is not None:
            mut.to_parquet(self.episode_data_dir / "mutations.parquet")
            written.append(f"mutations({mut.shape[0]}×{mut.shape[1]})")

        rppa = self.dataset.get("rppa")
        if rppa is not None:
            rppa.to_parquet(self.episode_data_dir / "rppa.parquet")
            written.append(f"rppa({rppa.shape[0]}×{rppa.shape[1]})")

        meth = self.dataset.get("methylation")
        if meth is not None:
            meth.to_parquet(self.episode_data_dir / "methylation.parquet")
            written.append(f"methylation({meth.shape[0]}×{meth.shape[1]})")

        cna = self.dataset.get("cna")
        if cna is not None:
            cna.to_parquet(self.episode_data_dir / "cna.parquet")
            written.append(f"cna({cna.shape[0]}×{cna.shape[1]})")

        print(f"[Episode {self.episode_id}] Data → {self.episode_data_dir}/ [{', '.join(written)}]")

    def _cleanup_episode_data(self) -> None:
        """Remove data/episode/ after episode completes."""
        if self.episode_data_dir.exists():
            shutil.rmtree(self.episode_data_dir)
