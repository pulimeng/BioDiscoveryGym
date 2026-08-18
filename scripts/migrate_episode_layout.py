#!/usr/bin/env python3
"""Reorganise every episode directory into  harness-root / outputs/ / scoring/<judge>/.

WHY. The episode directory flattened three provenances into one namespace — harness inputs,
the agent's own analysis outputs, and scorer artifacts. Episode discovery therefore relied on
a glob plus a blocklist of substrings guessed to appear in non-episode filenames, and agents
demonstrably invent names that guess does not cover. See judges_config for the full note.

WHAT MOVES
  <stem>.json/.md/.log, codebook.json, gene_map.json, sample_codebook.json,
  grouping.json, grouping_blinded_k5.json          -> stay at the episode root (harness)
  <stem>_v3trace.json                              -> scoring/v3trace.json (judge-independent)
  everything else that is not a scorer artifact    -> outputs/            (agent-created)

WHAT IS REMOVED (--remove-stale)
  The pre-panel scorer artifacts: _cotsummary.json, _cotsummary_j2.json, _cotsummary_j3.json,
  _supportscores.json, _v3scores.json. These carry no judge provenance and are superseded by
  the panel regeneration. They are NOT migrated into scoring/<judge>/ because there is no
  honest judge name to file them under.

  They are only removed if a backup tarball exists — regenerating them costs days of API time.

Usage:  BDG_RUNS=clean python scripts/migrate_episode_layout.py                 # dry run
        BDG_RUNS=clean python scripts/migrate_episode_layout.py --apply
        ...                                        --apply --remove-stale
"""
from __future__ import annotations

import glob
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import judges_config as J
import runs_config

BACKUP_GLOB = 'results/tcga/_superseded/judge_artifacts_pre_panel_*.tar.gz'
# Any judge artifact, current or legacy, identified by substring on the FLAT filename.
SCORER_MARKS = ('_v3scores', '_supportscores', '_cotsummary', '_v3trace')


def episodes():
    for d in runs_config.flat():
        for e in sorted(glob.glob(os.path.join(d, '*'))):
            if os.path.isdir(e) and not os.path.basename(e).startswith(('_', '.')):
                yield e


def plan(ep: str):
    """(to_outputs, trace_file, tagged, stale) for one episode directory.

    `tagged` are scorer artifacts that DO name their judge (written since the panel change) —
    they are migrated into scoring/<tag>/, not deleted. `stale` are the untagged pre-panel
    files, which have no judge to file them under. Lumping the two together would delete valid,
    provenance-bearing judgements as though they were legacy, and the only visible sign would
    be a larger regeneration bill.
    """
    stem = os.path.basename(ep)
    legacy = {f for fs in J.LEGACY_ARTIFACTS.values() for f in fs}
    tagged_map = {f'_{J.ARTIFACTS[k][:-5]}_{t}.json'.replace('_cotsummary_', '_cotsummary_')
                  : (k, t) for k in J.ARTIFACTS for t in J.tags()}
    # built explicitly to avoid guessing at the flat naming used before the move
    tagged_map = {}
    for k, base in (('cot', '_cotsummary'), ('support', '_supportscores'), ('outcome', '_v3scores')):
        for t in J.tags():
            tagged_map[f'{base}_{t}.json'] = (k, t)

    to_outputs, trace, tagged, stale = [], None, [], []
    for f in sorted(os.listdir(ep)):
        p = os.path.join(ep, f)
        if f.startswith('.'):
            continue
        if os.path.isdir(p):
            # Agents write DIRECTORIES too — gseapy and enrichr drop a results folder per
            # gene set (gsea_hallmark/, enrichr_c1/, prerank_reactome_cluster_3/, ~90 of them
            # across the run, every name invented by the agent). A file-only migration leaves
            # these at the episode root, which is precisely the mixed namespace this move
            # exists to end. Only our own two directories are exempt.
            if f not in (J.OUTPUTS_DIR, J.SCORING_DIR):
                to_outputs.append(f)
            continue
        if f in J.HARNESS_FILES or f in (f'{stem}.json', f'{stem}.md', f'{stem}.log'):
            continue
        rest = f[len(stem):] if f.startswith(stem) else f
        if rest == '_v3trace.json':
            trace = f
        elif rest in tagged_map:
            tagged.append((f, *tagged_map[rest]))
        elif rest in legacy:
            stale.append(f)
        elif any(m in f for m in SCORER_MARKS):
            stale.append(f)                      # unrecognised scorer artifact -> treat as stale
        else:
            to_outputs.append(f)
    return to_outputs, trace, tagged, stale


def main() -> int:
    apply_ = '--apply' in sys.argv
    rm = '--remove-stale' in sys.argv
    if rm and not glob.glob(BACKUP_GLOB):
        print(f"REFUSING --remove-stale: no backup matching {BACKUP_GLOB}", file=sys.stderr)
        return 2

    eps = list(episodes())
    n_out = n_stale = n_trace = n_tag = 0
    for ep in eps:
        outs, trace, tagged, stale = plan(ep)
        n_out += len(outs); n_stale += len(stale); n_trace += bool(trace); n_tag += len(tagged)
        if not apply_:
            continue
        if outs:
            os.makedirs(J.outputs_dir(ep), exist_ok=True)
            for f in outs:
                shutil.move(os.path.join(ep, f), os.path.join(J.outputs_dir(ep), f))
        os.makedirs(J.scoring_dir(ep), exist_ok=True)
        if trace:
            shutil.move(os.path.join(ep, trace), os.path.join(J.scoring_dir(ep), J.TRACE_FILE))
        for f, kind, tag in tagged:
            os.makedirs(J.scoring_dir(ep, tag), exist_ok=True)
            shutil.move(os.path.join(ep, f), J.artifact_path(ep, kind, tag))
        if rm:
            for f in stale:
                os.remove(os.path.join(ep, f))

    print(f"  episodes                 : {len(eps)}")
    print(f"  -> outputs/              : {n_out} agent files")
    print(f"  -> scoring/v3trace.json  : {n_trace}")
    print(f"  -> scoring/<judge>/      : {n_tag} provenance-bearing artifacts (KEPT)")
    print(f"  untagged pre-panel files : {n_stale} " + ("(REMOVED)" if (apply_ and rm) else
                                                        "(kept — pass --remove-stale)"))
    if not apply_:
        print("\n  DRY RUN — nothing moved. Re-run with --apply.")
    return 0


if __name__ == '__main__':
    sys.exit(main())
