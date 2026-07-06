"""
Download PRISM drug-response data (Repurposing Secondary Screen).

Primary download: PRISM Repurposing 19Q4 secondary screen
  - logfold-change matrix (cell lines × compounds)
  - treatment info (compound metadata)

Usage:
    python scripts/download_prism.py --out data/prism
"""

import argparse
from pathlib import Path

import requests
import urllib3
from tqdm import tqdm

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

PRISM_FILES = {
    # IDs verified via https://api.figshare.com/v2/articles/9393293
    "lfc_matrix": {
        "url": "https://ndownloader.figshare.com/files/20237757",
        "name": "secondary-screen-replicate-collapsed-logfold-change.csv",
    },
    "treatment_info": {
        "url": "https://ndownloader.figshare.com/files/20237763",
        "name": "secondary-screen-replicate-collapsed-treatment-info.csv",
    },
    "cell_line_info": {
        "url": "https://ndownloader.figshare.com/files/20237769",
        "name": "secondary-screen-cell-line-info.csv",
    },
}


def download_file(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and dest.stat().st_size > 0:
        print(f"  [skip] {dest.name} already exists")
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
            raise RuntimeError(f"Empty response for {dest.name} — URL may be blocked by proxy")
        tmp.rename(dest)
    except Exception:
        if tmp.exists():
            tmp.unlink()
        raise


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="data/prism")
    parser.add_argument(
        "--files",
        nargs="+",
        default=list(PRISM_FILES),
        choices=list(PRISM_FILES),
    )
    args = parser.parse_args()

    out_dir = Path(args.out)
    print(f"PRISM → {out_dir.resolve()}")
    for key in args.files:
        meta = PRISM_FILES[key]
        download_file(meta["url"], out_dir / meta["name"])

    print("Done.")


if __name__ == "__main__":
    main()
