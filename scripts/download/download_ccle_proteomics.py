"""
Download CCLE proteomics (mass-spectrometry protein abundance).

Source: Nusinow et al. 2020 Cell — "Quantitative Proteomics of the Cancer Cell Line Encyclopedia"
        https://gygi.hms.harvard.edu/publications/ccle.html

Data: ~375 cell lines × ~12,755 proteins, normalized TMT log2 protein abundance.
      Rows = proteins (Gene_Symbol column), Columns = CCLE cell-line names.

Output:
  data/ccle_proteomics/protein_quant_current_normalized.csv.gz   (raw, ~25 MB)

Usage:
    python scripts/download_ccle_proteomics.py
"""

import gzip
import shutil
from pathlib import Path

import requests
import urllib3
from tqdm import tqdm

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

OUT_DIR = Path("data/ccle_proteomics")
URL = "https://gygi.hms.harvard.edu/data/ccle/protein_quant_current_normalized.csv.gz"
OUT_FILE = "protein_quant_current_normalized.csv.gz"


def download() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    dest = OUT_DIR / OUT_FILE
    if dest.exists() and dest.stat().st_size > 0:
        print(f"  [skip] {dest.name} already exists ({dest.stat().st_size / 1e6:.1f} MB)")
        return

    tmp = dest.with_suffix(".tmp")
    print(f"  Downloading {OUT_FILE} ...")
    try:
        with requests.get(URL, stream=True, timeout=300, verify=False) as r:
            r.raise_for_status()
            total = int(r.headers.get("content-length", 0))
            with open(tmp, "wb") as f, tqdm(total=total, unit="B", unit_scale=True) as bar:
                for chunk in r.iter_content(1 << 20):
                    f.write(chunk)
                    bar.update(len(chunk))
        if tmp.stat().st_size == 0:
            tmp.unlink()
            raise RuntimeError("Empty response")
        tmp.rename(dest)
        print(f"  Done: {dest} ({dest.stat().st_size / 1e6:.1f} MB)")
    except Exception:
        if tmp.exists():
            tmp.unlink()
        raise


if __name__ == "__main__":
    print("\n=== CCLE Proteomics (Nusinow et al. 2020) ===")
    download()
    print("\nDone.")
    print("Key columns: Gene_Symbol, then one column per CCLE cell line (~375 lines × ~12,755 proteins)")
