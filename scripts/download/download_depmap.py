"""
Download DepMap / CCLE public data.

Files fetched (DepMap 23Q4 by default):
  - OmicsExpressionProteinCodingGenesTPMLogp1.csv  (expression)
  - OmicsSomaticMutationsMatrixDamaging.csv        (mutation binary matrix)
  - OmicsCNGene.csv                                (copy-number)
  - CRISPRGeneEffect.csv                           (CRISPR KO scores)
  - Model.csv                                       (sample metadata)

Usage:
    python scripts/download_depmap.py --release 23Q4 --out data/depmap
"""

import argparse
import hashlib
import sys
import warnings
from pathlib import Path

import requests
import urllib3
from tqdm import tqdm

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# DepMap figshare article IDs per release
RELEASE_URLS: dict[str, dict[str, str]] = {
    "23Q4": {
        # IDs verified via https://api.figshare.com/v2/articles/24667905
        "expression": "https://ndownloader.figshare.com/files/43347204",
        "mutation": "https://ndownloader.figshare.com/files/43347516",
        "cnv": "https://ndownloader.figshare.com/files/43346913",
        "crispr": "https://ndownloader.figshare.com/files/43346616",
        "metadata": "https://ndownloader.figshare.com/files/43746708",
    },
    "24Q2": {
        # IDs verified via https://api.figshare.com/v2/articles/26261527
        "expression": "https://ndownloader.figshare.com/files/47596012",
        "mutation": "https://ndownloader.figshare.com/files/47596063",
        "cnv": "https://ndownloader.figshare.com/files/47596069",
        "crispr": "https://ndownloader.figshare.com/files/47596018",
        "metadata": "https://ndownloader.figshare.com/files/47596075",
    },
}

FILE_NAMES = {
    "expression": "OmicsExpressionProteinCodingGenesTPMLogp1.csv",
    "mutation": "OmicsSomaticMutationsMatrixDamaging.csv",
    "cnv": "OmicsCNGene.csv",
    "crispr": "CRISPRGeneEffect.csv",
    "metadata": "Model.csv",
}


def download_file(url: str, dest: Path, chunk_size: int = 1 << 20) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and dest.stat().st_size > 0:
        print(f"  [skip] {dest.name} already exists")
        return
    print(f"  Downloading {dest.name} ...")
    tmp = dest.with_suffix(dest.suffix + ".tmp")
    try:
        with requests.get(url, stream=True, timeout=120, verify=False) as r:
            r.raise_for_status()
            total = int(r.headers.get("content-length", 0))
            with open(tmp, "wb") as f, tqdm(total=total, unit="B", unit_scale=True) as bar:
                for chunk in r.iter_content(chunk_size):
                    f.write(chunk)
                    bar.update(len(chunk))
        if tmp.stat().st_size == 0:
            tmp.unlink()
            raise RuntimeError(f"Empty response for {dest.name} — URL may be blocked by proxy")
        tmp.rename(dest)
    except Exception:
        if tmp.exists():
            tmp.unlink()
        raise


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--release", default="23Q4", choices=list(RELEASE_URLS))
    parser.add_argument("--out", default="data/depmap")
    parser.add_argument(
        "--files",
        nargs="+",
        default=list(FILE_NAMES),
        choices=list(FILE_NAMES),
        help="Which files to download (default: all)",
    )
    args = parser.parse_args()

    out_dir = Path(args.out)
    urls = RELEASE_URLS[args.release]

    print(f"DepMap release: {args.release} → {out_dir.resolve()}")
    for key in args.files:
        dest = out_dir / FILE_NAMES[key]
        download_file(urls[key], dest)

    print("Done.")


if __name__ == "__main__":
    main()
