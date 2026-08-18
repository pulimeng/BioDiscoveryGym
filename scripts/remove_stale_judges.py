#!/usr/bin/env python3
"""Remove the pre-panel judge artifacts — but only once the panel that replaces them is complete.

WHAT IS STALE. The old design's outputs: three same-model CoT passes (_cotsummary.json,
_cotsummary_j2.json, _cotsummary_j3.json), plus the single-judge _supportscores.json and
_v3scores.json. All carry no judge provenance (see judges_config), which is why they cannot
simply be relabelled as the nemotron lane.

ORDER MATTERS, AND IT IS NOT "DELETE THEN REGENERATE".

  1. regenerate  — run_judge_panel_v2.sh writes <artifact>_<tag>.json for all three judges
  2. verify      — panel_status.py must report complete (3 judges x 3 artifacts x every episode)
  3. MIGRATE     — 15 scripts read "_v3scores.json", 11 read "_supportscores.json", 14 read
                   "_cotsummary.json" by that exact name. Deleting before they are panel-aware
                   does not break loudly: several glob and would simply find nothing, reporting
                   empty tables and zero-length denominators as if that were the finding.
  4. remove      — this script

Deleting first would leave the project with no scored data at all for the days the
regeneration takes, and every analysis silently reporting on an empty set meanwhile.

A backup tarball is written by the operator before step 1 (results/tcga/_superseded/
judge_artifacts_pre_panel_*.tar.gz); this script refuses to run if it cannot find one.

Usage:  BDG_RUNS=clean python scripts/remove_stale_judges.py            # dry run, always
        BDG_RUNS=clean python scripts/remove_stale_judges.py --confirm  # actually delete
        ... --allow-unmigrated    # skip the step-3 check (you have migrated the readers)
"""
from __future__ import annotations

import glob
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import judges_config as J
import runs_config

STALE = ['_cotsummary.json', '_cotsummary_j2.json', '_cotsummary_j3.json',
         '_supportscores.json', '_v3scores.json']
BACKUP_GLOB = 'results/tcga/_superseded/judge_artifacts_pre_panel_*.tar.gz'


def main() -> int:
    confirm = '--confirm' in sys.argv
    here = os.path.dirname(os.path.abspath(__file__))

    backups = glob.glob(BACKUP_GLOB)
    if not backups:
        print(f"REFUSING: no backup matching {BACKUP_GLOB}.\n"
              f"  These files take days of API time to regenerate. Make one first.", file=sys.stderr)
        return 2
    print(f"  backup present: {max(backups, key=os.path.getmtime)}")

    rc = subprocess.run([sys.executable, os.path.join(here, 'panel_status.py'), '--json'],
                        capture_output=True, text=True).returncode
    if rc != 0:
        print("REFUSING: the replacement panel is INCOMPLETE.\n"
              "  Run scripts/panel_status.py to see the shortfall. Removing the stale files now\n"
              "  would leave the analysis with neither the old data nor the new.", file=sys.stderr)
        return 2
    print("  panel complete: YES")

    if '--allow-unmigrated' not in sys.argv:
        readers = set()
        for pat in ('_v3scores.json', '_supportscores.json', '_cotsummary.json'):
            for f in glob.glob(os.path.join(here, '*.py')):
                if os.path.basename(f) in ('remove_stale_judges.py', 'judges_config.py'):
                    continue
                if pat in open(f, encoding='utf-8', errors='ignore').read():
                    readers.add(os.path.basename(f))
        if readers:
            print(f"REFUSING: {len(readers)} script(s) still read the stale filenames directly:\n"
                  + "".join(f"    {r}\n" for r in sorted(readers))
                  + "  Migrate them to judges_config.suffix(kind, tag) first. They will not fail\n"
                    "  loudly without these files — most glob and would report empty results as\n"
                    "  though that were the finding.\n"
                    "  Override with --allow-unmigrated once you have checked them.", file=sys.stderr)
            return 2

    victims = []
    for d in runs_config.flat():
        for suf in STALE:
            victims += glob.glob(os.path.join(d, '*', '*' + suf))
    print(f"\n  stale files to remove: {len(victims)}")
    for suf in STALE:
        print(f"    {suf:24} {sum(1 for v in victims if v.endswith(suf))}")

    if not confirm:
        print("\n  DRY RUN — nothing deleted. Re-run with --confirm.")
        return 0
    for v in victims:
        os.remove(v)
    print(f"\n  removed {len(victims)} stale files.")
    return 0


if __name__ == '__main__':
    sys.exit(main())
