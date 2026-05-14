"""
Download cancer driver gene annotations from OncoKB.

OncoKB cancer gene list (open, no auth required):
  - Gene symbol, is oncogene, is TSG, OncoKB level

Note: COSMIC Cancer Gene Census requires registration and is not freely scriptable.
OncoKB covers the same set of curated cancer drivers and is openly accessible.

Output:
  data/cancer_genes/
    oncokb_cancer_gene_list.tsv

Usage:
    python scripts/download_cancer_genes.py
"""

import argparse
from pathlib import Path

import requests
import urllib3
from tqdm import tqdm

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

ONCOKB_URL = "https://www.oncokb.org/api/v1/utils/cancerGeneList.txt"


def download_file(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and dest.stat().st_size > 0:
        print(f"  [skip] {dest.name}")
        return
    print(f"  Downloading {dest.name} ...")
    tmp = dest.with_suffix(dest.suffix + ".tmp")
    try:
        with requests.get(url, stream=True, timeout=120, verify=False) as r:
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


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="data/cancer_genes")
    args = parser.parse_args()

    out_dir = Path(args.out)

    print("\n=== OncoKB Cancer Gene List ===")
    download_file(ONCOKB_URL, out_dir / "oncokb_cancer_gene_list.tsv")

    print("\nDone.")


if __name__ == "__main__":
    main()
