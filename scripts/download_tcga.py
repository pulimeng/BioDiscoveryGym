"""
Download TCGA expression + clinical data via GDC API for sealed evaluation.

Downloads raw files only — matrix building and log-TPM conversion happen in
process_tcga.py (run after this script completes).

For each cohort downloads:
  - Expression: STAR-Counts per-sample TSVs bundled as batch_XXXX.tar.gz.
    Contains raw counts + FPKM + FPKM_UQ + TPM columns per gene.
    process_tcga.py extracts these, selects tpm_unstranded, and builds the matrix.
  - Clinical: case metadata via GDC /cases endpoint (diagnosis, stage, survival).

The sealed 20% split is created by build_sealed_slice.py (run after process_tcga.py).

Usage:
    python scripts/download_tcga.py --cohorts BRCA LUAD --out data/tcga

Requires: requests, pandas, tqdm
GDC API docs: https://docs.gdc.cancer.gov/API/Users_Guide/Getting_Started/
"""

import argparse
import json
from pathlib import Path

import pandas as pd
import requests
import urllib3
from tqdm import tqdm

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

GDC_FILES_ENDPOINT = "https://api.gdc.cancer.gov/files"
GDC_DATA_ENDPOINT = "https://api.gdc.cancer.gov/data"
GDC_CASES_ENDPOINT = "https://api.gdc.cancer.gov/cases"

CLINICAL_FIELDS = ",".join([
    "submitter_id",
    "diagnoses.primary_diagnosis",
    "diagnoses.tumor_stage",
    "diagnoses.age_at_diagnosis",
    "diagnoses.days_to_death",
    "diagnoses.days_to_last_follow_up",
    "demographic.gender",
    "demographic.race",
    "demographic.vital_status",
    "demographic.days_to_death",
])


def query_gdc_files(project_id: str, data_category: str, data_type: str) -> list[dict]:
    filters = {
        "op": "and",
        "content": [
            {"op": "=", "content": {"field": "cases.project.project_id", "value": project_id}},
            {"op": "=", "content": {"field": "data_category", "value": data_category}},
            {"op": "=", "content": {"field": "data_type", "value": data_type}},
            {"op": "=", "content": {"field": "access", "value": "open"}},
        ],
    }
    params = {
        "filters": json.dumps(filters),
        "fields": "file_id,file_name,cases.case_id,cases.submitter_id",
        "format": "json",
        "size": "2000",
    }
    r = requests.get(GDC_FILES_ENDPOINT, params=params, timeout=60, verify=False)
    r.raise_for_status()
    return r.json()["data"]["hits"]


def download_gdc_manifest(file_ids: list[str], dest: Path, max_retries: int = 5) -> None:
    """Download a set of files from GDC using the data endpoint."""
    import time
    dest.mkdir(parents=True, exist_ok=True)
    batch_size = 100
    for i in tqdm(range(0, len(file_ids), batch_size), desc="GDC batches"):
        fname = dest / f"batch_{i // batch_size:04d}.tar.gz"
        if fname.exists() and fname.stat().st_size > 0:
            continue
        batch = file_ids[i : i + batch_size]
        params = {"ids": batch}
        tmp = fname.with_suffix(".tar.gz.tmp")
        for attempt in range(max_retries):
            try:
                r = requests.post(GDC_DATA_ENDPOINT, json=params, stream=True, timeout=300, verify=False)
                r.raise_for_status()
                with open(tmp, "wb") as f:
                    for chunk in r.iter_content(1 << 20):
                        f.write(chunk)
                if tmp.stat().st_size == 0:
                    raise RuntimeError("Empty response from GDC")
                tmp.rename(fname)
                break
            except Exception as e:
                if tmp.exists():
                    tmp.unlink()
                if attempt < max_retries - 1:
                    wait = 2 ** attempt
                    print(f"\n  [retry {attempt+1}/{max_retries}] {e} — waiting {wait}s")
                    time.sleep(wait)
                else:
                    raise


