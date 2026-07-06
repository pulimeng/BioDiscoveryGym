"""
Download GDSC1 + GDSC2 drug-response data for validation.

Source: cancerrxgene.org (GDSC v8.4)
  - Drug response AUC / IC50 matrices
  - Cell line metadata

Usage:
    python scripts/download_gdsc.py --out data/gdsc
"""

import argparse
from pathlib import Path

import requests
import urllib3
from tqdm import tqdm

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

GDSC_FILES = {
    "gdsc1_ic50": {
        "url": "https://cog.sanger.ac.uk/cancerrxgene/GDSC_release8.4/GDSC1_fitted_dose_response_24Jul22.xlsx",
        "name": "GDSC1_fitted_dose_response.xlsx",
    },
    "gdsc2_ic50": {
        "url": "https://cog.sanger.ac.uk/cancerrxgene/GDSC_release8.4/GDSC2_fitted_dose_response_24Jul22.xlsx",
        "name": "GDSC2_fitted_dose_response.xlsx",
    },
    "cell_lines": {
        "url": "https://cog.sanger.ac.uk/cancerrxgene/GDSC_release8.4/Cell_Lines_Details.xlsx",
        "name": "Cell_Lines_Details.xlsx",
    },
    "drug_list": {
        "url": "https://cog.sanger.ac.uk/cancerrxgene/GDSC_release8.4/screened_compounds_rel_8.4.csv",
        "name": "screened_compounds.csv",
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
    parser.add_argument("--out", default="data/gdsc")
    parser.add_argument(
        "--files",
        nargs="+",
        default=list(GDSC_FILES),
        choices=list(GDSC_FILES),
    )
    args = parser.parse_args()

    out_dir = Path(args.out)
    print(f"GDSC → {out_dir.resolve()}")
    for key in args.files:
        meta = GDSC_FILES[key]
        download_file(meta["url"], out_dir / meta["name"])

    print("Done.")


if __name__ == "__main__":
    main()
