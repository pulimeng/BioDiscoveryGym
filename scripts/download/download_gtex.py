"""
Download GTEx v8 tissue-median expression for use as normal-tissue baseline.

Agents use this to distinguish context-specific signal from tissue-normal expression.

Downloads:
  - GTEx_Analysis_2017-06-05_v8_RNASeQCv1.1.9_gene_median_tpm.gct.gz
    Rows = genes (ENSG IDs + symbol), Columns = 54 tissue types, values = median TPM

Output:
  data/gtex/
    gene_median_tpm.gct.gz          raw GCT file
    gene_median_tpm.parquet         parsed: genes × tissues, indexed by gene_symbol

Usage:
    python scripts/download_gtex.py
"""

import argparse
import gzip
import io
from pathlib import Path

import pandas as pd
import requests
import urllib3
from tqdm import tqdm

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

GTEX_URL = (
    "https://storage.googleapis.com/adult-gtex/bulk-gex/v8/rna-seq/"
    "GTEx_Analysis_2017-06-05_v8_RNASeQCv1.1.9_gene_median_tpm.gct.gz"
)


def download_file(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and dest.stat().st_size > 0:
        print(f"  [skip] {dest.name}")
        return
    print(f"  Downloading {dest.name} ...")
    tmp = dest.with_suffix(dest.suffix + ".tmp")
    try:
        with requests.get(url, stream=True, timeout=300, verify=False) as r:
            r.raise_for_status()
            total = int(r.headers.get("content-length", 0))
            with open(tmp, "wb") as f, tqdm(total=total, unit="B", unit_scale=True) as bar:
                for chunk in r.iter_content(1 << 20):
                    f.write(chunk)
                    bar.update(len(chunk))
        if tmp.stat().st_size == 0:
            tmp.unlink()
            raise RuntimeError(f"Empty response for {dest.name}")
        tmp.rename(dest)
    except Exception:
        if tmp.exists():
            tmp.unlink()
        raise


def parse_gct(gz_path: Path) -> pd.DataFrame:
    """
    Parse GCT v1.2 format:
      line 0: #1.2
      line 1: nrows  ncols
      line 2: header (Name, Description, tissue1, tissue2, ...)
      lines 3+: data rows
    Returns DataFrame indexed by gene_symbol (Description col).
    """
    print("  Parsing GCT → parquet ...")
    with gzip.open(gz_path, "rt") as f:
        f.readline()  # #1.2
        f.readline()  # dimensions
        content = f.read()

    df = pd.read_csv(io.StringIO(content), sep="\t")
    # Columns: Name (ENSG), Description (symbol), <tissues>
    df = df.rename(columns={"Description": "gene_symbol"})
    df = df.drop(columns=["Name"], errors="ignore")
    df = df.set_index("gene_symbol")
    return df


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="data/gtex")
    args = parser.parse_args()

    out_dir = Path(args.out)
    gz_path = out_dir / "gene_median_tpm.gct.gz"
    parquet_path = out_dir / "gene_median_tpm.parquet"

    download_file(GTEX_URL, gz_path)

    if parquet_path.exists() and parquet_path.stat().st_size > 0:
        print(f"  [skip] {parquet_path.name}")
    else:
        df = parse_gct(gz_path)
        df.to_parquet(parquet_path)
        print(f"  Saved {df.shape[0]:,} genes × {df.shape[1]} tissues → {parquet_path.name}")

    print("Done.")


if __name__ == "__main__":
    main()
