"""
Hidden context construction.

Builds the secret label mapping that agents must discover.
Supports three difficulty levels:
  - "easy"   : strong signal (2 tissue types, well-separated in expression)
  - "medium" : mutation status (BRCA1/2) — moderate signal
  - "hard"   : quantitative drug-response tertile — weak, noisy signal
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


@dataclass
class HiddenContext:
    """
    hidden_labels: {sample_id: label_string}
    context_variable: human-readable description of what was hidden
    difficulty: "easy" | "medium" | "hard"
    label_set: the possible label values
    metadata: any extra info (e.g. which drug, which mutation gene)
    """

    hidden_labels: dict[str, str]
    context_variable: str
    difficulty: str
    label_set: list[str]
    metadata: dict[str, Any] = field(default_factory=dict)

    def save(self, path: str | Path) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "context_variable": self.context_variable,
            "difficulty": self.difficulty,
            "label_set": self.label_set,
            "metadata": self.metadata,
            "hidden_labels": self.hidden_labels,
        }
        Path(path).write_text(json.dumps(payload, indent=2))

    @classmethod
    def load(cls, path: str | Path) -> "HiddenContext":
        payload = json.loads(Path(path).read_text())
        return cls(
            hidden_labels=payload["hidden_labels"],
            context_variable=payload["context_variable"],
            difficulty=payload["difficulty"],
            label_set=payload["label_set"],
            metadata=payload.get("metadata", {}),
        )


class HiddenContextBuilder:
    """
    Constructs a HiddenContext from a DepMap dataset dict.

    Usage:
        builder = HiddenContextBuilder(dataset, metadata_df)
        ctx = builder.build_tissue_context(tissue_col="OncotreePrimaryDisease", n_groups=2)
    """

    def __init__(self, dataset: dict, seed: int = 42):
        self.dataset = dataset
        self.seed = seed
        self.rng = np.random.default_rng(seed)

    # ------------------------------------------------------------------
    # Easy: tissue-type binary split
    # ------------------------------------------------------------------

    def build_tissue_context(
        self,
        tissue_col: str = "OncotreePrimaryDisease",
        n_groups: int = 2,
        min_samples_per_group: int = 30,
    ) -> HiddenContext:
        metadata: pd.DataFrame = self.dataset.get("metadata")
        if metadata is None or tissue_col not in metadata.columns:
            raise ValueError(f"Column {tissue_col!r} not found in metadata.")

        counts = metadata[tissue_col].value_counts()
        eligible = counts[counts >= min_samples_per_group].index.tolist()
        if len(eligible) < n_groups:
            raise ValueError(f"Not enough tissue types with ≥{min_samples_per_group} samples.")

        chosen = self.rng.choice(eligible, size=n_groups, replace=False).tolist()
        subset = metadata[metadata[tissue_col].isin(chosen)]

        hidden_labels = {
            sid: f"Context_{chr(65 + chosen.index(row[tissue_col]))}"
            for sid, row in subset.iterrows()
        }

        return HiddenContext(
            hidden_labels=hidden_labels,
            context_variable=f"Tissue type ({tissue_col}): {chosen}",
            difficulty="easy",
            label_set=[f"Context_{chr(65 + i)}" for i in range(n_groups)],
            metadata={"tissue_col": tissue_col, "chosen_tissues": chosen},
        )

    # ------------------------------------------------------------------
    # Medium: mutation status (binary)
    # ------------------------------------------------------------------

    def build_mutation_context(
        self, gene: str = "BRCA1", min_mutated: int = 20
    ) -> HiddenContext:
        mutation: pd.DataFrame = self.dataset.get("mutation")
        if mutation is None:
            raise ValueError("Mutation matrix not loaded in dataset.")
        if gene not in mutation.columns:
            raise ValueError(f"Gene {gene!r} not in mutation matrix.")

        mut_col = mutation[gene]
        n_mut = int(mut_col.sum())
        if n_mut < min_mutated:
            raise ValueError(f"Only {n_mut} mutated samples for {gene}; need ≥{min_mutated}.")

        hidden_labels = {
            sid: ("Context_Mutant" if mut_col[sid] > 0 else "Context_WT")
            for sid in mut_col.index
        }

        return HiddenContext(
            hidden_labels=hidden_labels,
            context_variable=f"{gene} mutation status",
            difficulty="medium",
            label_set=["Context_Mutant", "Context_WT"],
            metadata={"gene": gene, "n_mutated": n_mut},
        )

    # ------------------------------------------------------------------
    # Hard: drug-response tertile
    # ------------------------------------------------------------------

    def build_drug_response_context(self, drug_col: str | None = None) -> HiddenContext:
        dr: pd.DataFrame = self.dataset.get("drug_response")
        if dr is None:
            raise ValueError("Drug response matrix not loaded in dataset.")

        if drug_col is None:
            # Pick the drug with the most complete data
            drug_col = dr.notna().sum().idxmax()

        series = dr[drug_col].dropna()
        tertiles = pd.qcut(series, q=3, labels=["Context_Sensitive", "Context_Intermediate", "Context_Resistant"])

        hidden_labels = {sid: str(label) for sid, label in tertiles.items()}

        return HiddenContext(
            hidden_labels=hidden_labels,
            context_variable=f"Drug response tertile ({drug_col})",
            difficulty="hard",
            label_set=["Context_Sensitive", "Context_Intermediate", "Context_Resistant"],
            metadata={"drug": drug_col},
        )

    # ------------------------------------------------------------------
    # Sealed TCGA slice (20% held out)
    # ------------------------------------------------------------------

    def build_sealed_tcga_slice(
        self,
        tcga_labels: dict[str, str],
        sealed_fraction: float = 0.20,
        seal_path: str | Path = "data/sealed/sealed_labels.json",
        split_col: str = "primary_diagnosis",
    ) -> tuple[dict[str, str], dict[str, str]]:
        """
        Split TCGA labels into public (80%) and sealed (20%) portions.
        Label values are anonymized to Context_A/B/... before writing so
        the clinical variable cannot be inferred from the files.
        A label_mapping.json is written alongside the sealed file for
        evaluator reference only.

        Returns:
            (public_labels, {}) — sealed labels are written only to disk.
        """
        # Anonymize: raw diagnosis string → Context_A, Context_B, ...
        unique_labels = sorted(set(tcga_labels.values()))
        label_map = {raw: f"Context_{chr(65 + i)}" for i, raw in enumerate(unique_labels)}
        anon_labels = {k: label_map[v] for k, v in tcga_labels.items()}

        sample_ids = list(anon_labels.keys())
        n_sealed = max(1, int(len(sample_ids) * sealed_fraction))
        idx = self.rng.choice(len(sample_ids), size=n_sealed, replace=False)
        sealed_ids = {sample_ids[i] for i in idx}

        public_labels = {k: v for k, v in anon_labels.items() if k not in sealed_ids}
        sealed_labels = {k: v for k, v in anon_labels.items() if k in sealed_ids}

        seal_path = Path(seal_path)
        seal_path.parent.mkdir(parents=True, exist_ok=True)
        seal_path.write_text(json.dumps(sealed_labels, indent=2))
        label_map["_split_col"] = split_col
        (seal_path.parent / "label_mapping.json").write_text(json.dumps(label_map, indent=2))
        print(f"Sealed {len(sealed_labels)} samples → {seal_path}")
        print(f"Label mapping → {seal_path.parent / 'label_mapping.json'}")

        return public_labels, {}


# ---------------------------------------------------------------------------
# DataAnonymizer
# ---------------------------------------------------------------------------

# Clinical columns that leak cohort identity through their name or categorical values,
# but carry real biological signal — renamed rather than stripped, with a codebook
# mapping CLIN_XX → real column name and CAT_X → real category value.
# True = also remap categorical string values; False = numeric, column rename only.
#
# Rule: keep columns that represent clinical/histological measurements (pathology subtype,
# numeric scores derived from assays). Strip molecular clustering labels entirely —
# precomputed cluster assignments are the paper's answer, not independent data.
_CLINICAL_RENAME = {
    "hrd_score": False,  # continuous genomic instability score — numeric, rename only
    "icluster":  False,  # integrative iCluster (mRNA+methy+CNA), integers 1-4 — numeric, rename only
    "pathology": True,   # histological subtype — "Osteoblastic"/"Chondroblastic" → CAT_X
}

# Columns that directly reveal cancer type, tissue of origin, or molecular subtype.
# Survival and staging columns are intentionally NOT stripped — they are valid
# phenotypic anchors the agent should use for mechanistic investigation.
_ALWAYS_STRIP = [
    # tissue / lineage (DepMap) — directly reveal cancer type
    "OncotreePrimaryDisease", "OncotreeLineage", "OncotreeSubtype",
    "OncotreeCode", "PrimaryOrMetastasis", "SampleCollectionSite",
    "lineage", "lineage_subtype", "cancer_type", "tissue_type",
    # mutation labels (DepMap)
    "BRCA1_mut", "BRCA2_mut", "TP53_mut", "KRAS_mut",
    # subtypes (DepMap / TCGA paper annotations)
    "paper_BRCA_Subtype_PAM50", "molecular_subtype", "subtype",
    # drug sensitivity proxies
    "auc", "ic50", "lfc",
    # TCGA GDC fields that directly reveal histology or tissue of origin
    "primary_diagnosis", "morphology",
    "site_of_resection_or_biopsy", "tissue_or_organ_of_origin",
    # Demographics that can leak cohort identity (e.g. LIHC has high Asian
    # proportion from HBV-endemic regions — a fingerprint that survives mislead)
    "gender", "race", "ethnicity",
]


class DataAnonymizer:
    """
    Strips or renames leaky columns from a dataset before it is handed to an agent.

    Usage:
        anon_dataset = DataAnonymizer.mask(dataset)
        clinical_codebook = anon_dataset.get("clinical_codebook", {})
    """

    @staticmethod
    def anonymize_clinical(metadata) -> tuple:
        """
        Rename leaky clinical columns to CLIN_00, CLIN_01, … and remap
        categorical string values to CAT_0, CAT_1, … where flagged.

        Returns (anonymized_df, codebook) where codebook maps:
            CLIN_XX → {"real_name": str, "value_map": {CAT_X: real_val} | None}

        Deterministic: columns sorted alphabetically, values sorted for categories.
        """
        import pandas as pd

        meta = metadata.copy()
        codebook: dict = {}

        present = sorted(c for c in _CLINICAL_RENAME if c in meta.columns)
        for idx, col in enumerate(present):
            anon_col = f"CLIN_{idx:02d}"
            remap_values = _CLINICAL_RENAME[col]

            value_map = None
            if remap_values and meta[col].dtype == object:
                categories = sorted(meta[col].dropna().unique().tolist())
                value_map = {f"CAT_{i}": cat for i, cat in enumerate(categories)}
                inv_map = {v: k for k, v in value_map.items()}
                meta[col] = meta[col].map(inv_map)

            codebook[anon_col] = {"real_name": col, "value_map": value_map}
            meta = meta.rename(columns={col: anon_col})

        return meta, codebook

    @staticmethod
    def mask(dataset: dict) -> dict:
        """
        Return a shallow-copied, agent-safe version of dataset with:
        - Columns in _ALWAYS_STRIP removed from metadata
        - Columns in _CLINICAL_RENAME renamed to CLIN_XX (values remapped where needed)
        - 'clinical_codebook' key added with the CLIN_XX → real mapping
        """
        import copy

        safe = copy.copy(dataset)

        meta = safe.get("metadata")
        if meta is not None:
            cols_to_drop = [c for c in _ALWAYS_STRIP if c in meta.columns]
            meta = meta.drop(columns=cols_to_drop, errors="ignore")
            meta, clinical_codebook = DataAnonymizer.anonymize_clinical(meta)
            safe["metadata"] = meta
            safe["clinical_codebook"] = clinical_codebook

        return safe
