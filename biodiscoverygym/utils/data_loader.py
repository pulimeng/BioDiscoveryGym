"""
DataLoader: reads processed DepMap / PRISM files into a dataset dict
compatible with BioDiscoveryGymEnv.

Returns:
    {
        "expression": pd.DataFrame  (samples × genes, log-TPM),
        "metadata":   pd.DataFrame  (samples × clinical/annotation cols),
        "mutation":   pd.DataFrame | None,
        "cnv":        pd.DataFrame | None,
        "crispr":     pd.DataFrame | None,
        "drug_response": pd.DataFrame | None,
    }

Supports two source formats:
  - Standard DepMap release CSVs (index = ModelID / ACH-...)
  - HPC-local DepMap CSVs (ModelID as a column, extra metadata columns before genes)
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

# Columns present in HPC-format omics files that are not gene measurements.
_HPC_META_COLS = {
    "SequencingID", "ModelConditionID", "ModelID",
    "IsDefaultEntryForMC", "IsDefaultEntryForModel",
}

# HPC base directory (mounted network volume).
HPC_DEPMAP_DIR = Path("/Volumes/HPC/S2K/peddep")
HPC_DRUG_DIR   = HPC_DEPMAP_DIR / "drug_screening"


class DataLoader:
    def __init__(self, data_dir: str | Path = "data"):
        self.data_dir = Path(data_dir)

    # ------------------------------------------------------------------
    # Public entry points
    # ------------------------------------------------------------------

    def load_depmap(
        self,
        release_dir: str | Path | None = None,
        load_mutation: bool = True,
        load_cnv: bool = True,
        load_crispr: bool = False,
    ) -> dict[str, Any]:
        """
        Load DepMap omics data.  Tries the standard release directory first;
        falls back to the HPC volume if files are missing.
        """
        d = Path(release_dir) if release_dir else self.data_dir / "depmap"

        expression = self._load_omics(
            d / "OmicsExpressionProteinCodingGenesTPMLogp1.csv",
            hpc_path=HPC_DEPMAP_DIR / "OmicsExpressionTPMLogp1HumanProteinCodingGenes.csv",
        )
        metadata = self._load_metadata(
            d / "Model.csv",
            hpc_path=HPC_DRUG_DIR / "Model.csv",
        )

        dataset: dict[str, Any] = {
            "expression": expression,
            "metadata": metadata,
            "mutation": self._load_omics(
                d / "OmicsSomaticMutationsMatrixDamaging.csv",
                hpc_path=None,  # HPC has long-format only; skip binary matrix
            ) if load_mutation else None,
            "cnv": self._load_omics(
                d / "OmicsCNGene.csv",
                hpc_path=HPC_DEPMAP_DIR / "OmicsCNGeneWGS.csv",
            ) if load_cnv else None,
            "crispr": self._load_omics(
                d / "CRISPRGeneEffect.csv",
                hpc_path=None,
            ) if load_crispr else None,
            "drug_response": None,
        }

        # Align all matrices to common sample index
        if expression is not None:
            samples = expression.index
            for key in ("mutation", "cnv", "crispr"):
                if dataset[key] is not None:
                    dataset[key] = dataset[key].reindex(samples)
            if metadata is not None:
                dataset["metadata"] = metadata.reindex(samples)

        return dataset

    def load_prism(self, prism_dir: str | Path | None = None) -> pd.DataFrame | None:
        d = Path(prism_dir) if prism_dir else self.data_dir / "prism"

        # Standard release format: samples × drugs
        standard = d / "secondary-screen-replicate-collapsed-logfold-change.csv"
        if standard.exists():
            return pd.read_csv(standard, index_col=0)

        # HPC format: drugs × samples (transposed); use 24Q2 primary screen
        hpc = HPC_DRUG_DIR / "Repurposing_Public_24Q2_Extended_Primary_Data_Matrix.csv"
        if hpc.exists():
            df = pd.read_csv(hpc, index_col=0)
            # Rows = drugs (BRD IDs), columns = ACH- IDs → transpose to samples × drugs
            return df.T
        return None

    def attach_drug_response(self, dataset: dict, prism_dir: str | Path | None = None) -> dict:
        lfc = self.load_prism(prism_dir)
        if lfc is not None and dataset.get("expression") is not None:
            shared = dataset["expression"].index.intersection(lfc.index)
            dataset["drug_response"] = lfc.reindex(shared)
        return dataset

    def load_tcga(
        self,
        cohort: str,
        tcga_dir: str | Path | None = None,
        gene_type: str = "protein_coding",
        expression_col: str = "tpm_unstranded",
        log1p: bool = True,
        use_cache: bool = True,
        perturb: bool = False,
    ) -> dict[str, Any]:
        """
        Load a TCGA cohort into a dataset dict compatible with BioDiscoveryGymEnv.

        Extracts per-sample expression TSVs from GDC batch tarballs, builds a
        samples × genes DataFrame (log1p TPM by default), and caches to parquet.
        Clinical metadata is loaded from the downloaded TSV.

        Args:
            cohort:         Cohort name, e.g. "BRCA" (case-insensitive).
            tcga_dir:       Root TCGA data directory (default: data/tcga).
            gene_type:      Filter to this gene_type (default: "protein_coding").
            expression_col: Which count column to use (default: "tpm_unstranded").
            log1p:          Apply log1p transform (default: True, matches DepMap).
            use_cache:      Load from / save to expression.parquet if available.

        Returns:
            Dataset dict with keys: expression, metadata, mutation, cnv, crispr,
            drug_response (last four are None — TCGA has no DepMap-style matrices).
        """
        import json
        import tarfile
        import numpy as np

        cohort = cohort.upper()
        d = Path(tcga_dir) if tcga_dir else self.data_dir / "tcga" / cohort.lower()
        cache_path = d / "expression.parquet"

        # ------------------------------------------------------------------
        # Expression matrix
        # ------------------------------------------------------------------
        if use_cache and cache_path.exists():
            expression = pd.read_parquet(cache_path)
            print(f"[TCGA {cohort}] Loaded expression from cache: {expression.shape}")
        else:
            manifest_path = d / "file_manifest.json"
            if not manifest_path.exists():
                raise FileNotFoundError(f"Manifest not found: {manifest_path}")

            # file_id → TCGA submitter ID (e.g. TCGA-BH-A18H)
            manifest = json.loads(manifest_path.read_text())
            file_id_to_sample = {
                entry["id"]: entry["cases"][0]["submitter_id"]
                for entry in manifest
                if entry.get("cases")
            }

            raw_dir = d / "expression_raw"
            tarballs = sorted(raw_dir.glob("batch_*.tar.gz"))
            if not tarballs:
                raise FileNotFoundError(f"No batch tarballs found in {raw_dir}")

            rows: dict[str, pd.Series] = {}
            gene_index: list[str] | None = None

            for tb_path in tarballs:
                print(f"  Extracting {tb_path.name} ...", end=" ", flush=True)
                try:
                    tf_handle = tarfile.open(tb_path, "r:gz")
                    is_tar = True
                except Exception:
                    is_tar = False

                if is_tar:
                    with tf_handle as tf:
                        for member in tf.getmembers():
                            if not member.name.endswith(".tsv"):
                                continue
                            file_id = member.name.split("/")[0]
                            sample_id = file_id_to_sample.get(file_id)
                            if sample_id is None:
                                continue
                            fobj = tf.extractfile(member)
                            if fobj is None:
                                continue
                            df = pd.read_csv(fobj, sep="\t", comment="#")
                            df = df[df["gene_type"] == gene_type].copy()
                            df = df[["gene_name", expression_col]].dropna()
                            df = df.groupby("gene_name")[expression_col].sum()
                            if gene_index is None:
                                gene_index = df.index.tolist()
                            rows[sample_id] = df.reindex(gene_index)
                else:
                    # GDC returns a bare TSV (no tar wrapper) for single-file batches.
                    # Infer the sample ID from the manifest using the batch index.
                    batch_idx = int(tb_path.stem.replace("batch_", "").replace(".tar", "")) * 100
                    batch_file_ids = list(file_id_to_sample.keys())[batch_idx: batch_idx + 100]
                    try:
                        # Open explicitly as text — pandas would try to decompress
                        # based on the .gz extension and fail on a bare TSV.
                        with open(tb_path, "r") as fh:
                            df = pd.read_csv(fh, sep="\t", comment="#")
                        df = df[df["gene_type"] == gene_type].copy()
                        df = df[["gene_name", expression_col]].dropna()
                        df = df.groupby("gene_name")[expression_col].sum()
                        if gene_index is None:
                            gene_index = df.index.tolist()
                        for fid in batch_file_ids:
                            sid = file_id_to_sample.get(fid)
                            if sid:
                                rows[sid] = df.reindex(gene_index)
                    except Exception as e:
                        print(f"SKIP (unreadable: {e})")
                        continue

                print(f"{len(rows)} samples so far")

            expression = pd.DataFrame(rows).T  # samples × genes
            expression.index.name = "sample_id"

            if log1p:
                expression = np.log1p(expression)

            expression.to_parquet(cache_path)
            print(f"[TCGA {cohort}] Built expression matrix {expression.shape} → cached")

        # ------------------------------------------------------------------
        # Clinical metadata (strip nothing here — DataAnonymizer handles that)
        # ------------------------------------------------------------------
        clinical_fname = f"{cohort}_clinical_perturbed.tsv" if perturb else f"{cohort}_clinical.tsv"
        clinical_path = d / clinical_fname
        metadata = None
        if clinical_path.exists():
            metadata = pd.read_csv(clinical_path, sep="\t", index_col=0)
            metadata = metadata.reindex(expression.index)

        # Optional modalities — load from parquet if preprocessed files exist
        mutation_fname = "mutations_perturbed.parquet" if perturb else "mutations.parquet"
        mutation_path = d / mutation_fname
        rppa_path     = d / "rppa.parquet"

        if perturb and not (d / "LIHC_clinical_perturbed.tsv").exists():
            raise FileNotFoundError(
                "Perturbed data not found. Run: python scripts/perturb_lihc.py"
            )

        mutation = pd.read_parquet(mutation_path).reindex(expression.index) if mutation_path.exists() else None
        rppa     = pd.read_parquet(rppa_path).reindex(expression.index)     if rppa_path.exists()     else None

        if mutation is not None:
            print(f"[TCGA {cohort}] Loaded mutations: {mutation.shape}")
        if rppa is not None:
            print(f"[TCGA {cohort}] Loaded RPPA: {rppa.shape}")

        return {
            "expression": expression,
            "metadata":   metadata,
            "mutation":   mutation,
            "rppa":       rppa,
            "cnv":        None,
            "crispr":     None,
            "drug_response": None,
        }

    def load_synthetic(
        self,
        n_samples: int = 200,
        n_genes: int = 500,
        n_context_groups: int = 2,
        seed: int = 42,
    ) -> tuple[dict[str, Any], dict[str, str]]:
        """Generate a small synthetic dataset for unit tests and M0 validation."""
        import numpy as np
        from biodiscoverygym.seeds import set_global_seed

        set_global_seed(seed)

        group_labels = [f"Context_{chr(65 + i)}" for i in range(n_context_groups)]
        sample_ids = [f"ACH-{i:06d}" for i in range(n_samples)]
        gene_ids = [f"GENE{i:04d}" for i in range(n_genes)]

        hidden_labels = {
            sid: group_labels[i % n_context_groups]
            for i, sid in enumerate(sample_ids)
        }

        group_numeric = [i % n_context_groups for i in range(n_samples)]
        expr = np.random.randn(n_samples, n_genes)
        for j in range(20):
            expr[:, j] += [2.0 * g for g in group_numeric]

        expression = pd.DataFrame(expr, index=sample_ids, columns=gene_ids)
        metadata = pd.DataFrame(
            {"n_samples": n_samples, "tissue_type": "synthetic"},
            index=sample_ids,
        )

        dataset = {
            "expression": expression,
            "metadata": metadata,
            "mutation": None,
            "cnv": None,
            "crispr": None,
            "drug_response": None,
        }
        return dataset, hidden_labels

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _load_omics(self, path: Path, hpc_path: Path | None) -> pd.DataFrame | None:
        """
        Load an omics matrix, falling back to hpc_path if path is missing.
        Handles both standard format (index = ACH-) and HPC format
        (ModelID as column, extra metadata columns before genes).
        """
        target = path if path.exists() and path.stat().st_size > 0 else None
        if target is None and hpc_path is not None and hpc_path.exists():
            target = hpc_path
        if target is None:
            return None

        df = self._load_csv(target, index_col=0)
        if df is None:
            return None

        # Detect HPC format: ModelID is a column (not already the index)
        if "ModelID" in df.columns:
            df = df[df.get("IsDefaultEntryForModel", pd.Series("Yes", index=df.index)) == "Yes"]
            df = df.set_index("ModelID")
            df = df.drop(columns=[c for c in _HPC_META_COLS if c in df.columns], errors="ignore")

        return df

    def _load_metadata(self, path: Path, hpc_path: Path | None) -> pd.DataFrame | None:
        target = path if path.exists() and path.stat().st_size > 0 else None
        if target is None and hpc_path is not None and hpc_path.exists():
            target = hpc_path
        if target is None:
            return None
        # Model.csv is always indexed by ModelID
        return self._load_csv(target, index_col=0)

    @staticmethod
    def _load_csv(path: Path, **kwargs) -> pd.DataFrame | None:
        if not path.exists():
            return None
        if path.suffix.lower() == ".parquet":
            return pd.read_parquet(path)
        return pd.read_csv(path, **kwargs)
