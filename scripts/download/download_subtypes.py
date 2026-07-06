"""
Download TCGA Pan-Cancer molecular subtype annotations from UCSC Xena.

Source: TCGASubtype.20170308.tsv.gz
  - BRCA: PAM50 (LumA, LumB, Her2, Basal, Normal)
  - PRAD: Fusion/mutation-based (ERG, ETV1/4, FLI1, SPOP, FOXA1, IDH1)
  - UCEC: POLE / MSI / CN_LOW / CN_HIGH
  - LUAD: iCluster 1–6
  - LIHC: iCluster 1–3

Output: data/subtypes/pancan_subtypes.tsv
  Columns: sample_id (12-char TCGA participant barcode), cohort, subtype

Usage:
    python scripts/download_subtypes.py
"""

import io
import gzip
from pathlib import Path

import pandas as pd
import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

XENA_URL = "https://pancanatlas.xenahubs.net/download/TCGASubtype.20170308.tsv.gz"
OUT_DIR = Path("data/subtypes")
OUT_FILE = OUT_DIR / "pancan_subtypes.tsv"

COHORTS = {"BRCA", "PRAD", "UCEC", "LUAD", "LIHC", "LUSC", "OVCA"}

# Map Xena cohort names → standard TCGA abbreviations used in this project
COHORT_REMAP = {"OVCA": "OV"}


def download(url: str) -> bytes:
    print(f"Downloading {url} ...")
    r = requests.get(url, verify=False, timeout=120)
    r.raise_for_status()
    print(f"  {len(r.content):,} bytes")
    return r.content


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    raw = download(XENA_URL)
    text = gzip.decompress(raw).decode("utf-8")
    df = pd.read_csv(io.StringIO(text), sep="\t")

    # sampleID is full barcode e.g. TCGA-OR-A5J1-01 → participant = TCGA-OR-A5J1
    df["participant_id"] = df["sampleID"].str[:12]

    # Subtype_Selected contains "COHORT.subtype" e.g. BRCA.LumA
    df["cohort"] = df["Subtype_Selected"].str.split(".").str[0]
    df = df[df["cohort"].isin(COHORTS)].copy()

    # Strip the cohort prefix from the label so it's just "LumA", "iCluster:1", etc.
    df["subtype"] = df["Subtype_Selected"].str.split(".", n=1).str[1]

    # Drop NA subtypes (keep UCEC.NA etc. as NaN — exclude from scoring)
    df = df[df["subtype"].notna() & (df["subtype"] != "NA")]

    # Remap cohort names to standard abbreviations
    df["cohort"] = df["cohort"].replace(COHORT_REMAP)

    out = df[["participant_id", "cohort", "subtype"]].rename(
        columns={"participant_id": "sample_id"}
    )
    out = out.drop_duplicates(subset="sample_id")
    out.to_csv(OUT_FILE, sep="\t", index=False)

    print(f"\nSaved {len(out)} labelled samples → {OUT_FILE}")
    for cohort, grp in out.groupby("cohort"):
        print(f"  {cohort}: {len(grp)} samples — {sorted(grp['subtype'].unique())}")


if __name__ == "__main__":
    main()
