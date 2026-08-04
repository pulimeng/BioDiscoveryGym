"""Shared path resolution for the per-episode staging directory.

WHY THIS MODULE EXISTS
----------------------
The anonymized episode data used to be staged at a single hardcoded `data/episode/`. Every
episode wrote its cohort there, the agent's executor read it back, and the episode deleted it on
the way out. That is correct for one process and silently wrong for two.

Run three model lanes concurrently and they share one staging directory: lane B truncates
`expression.parquet` while lane A is mid-read, and lane C `rmtree`s the whole thing when its
episode ends. The failure we actually saw was loud — `Parquet magic bytes not found in footer`,
every lane dead within minutes. That was the lucky outcome.

The unlucky outcome is the one this module exists to prevent: lane A opens the file a moment
AFTER lane B finished writing it, reads a complete and perfectly valid parquet belonging to a
different cohort, and runs an episode labelled `g2_brca_s42` on OV data. Nothing raises. The
episode completes, gets scored against BRCA's answer key, and lands in the results table looking
exactly like every other row. This project already has a documented history of defects that
render as benign values (docs/DATA_INTEGRITY_AUDIT.md); a cross-cohort read would be the worst
of them, because it corrupts the cohort identity the entire benchmark is built on measuring.

So the staging directory is per-process. Episode (writer) and CodeExecutor (reader) both resolve
it through this one function, which is what keeps them in agreement.

The PID is also safe to expose to the agent — unlike a cohort-bearing path it carries no identity
(same reasoning as the opaque `_work/<uuid>` dir in episode.py). Episode data is pre-loaded into
the agent's namespace rather than referenced by path, so this name never reaches the transcript.
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path

_STAGING_ROOT = "_episode"


def episode_data_dir(data_dir: str | Path = "data") -> Path:
    """Staging dir for THIS process's episode data. Unique per lane; never shared."""
    return Path(data_dir) / _STAGING_ROOT / f"pid{os.getpid()}"


def sweep_stale_staging(data_dir: str | Path = "data") -> int:
    """Drop staging dirs belonging to processes that no longer exist.

    A crashed or SIGKILLed episode never reaches its cleanup, so its directory survives — and at
    ~200 MB per cohort that accumulates fast across a 95-episode run. Only dirs whose PID is dead
    are removed, so this is safe to call while sibling lanes are running.
    """
    root = Path(data_dir) / _STAGING_ROOT
    if not root.is_dir():
        return 0
    removed = 0
    for d in root.iterdir():
        if not d.is_dir() or not d.name.startswith("pid"):
            continue
        try:
            pid = int(d.name[3:])
        except ValueError:
            continue
        try:
            os.kill(pid, 0)          # signal 0 = existence probe, sends nothing
        except ProcessLookupError:
            shutil.rmtree(d, ignore_errors=True)
            removed += 1
        except PermissionError:
            pass                     # alive, owned by another user — leave it alone
    return removed
