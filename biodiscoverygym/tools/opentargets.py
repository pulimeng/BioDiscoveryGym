"""
OpenTargets actionability lookup for candidate drug targets.

Loads pre-downloaded OpenTargets parquets and provides query helpers
the agent can call to assess whether a candidate gene is tractable,
druggable, or has approved/clinical-stage drugs.

Data source: OpenTargets Platform (https://platform.opentargets.org/)
Download: python scripts/download_opentargets.py
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import pandas as pd

_OT_DIR = Path("data/opentargets")
_TRACT_PATH = _OT_DIR / "ot_tractability.parquet"
_DRUGS_PATH = _OT_DIR / "ot_known_drugs.parquet"

_MODALITY_LABELS = {
    "SM": "Small Molecule",
    "AB": "Antibody",
    "PR": "PROTAC",
    "OC": "Other Clinical",
}


@dataclass
class ActionabilityResult:
    gene_symbol: str
    has_approved_drug: bool
    has_clinical_drug: bool
    tractable_sm: bool
    tractable_ab: bool
    top_sm_bucket: Optional[str]
    top_ab_bucket: Optional[str]
    approved_drugs: list[dict] = field(default_factory=list)
    clinical_drugs: list[dict] = field(default_factory=list)
    found: bool = True

    def summary(self) -> str:
        if not self.found:
            return f"{self.gene_symbol}: not found in OpenTargets cache"

        lines = [f"Actionability — {self.gene_symbol}"]
        lines.append(f"  Approved drugs  : {'YES' if self.has_approved_drug else 'no'}")
        lines.append(f"  Clinical drugs  : {'YES' if self.has_clinical_drug else 'no'}")
        lines.append(f"  SM tractability : {self.top_sm_bucket or 'not tractable'}")
        lines.append(f"  AB tractability : {self.top_ab_bucket or 'not tractable'}")

        if self.approved_drugs:
            lines.append("\n  Approved drugs:")
            for d in self.approved_drugs[:10]:
                lines.append(
                    f"    {d['drug_name']:30s}  {d.get('max_phase_str', d.get('max_phase',''))}  {d['disease_name']}"
                )
        if self.clinical_drugs:
            shown = [d for d in self.clinical_drugs if not d.get("is_approved")][:5]
            if shown:
                lines.append("\n  Clinical (phase≥3, not yet approved):")
                for d in shown:
                    lines.append(
                        f"    {d['drug_name']:30s}  {d.get('max_phase_str', d.get('max_phase',''))}  {d['disease_name']}"
                    )
        return "\n".join(lines)


def _load_tables() -> tuple[pd.DataFrame, pd.DataFrame]:
    if not _TRACT_PATH.exists() or not _DRUGS_PATH.exists():
        raise FileNotFoundError(
            f"OpenTargets data not found in {_OT_DIR}. "
            "Run: python scripts/download_opentargets.py"
        )
    tract = pd.read_parquet(_TRACT_PATH)
    drugs = pd.read_parquet(_DRUGS_PATH)
    return tract, drugs


def get_actionability(gene_symbol: str) -> ActionabilityResult:
    """Return actionability summary for a single gene."""
    tract, drugs = _load_tables()

    t = tract[tract["gene_symbol"] == gene_symbol]
    d = drugs[drugs["gene_symbol"] == gene_symbol]

    if t.empty and d.empty:
        return ActionabilityResult(
            gene_symbol=gene_symbol,
            has_approved_drug=False,
            has_clinical_drug=False,
            tractable_sm=False,
            tractable_ab=False,
            top_sm_bucket=None,
            top_ab_bucket=None,
            found=False,
        )

    has_approved = bool(t["has_approved_drug"].any()) if not t.empty else d["is_approved"].any()
    has_clinical = bool(t["has_clinical_drug"].any()) if not t.empty else (d["max_phase"] >= 3).any()

    def top_bucket(modality: str) -> Optional[str]:
        sub = t[(t["modality"] == modality) & t["value"]]
        if sub.empty:
            return None
        return sub.iloc[0]["bucket_label"]

    approved_drugs = (
        d[d["is_approved"]][["drug_name", "max_phase_num", "max_phase_str", "disease_name"]]
        .drop_duplicates("drug_name")
        .sort_values("max_phase_num", ascending=False)
        .rename(columns={"max_phase_num": "max_phase"})
        .to_dict("records")
    )
    clinical_drugs = (
        d[d["max_phase_num"] >= 3][["drug_name", "max_phase_num", "max_phase_str", "is_approved", "disease_name"]]
        .drop_duplicates("drug_name")
        .sort_values("max_phase_num", ascending=False)
        .rename(columns={"max_phase_num": "max_phase"})
        .to_dict("records")
    )

    return ActionabilityResult(
        gene_symbol=gene_symbol,
        has_approved_drug=has_approved,
        has_clinical_drug=has_clinical,
        tractable_sm=top_bucket("SM") is not None,
        tractable_ab=top_bucket("AB") is not None,
        top_sm_bucket=top_bucket("SM"),
        top_ab_bucket=top_bucket("AB"),
        approved_drugs=approved_drugs,
        clinical_drugs=clinical_drugs,
    )


def batch_actionability(gene_symbols: list[str]) -> pd.DataFrame:
    """
    Return a summary DataFrame for multiple genes — useful for ranking candidates.

    Columns: gene_symbol, has_approved_drug, has_clinical_drug,
             tractable_sm, tractable_ab, n_approved_drugs, n_clinical_drugs
    """
    tract, drugs = _load_tables()

    tract_g = (
        tract.groupby("gene_symbol")
        .agg(
            has_approved_drug=("has_approved_drug", "max"),
            has_clinical_drug=("has_clinical_drug", "max"),
            tractable_sm=("modality", lambda s: ((tract.loc[s.index, "modality"] == "SM") & tract.loc[s.index, "value"]).any()),
            tractable_ab=("modality", lambda s: ((tract.loc[s.index, "modality"] == "AB") & tract.loc[s.index, "value"]).any()),
        )
        .reset_index()
    )

    drug_counts = (
        drugs.groupby("gene_symbol")
        .agg(
            n_approved_drugs=("is_approved", "sum"),
            n_clinical_drugs=("max_phase_num", lambda x: (x >= 3).sum()),
        )
        .reset_index()
    )

    query_df = pd.DataFrame({"gene_symbol": gene_symbols})
    result = (
        query_df
        .merge(tract_g, on="gene_symbol", how="left")
        .merge(drug_counts, on="gene_symbol", how="left")
        .fillna({"has_approved_drug": False, "has_clinical_drug": False,
                 "tractable_sm": False, "tractable_ab": False,
                 "n_approved_drugs": 0, "n_clinical_drugs": 0})
    )
    return result
