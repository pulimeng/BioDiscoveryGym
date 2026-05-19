"""
Download and preprocess PrimeKG for BioDiscoveryGym.

Source: Harvard Dataverse doi:10.7910/DVN/IXA7BM (Chandak et al. 2023)

Splits the full kg.csv into four purpose-specific parquets:
  data/networks/primekg_gene_gene.parquet     PPI — path-finding between marker genes
  data/networks/primekg_gene_drug.parquet     drug targets — next_experiment suggestions
  data/networks/primekg_gene_disease.parquet  gene-disease — driver gene context
  data/networks/primekg_gene_pathway.parquet  pathway membership — mechanism support

Usage:
    python scripts/download_primekg.py
    python scripts/download_primekg.py --out-dir data/networks
"""
from __future__ import annotations

import argparse
import io
from pathlib import Path

import pandas as pd
import requests

DATAVERSE_DOI = "doi:10.7910/DVN/IXA7BM"
DATAVERSE_API = "https://dataverse.harvard.edu/api"

# Relations to keep per split.
# PrimeKG naming convention: {x_type}_{y_type} with '/' stripped.
# e.g. gene/protein ↔ disease → "disease_protein"
SPLITS: dict[str, set[str]] = {
    "gene_gene": {
        "protein_protein",
    },
    "gene_drug": {
        "drug_protein",
    },
    "gene_disease": {
        "disease_protein",      # disease ↔ gene/protein
    },
    "gene_pathway": {
        "pathway_protein",      # pathway ↔ gene/protein
    },
}

ALL_KEEP = {r for relations in SPLITS.values() for r in relations}


def download_kg(out_dir: Path) -> pd.DataFrame:
    print("Fetching PrimeKG file list from Harvard Dataverse...")
    r = requests.get(
        f"{DATAVERSE_API}/datasets/:persistentId/versions/:latest/files",
        params={"persistentId": DATAVERSE_DOI},
        timeout=30,
    )
    r.raise_for_status()
    files = r.json()["data"]
    kg_file = next((f for f in files if f["dataFile"]["filename"] == "kg.csv"), None)
    if kg_file is None:
        raise FileNotFoundError(
            f"kg.csv not found. Available: {[f['dataFile']['filename'] for f in files]}"
        )

    file_id = kg_file["dataFile"]["id"]
    size_mb = kg_file["dataFile"]["filesize"] / 1024 / 1024
    print(f"  kg.csv — {size_mb:.0f} MB  (id={file_id})")
    print(f"  Downloading...")

    r = requests.get(
        f"{DATAVERSE_API}/access/datafile/{file_id}",
        timeout=600,
        stream=True,
    )
    r.raise_for_status()

    chunks, downloaded = [], 0
    for chunk in r.iter_content(chunk_size=1024 * 1024):
        chunks.append(chunk)
        downloaded += len(chunk)
        print(f"\r  {downloaded / 1024 / 1024:.0f} / {size_mb:.0f} MB", end="", flush=True)
    print()

    df = pd.read_csv(io.BytesIO(b"".join(chunks)))
    print(f"  Raw: {len(df):,} edges — {df['relation'].nunique()} relation types")
    print("  All relation types:")
    for r, n in df['relation'].value_counts().items():
        mark = "✓" if r in ALL_KEEP else " "
        print(f"    {mark} {r}: {n:,}")
    return df


def save_splits(df: pd.DataFrame, out_dir: Path) -> None:
    cols = ["x_name", "x_type", "y_name", "y_type", "relation", "display_relation"]

    for split_name, relations in SPLITS.items():
        mask = df["relation"].isin(relations)
        sub = df[mask][cols].reset_index(drop=True)
        path = out_dir / f"primekg_{split_name}.parquet"
        sub.to_parquet(path, index=False)
        size_mb = path.stat().st_size / 1024 / 1024
        print(f"  {path.name:<40} {len(sub):>8,} edges  {size_mb:.1f} MB")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--out-dir", default="data/networks")
    p.add_argument(
        "--skip-download",
        metavar="KG_CSV",
        help="Skip download and use a local kg.csv path instead",
    )
    p.add_argument(
        "--cache-csv",
        metavar="PATH",
        help="Save raw kg.csv here after download for later reuse (e.g. data/networks/kg.csv)",
    )
    p.add_argument(
        "--force",
        action="store_true",
        help="Re-split even if output parquets already exist",
    )
    args = p.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # Check if already done
    existing = [out_dir / f"primekg_{s}.parquet" for s in SPLITS]
    if all(p.exists() for p in existing) and not args.force:
        print("All PrimeKG split files already exist — skipping.")
        print("Use --force to re-split.")
        return

    if args.skip_download:
        print(f"Loading local kg.csv from {args.skip_download}...")
        df = pd.read_csv(args.skip_download)
    else:
        df = download_kg(out_dir)
        if args.cache_csv:
            cache_path = Path(args.cache_csv)
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            df.to_csv(cache_path, index=False)
            print(f"  Cached raw kg.csv → {cache_path}")

    print(f"\nSaving splits to {out_dir}/")
    save_splits(df, out_dir)

    print(f"\nDone. Agent query examples:")
    print(f"  # PPI path-finding:")
    print(f"  import pandas as pd, networkx as nx")
    print(f"  gg = pd.read_parquet('data/networks/primekg_gene_gene.parquet')")
    print(f"  G  = nx.from_pandas_edgelist(gg, 'x_name', 'y_name', 'display_relation')")
    print(f"  nx.shortest_path(G, 'BRCA2', 'TP53')")
    print(f"")
    print(f"  # Drug targets for a gene:")
    print(f"  gd = pd.read_parquet('data/networks/primekg_gene_drug.parquet')")
    print(f"  gd[gd['x_name'] == 'BRCA2'][['y_name', 'display_relation']]")


if __name__ == "__main__":
    main()
