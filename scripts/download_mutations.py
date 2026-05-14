"""
Download TCGA somatic mutation data from GDC and build a binary mutation matrix.

Per cohort:
  1. Query GDC for all open-access Masked Somatic Mutation MAF files
  2. Download and parse each (Hugo_Symbol, Variant_Classification, Tumor_Sample_Barcode)
  3. Retain only functional mutations (missense, nonsense, frameshift, splice, in-frame indel)
  4. Aggregate into a samples × genes binary matrix (1 = functionally mutated)
  5. Save to data/tcga/{cohort}/mutations.parquet

Usage:
    python scripts/download_mutations.py --cohorts LIHC BRCA
    python scripts/download_mutations.py  # all 5 default cohorts
"""

import argparse
import gzip
import io
import json
import time
from pathlib import Path

import pandas as pd
import requests
import urllib3
from tqdm import tqdm

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

GDC_FILES_ENDPOINT = "https://api.gdc.cancer.gov/files"
GDC_DATA_ENDPOINT  = "https://api.gdc.cancer.gov/data"

FUNCTIONAL_CLASSES = {
    "Missense_Mutation",
    "Nonsense_Mutation",
    "Frame_Shift_Del",
    "Frame_Shift_Ins",
    "Splice_Site",
    "In_Frame_Del",
    "In_Frame_Ins",
    "Translation_Start_Site",
    "Nonstop_Mutation",
}

DEFAULT_COHORTS = [
    "BRCA", "COAD", "HNSC", "KIRC", "LIHC", "LUAD", "LUSC", "OV", "PRAD", "SKCM", "UCEC",
]


def query_maf_files(project_id: str) -> list[dict]:
    filters = {
        "op": "and",
        "content": [
            {"op": "=", "content": {"field": "cases.project.project_id", "value": project_id}},
            {"op": "=", "content": {"field": "data_type",                "value": "Masked Somatic Mutation"}},
            {"op": "=", "content": {"field": "access",                   "value": "open"}},
        ],
    }
    params = {
        "filters": json.dumps(filters),
        "fields": "file_id,file_name,cases.submitter_id",
        "format": "json",
        "size": "2000",
    }
    r = requests.get(GDC_FILES_ENDPOINT, params=params, timeout=60, verify=False)
    r.raise_for_status()
    hits = r.json()["data"]["hits"]
    return [
        {
            "file_id": h["file_id"],
            "sample_id": h["cases"][0]["submitter_id"],
        }
        for h in hits
        if h.get("cases")
    ]


def download_maf(file_id: str, retries: int = 3) -> bytes:
    for attempt in range(retries):
        try:
            r = requests.post(
                GDC_DATA_ENDPOINT,
                json={"ids": [file_id]},
                stream=True,
                timeout=120,
                verify=False,
            )
            r.raise_for_status()
            return r.content
        except Exception as e:
            if attempt == retries - 1:
                raise
            time.sleep(2 ** attempt)


def parse_maf(content: bytes) -> list[tuple[str, str]]:
    """Return list of (sample_id_12, hugo_symbol) for functional mutations."""
    try:
        text = gzip.decompress(content).decode("utf-8", errors="replace")
    except Exception:
        text = content.decode("utf-8", errors="replace")

    results = []
    for line in text.splitlines():
        if line.startswith("#") or line.startswith("Hugo_Symbol"):
            continue
        parts = line.split("\t")
        if len(parts) < 16:
            continue
        gene      = parts[0]
        vclass    = parts[8]
        barcode   = parts[15]
        if vclass in FUNCTIONAL_CLASSES and gene:
            results.append((barcode[:12], gene))
    return results


def build_matrix(records: list[tuple[str, str]]) -> pd.DataFrame:
    """Build binary samples × genes mutation matrix."""
    df = pd.DataFrame(records, columns=["sample_id", "gene"])
    df = df.drop_duplicates()
    df["mutated"] = 1
    matrix = df.pivot_table(
        index="sample_id", columns="gene", values="mutated", fill_value=0
    )
    matrix.index.name = "sample_id"
    matrix.columns.name = None
    return matrix.astype("int8")


def process_cohort(cohort: str, out_dir: Path) -> None:
    project_id = f"TCGA-{cohort}"
    cache = out_dir / "mutations.parquet"
    if cache.exists():
        print(f"  [skip] {cohort} — mutations.parquet already exists")
        return

    print(f"\n=== {project_id} ===")
    files = query_maf_files(project_id)
    print(f"  {len(files)} MAF files found")

    records: list[tuple[str, str]] = []
    for entry in tqdm(files, desc=f"  {cohort} MAFs"):
        try:
            content = download_maf(entry["file_id"])
            records.extend(parse_maf(content))
        except Exception as e:
            tqdm.write(f"  WARN: {entry['file_id']} failed: {e}")

    if not records:
        print(f"  No mutations parsed for {cohort}")
        return

    matrix = build_matrix(records)
    print(f"  Matrix: {matrix.shape[0]} samples × {matrix.shape[1]} genes")
    matrix.to_parquet(cache)
    print(f"  Saved → {cache}")

    # Quick summary of top mutated genes
    top = matrix.sum(axis=0).sort_values(ascending=False).head(10)
    print("  Top mutated genes:", list(top.index))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cohorts", nargs="+", default=DEFAULT_COHORTS)
    parser.add_argument("--out", default="data/tcga")
    args = parser.parse_args()

    for cohort in args.cohorts:
        cohort = cohort.upper()
        out_dir = Path(args.out) / cohort.lower()
        out_dir.mkdir(parents=True, exist_ok=True)
        process_cohort(cohort, out_dir)

    print("\nDone.")


if __name__ == "__main__":
    main()
