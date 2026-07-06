"""
Download OpenTargets Platform actionability data for cancer genes.

Uses the public OpenTargets GraphQL API (no auth required):
  https://api.platform.opentargets.org/api/v4/graphql

Two output files in data/opentargets/:

  ot_tractability.parquet
    gene_symbol, ensembl_id, modality (SM/AB/PR/OC), bucket_label,
    value (bool), has_approved_drug, has_clinical_drug

  ot_known_drugs.parquet
    gene_symbol, ensembl_id, drug_id, drug_name, drug_type,
    max_phase_str (e.g. PHASE_3 / APPROVAL), max_phase_num (1-4),
    is_approved, disease_id, disease_name

Gene universe: OncoKB cancer gene list (if already downloaded) plus a
hardcoded fallback of ~100 key cancer genes.  Extend with --gene-list.

Usage:
    python scripts/download_opentargets.py
    python scripts/download_opentargets.py --gene-list data/cancer_genes/oncokb_cancer_gene_list.tsv
    python scripts/download_opentargets.py --out-dir data/opentargets --force
"""
from __future__ import annotations

import argparse
import time
from pathlib import Path
from typing import Any

import pandas as pd
import requests

OT_API = "https://api.platform.opentargets.org/api/v4/graphql"
MYGENE_API = "https://mygene.info/v3/query"

# Stage string → numeric equivalent (4 = approved)
_STAGE_NUM = {
    "PHASE_1": 1,
    "PHASE_1_2": 1,
    "PHASE_2": 2,
    "PHASE_2_3": 2,
    "PHASE_3": 3,
    "APPROVAL": 4,
}

FALLBACK_GENES = [
    "EGFR", "ERBB2", "ERBB3", "KRAS", "NRAS", "HRAS", "BRAF", "RAF1",
    "MAP2K1", "MAP2K2", "MAPK1", "MAPK3", "PIK3CA", "PIK3CB", "PTEN",
    "AKT1", "AKT2", "MTOR", "TSC1", "TSC2", "NF1", "NF2", "RB1",
    "TP53", "MDM2", "MDM4", "CDKN2A", "CDK4", "CDK6", "CCND1", "CCND2",
    "MYC", "MYCN", "MYCL", "BCL2", "BCL6", "MCL1",
    "ABL1", "ABL2", "BCR", "JAK1", "JAK2", "JAK3", "STAT3", "STAT5A",
    "FLT3", "KIT", "PDGFRA", "PDGFRB", "CSF1R", "MET", "ALK", "ROS1",
    "RET", "FGFR1", "FGFR2", "FGFR3", "FGFR4",
    "VEGFA", "VEGFR1", "VEGFR2", "VEGFR3",
    "CDH1", "VIM", "ZEB1", "SNAI1", "TWIST1",
    "BRCA1", "BRCA2", "ATM", "ATR", "CHEK1", "CHEK2", "PALB2",
    "MLH1", "MSH2", "MSH6", "PMS2",
    "DNMT3A", "TET2", "IDH1", "IDH2", "EZH2", "ASXL1",
    "CTNNB1", "APC", "AXIN1",
    "NOTCH1", "NOTCH2", "NOTCH3",
    "SMO", "PTCH1", "GLI1", "GLI2",
    "RUNX1", "FLI1", "ETV6",
    "AR", "ESR1", "PGR", "HIF1A",
    "MYD88", "CARD11", "NFKB1", "RELA",
    "PARP1", "PARP2", "TOP1", "TOP2A",
    "CD274", "PDCD1", "CTLA4", "LAG3", "HAVCR2",
    "TGFB1", "TGFBR1", "TGFBR2", "SMAD4",
    "ARID1A", "SMARCA4", "SMARCB1",
    "KMT2A", "KMT2D", "KDM5C", "KDM6A", "SETD2",
    "FBXW7", "KEAP1",
    "STK11", "MTOR",
    "RUNX2", "SP7",
    "VHL", "SDHA", "SDHB",
]


# ------------------------------------------------------------------
# Gene list loading
# ------------------------------------------------------------------

def load_gene_list(gene_list_path: Path | None) -> list[str]:
    default_path = Path("data/cancer_genes/oncokb_cancer_gene_list.tsv")

    for path in [gene_list_path, default_path]:
        if path is not None and path.exists():
            df = pd.read_csv(path, sep="\t")
            col = next(
                (c for c in df.columns if c.lower() in ("hugo symbol", "gene symbol", "symbol", "gene")),
                df.columns[0],
            )
            genes = df[col].dropna().str.strip().tolist()
            print(f"  Loaded {len(genes)} genes from {path.name}")
            return genes

    print(f"  OncoKB gene list not found — using built-in fallback ({len(FALLBACK_GENES)} genes)")
    return FALLBACK_GENES