def download_clinical(project_id: str, dest: Path) -> None:
    """Download clinical metadata via GDC /cases endpoint and save as TSV."""
    dest.mkdir(parents=True, exist_ok=True)
    cohort = project_id.split("-")[1]
    out_file = dest / f"{cohort}_clinical.tsv"
    if out_file.exists() and out_file.stat().st_size > 0:
        print(f"  [skip] {out_file.name}")
        return

    filters = json.dumps({
        "op": "=",
        "content": {"field": "project.project_id", "value": project_id},
    })
    params = {
        "filters": filters,
        "fields": CLINICAL_FIELDS,
        "format": "json",
        "size": "10000",
    }
    print(f"  Downloading clinical: {cohort}")
    r = requests.get(GDC_CASES_ENDPOINT, params=params, timeout=120, verify=False)
    r.raise_for_status()

    hits = r.json()["data"]["hits"]
    rows = []
    for h in hits:
        row = {"case_id": h["submitter_id"]}
        demo = h.get("demographic", {})
        row.update({
            "gender": demo.get("gender"),
            "race": demo.get("race"),
            "vital_status": demo.get("vital_status"),
            "days_to_death": demo.get("days_to_death"),
        })
        diag = (h.get("diagnoses") or [{}])[0]
        row.update({
            "primary_diagnosis": diag.get("primary_diagnosis"),
            "tumor_stage": diag.get("tumor_stage"),
            "age_at_diagnosis": diag.get("age_at_diagnosis"),
            "days_to_last_follow_up": diag.get("days_to_last_follow_up"),
        })
        rows.append(row)

    pd.DataFrame(rows).to_csv(out_file, sep="\t", index=False)
    print(f"  Saved {len(rows)} cases → {out_file.name}")


# 11 cohorts covering both benchmarks:
#   Target discovery: BRCA, COAD, HNSC, KIRC, LIHC, LUAD, LUSC, OV, PRAD, SKCM
#   Anomaly detection: BRCA, LUAD, LUSC, LIHC, OV, PRAD, UCEC
DEFAULT_COHORTS = [
    "BRCA",   # Breast — PAM50 subtypes, large N ~1100
    "COAD",   # Colon — MSI vs MSS, CMS subtypes
    "HNSC",   # Head & neck — HPV status
    "KIRC",   # Kidney clear cell — VHL mutation status
    "LIHC",   # Liver — HBV/HCV etiology
    "LUAD",   # Lung adenocarcinoma — KRAS/EGFR/ALK subtypes
    "LUSC",   # Lung squamous — separate lineage from LUAD
    "OV",     # Ovarian — BRCA1/2 HRD, platinum sensitivity
    "PRAD",   # Prostate — Gleason grade groups
    "SKCM",   # Melanoma — BRAF/NRAS mutation status
    "UCEC",   # Uterine — endometrioid vs serous subtypes (anomaly benchmark)
]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cohorts", nargs="+", default=DEFAULT_COHORTS)
    parser.add_argument("--out", default="data/tcga")
    args = parser.parse_args()

    out_dir = Path(args.out)

    for cohort in args.cohorts:
        project_id = f"TCGA-{cohort}"
        cohort_dir = out_dir / cohort.lower()
        cohort_dir.mkdir(parents=True, exist_ok=True)

        print(f"\n=== {project_id} ===")

        # Clinical metadata
        download_clinical(project_id, cohort_dir)

        # Gene expression — STAR-Counts (raw counts + TPM columns per sample)
        print(f"  Querying GDC for expression files...")
        files = query_gdc_files(
            project_id,
            data_category="Transcriptome Profiling",
            data_type="Gene Expression Quantification",
        )
        print(f"  Found {len(files)} expression files")

        file_ids = [f["file_id"] for f in files]
        manifest_path = cohort_dir / "file_manifest.json"
        manifest_path.write_text(json.dumps(files, indent=2))

        if file_ids:
            download_gdc_manifest(file_ids, cohort_dir / "expression_raw")

    print("\nDone. Run scripts/build_sealed_slice.py next.")


if __name__ == "__main__":
    main()
