"""
Download Human Protein Atlas (HPA) normal tissue protein expression data.

Source: proteinatlas.org — freely available, no registration required.
Data: protein-level expression across 44 normal human tissues + cell types.

Key columns used downstream:
  Gene          — HGNC symbol
  Tissue        — tissue name (e.g., "liver", "bone marrow")
  Cell type     — cell type within tissue
  Level         — Negative / Low / Medium / High
  Reliability   — Approved / Supported / Enhanced / Uncertain

Output:
  data/hpa/normal_tissue.tsv   (~30 MB uncompressed)

Usage:
    python scripts/download_hpa.py
"""

import gzip
import shutil
from pathlib import Path

import requests
import urllib3
from tqdm import tqdm

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

OUT_DIR = Path("data/hpa")
URL = "https://v23.proteinatlas.org/download/normal_tissue.tsv.zip"
OUT_FILE = "normal_tissue.tsv"


def download() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    dest = OUT_DIR / OUT_FILE
    if dest.exists() and dest.stat().st_size > 0:
        print(f"  [skip] {dest.name} already exists ({dest.stat().st_size / 1e6:.1f} MB)")
        return

    tmp = dest.with_suffix(".zip.tmp")
    print(f"  Downloading {OUT_FILE} ...")
    try:
        with requests.get(URL, stream=True, timeout=300, verify=False) as r:
            r.raise_for_status()
            total = int(r.headers.get("content-length", 0))
            with open(tmp, "wb") as f, tqdm(total=total, unit="B", unit_scale=True) as bar:
                for chunk in r.iter_content(1 << 20):
                    f.write(chunk)
                    bar.update(len(chunk))

        print(f"  Extracting → {dest.name} ...")
        import zipfile
        with zipfile.ZipFile(tmp) as zf:
            names = zf.namelist()
            tsv_name = next((n for n in names if n.endswith(".tsv")), names[0])
            with zf.open(tsv_name) as src, open(dest, "wb") as dst:
                shutil.copyfileobj(src, dst)
        tmp.unlink()

        print(f"  Done: {dest} ({dest.stat().st_size / 1e6:.1f} MB)")
    except Exception:
        if tmp.exists():
            tmp.unlink()
        raise


if __name__ == "__main__":
    print("\n=== Human Protein Atlas — Normal Tissue ===")
    download()
    print("\nDone.")
    print("Key columns: Gene, Tissue, Cell type, Level (Negative/Low/Medium/High), Reliability")