# ------------------------------------------------------------------
# Step 1: gene symbol → Ensembl ID via mygene.info JSON batch API
# ------------------------------------------------------------------

def symbols_to_ensembl(symbols: list[str]) -> dict[str, str]:
    """Return {symbol: ensembl_id}. Uses JSON body (list) for correct batch handling."""
    print(f"  Mapping {len(symbols)} symbols → Ensembl IDs via mygene.info...")
    symbol_to_ensembl: dict[str, str] = {}

    for i in range(0, len(symbols), 1000):
        chunk = symbols[i : i + 1000]
        resp = requests.post(
            MYGENE_API,
            json={
                "q": chunk,
                "scopes": "symbol",
                "fields": "ensembl.gene",
                "species": "human",
            },
            timeout=60,
        )
        resp.raise_for_status()
        for hit in resp.json():
            if not isinstance(hit, dict):
                continue
            sym = hit.get("query", "")
            ensembl = hit.get("ensembl", {})
            if isinstance(ensembl, list):
                ensembl = ensembl[0]
            if not isinstance(ensembl, dict):
                continue
            eid = ensembl.get("gene", "")
            if isinstance(eid, list):
                eid = eid[0]
            if eid and sym:
                symbol_to_ensembl[sym] = eid

    n_mapped = len(symbol_to_ensembl)
    n_miss = len(symbols) - n_mapped
    print(f"  Mapped {n_mapped}/{len(symbols)} symbols ({n_miss} unmapped, skipped)")
    return symbol_to_ensembl


# ------------------------------------------------------------------
# Step 2: OpenTargets GraphQL queries (batched via aliases)
# ------------------------------------------------------------------

_TRACTABILITY_FIELDS = """
    id
    approvedSymbol
    tractability {
      label
      modality
      value
    }
"""

# v4 API: knownDrugs → drugAndClinicalCandidates
# Drug.isApproved → derive from maxClinicalStage == "APPROVAL"
# Drug.maximumClinicalTrialPhase → Drug.maximumClinicalStage
# disease { id name } → diseases { diseaseFromSource disease { id name } }
_DRUGS_FIELDS = """
    id
    approvedSymbol
    drugAndClinicalCandidates {
      rows {
        maxClinicalStage
        drug {
          id
          name
          maximumClinicalStage
          drugType
        }
        diseases {
          diseaseFromSource
          disease {
            id
            name
          }
        }
      }
    }
"""


def _graphql_batch(ensembl_ids: list[str], fields: str) -> dict[str, Any]:
    """One batched query using aliases. Returns {ensembl_id: target_data}."""
    aliases = "\n".join(
        f'  t{i}: target(ensemblId: "{eid}") {{\n{fields}\n  }}'
        for i, eid in enumerate(ensembl_ids)
    )
    query = "{\n" + aliases + "\n}"

    resp = requests.post(
        OT_API,
        json={"query": query},
        headers={"Content-Type": "application/json"},
        timeout=120,
    )
    resp.raise_for_status()
    payload = resp.json()
    if "errors" in payload:
        raise RuntimeError(f"GraphQL errors: {payload['errors'][:1]}")

    data = payload.get("data", {})
    return {eid: data[f"t{i}"] for i, eid in enumerate(ensembl_ids) if data.get(f"t{i}")}


def query_opentargets(
    symbol_to_ensembl: dict[str, str],
    batch_size: int = 20,
    sleep_between: float = 0.3,
) -> tuple[list[dict], list[dict]]:
    ensembl_list = list(symbol_to_ensembl.values())
    eid_to_sym = {v: k for k, v in symbol_to_ensembl.items()}

    tractability_rows: list[dict] = []
    drug_rows: list[dict] = []

    n_batches = (len(ensembl_list) + batch_size - 1) // batch_size
    print(f"  Querying OpenTargets in {n_batches} batches of {batch_size}...")

    for i in range(0, len(ensembl_list), batch_size):
        batch = ensembl_list[i : i + batch_size]
        batch_num = i // batch_size + 1
        print(f"\r  batch {batch_num}/{n_batches}", end="", flush=True)

        try:
            tract_data = _graphql_batch(batch, _TRACTABILITY_FIELDS)
            drug_data = _graphql_batch(batch, _DRUGS_FIELDS)
        except Exception as e:
            print(f"\n  [warn] batch {batch_num} failed: {e} — skipping")
            time.sleep(2)
            continue

        for eid, tgt in tract_data.items():
            sym = eid_to_sym.get(eid, eid)
            tracts = tgt.get("tractability") or []
            approved = any(t["value"] and t["label"] == "Approved Drug" for t in tracts)
            clinical = any(
                t["value"] and t["label"] in ("Approved Drug", "Advanced Clinical", "Phase 1 Clinical")
                for t in tracts
            )
            for t in tracts:
                tractability_rows.append({
                    "gene_symbol": sym,
                    "ensembl_id": eid,
                    "modality": t["modality"],
                    "bucket_label": t["label"],
                    "value": t["value"],
                    "has_approved_drug": approved,
                    "has_clinical_drug": clinical,
                })

        for eid, tgt in drug_data.items():
            sym = eid_to_sym.get(eid, eid)
            dcc = tgt.get("drugAndClinicalCandidates") or {}
            for row in dcc.get("rows") or []:
                drug = row.get("drug") or {}
                max_stage_str = row.get("maxClinicalStage", "")
                max_phase_num = _STAGE_NUM.get(max_stage_str, 0)
                is_approved = max_stage_str == "APPROVAL"

                diseases = row.get("diseases") or []
                if not diseases:
                    drug_rows.append({
                        "gene_symbol": sym,
                        "ensembl_id": eid,
                        "drug_id": drug.get("id", ""),
                        "drug_name": drug.get("name", ""),
                        "drug_type": drug.get("drugType", ""),
                        "max_phase_str": max_stage_str,
                        "max_phase_num": max_phase_num,
                        "is_approved": is_approved,
                        "disease_id": "",
                        "disease_name": "",
                    })
                else:
                    seen_disease = set()
                    for d_entry in diseases:
                        dis = d_entry.get("disease") or {}
                        dis_id = dis.get("id", "")
                        dis_name = dis.get("name", "") or d_entry.get("diseaseFromSource", "")
                        key = (drug.get("id", ""), dis_id or dis_name)
                        if key in seen_disease:
                            continue
                        seen_disease.add(key)
                        drug_rows.append({
                            "gene_symbol": sym,
                            "ensembl_id": eid,
                            "drug_id": drug.get("id", ""),
                            "drug_name": drug.get("name", ""),
                            "drug_type": drug.get("drugType", ""),
                            "max_phase_str": max_stage_str,
                            "max_phase_num": max_phase_num,
                            "is_approved": is_approved,
                            "disease_id": dis_id,
                            "disease_name": dis_name,
                        })

        time.sleep(sleep_between)

    print()
    return tractability_rows, drug_rows


# ------------------------------------------------------------------
# Main
# ------------------------------------------------------------------

def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--out-dir", default="data/opentargets")
    p.add_argument(
        "--gene-list",
        metavar="TSV",
        help="TSV with a column named 'Hugo Symbol' or similar. Defaults to OncoKB file.",
    )
    p.add_argument("--force", action="store_true", help="Re-download even if output exists")
    p.add_argument("--batch-size", type=int, default=20, help="Genes per GraphQL batch")
    args = p.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    tract_path = out_dir / "ot_tractability.parquet"
    drugs_path = out_dir / "ot_known_drugs.parquet"

    if tract_path.exists() and drugs_path.exists() and not args.force:
        print("OpenTargets files already exist — skipping.")
        print("Use --force to re-download.")
        return

    gene_list_path = Path(args.gene_list) if args.gene_list else None
    genes = load_gene_list(gene_list_path)

    symbol_to_ensembl = symbols_to_ensembl(genes)
    if not symbol_to_ensembl:
        raise RuntimeError("No Ensembl IDs resolved — check network access.")

    tract_rows, drug_rows = query_opentargets(symbol_to_ensembl, batch_size=args.batch_size)

    if tract_rows:
        df_tract = pd.DataFrame(tract_rows)
        df_tract.to_parquet(tract_path, index=False)
        n_approved = df_tract[df_tract["has_approved_drug"]]["gene_symbol"].nunique()
        print(f"  ot_tractability.parquet   {len(df_tract):>8,} rows  "
              f"({df_tract['gene_symbol'].nunique()} genes, {n_approved} with approved drugs)")
    else:
        print("  [warn] No tractability data returned")

    if drug_rows:
        df_drugs = pd.DataFrame(drug_rows)
        df_drugs.to_parquet(drugs_path, index=False)
        approved = df_drugs[df_drugs["is_approved"]]["gene_symbol"].nunique()
        print(f"  ot_known_drugs.parquet    {len(df_drugs):>8,} rows  "
              f"({approved} genes with approved drugs)")
    else:
        print("  [warn] No drug data returned")

    print(f"\nDone.  Files written to {out_dir}/")
    print()
    print("Agent query examples:")
    print("  from biodiscoverygym.tools.opentargets import get_actionability, batch_actionability")
    print("  print(get_actionability('EGFR').summary())")
    print("  ranked = batch_actionability(['EGFR','TP53','MYC'])")


if __name__ == "__main__":
    main()
