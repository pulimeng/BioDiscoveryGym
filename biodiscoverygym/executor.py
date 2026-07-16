"""
CodeExecutor: stateful Python execution environment for Task A (cohort analysis) agents.

- Maintains a persistent namespace across calls (variables survive between run_code invocations)
- Pre-loads expression + metadata from data/episode/ on construction
- Captures stdout and returns it as a string
- Blocks access to internal keys, raw TCGA source files, and prior scored results
- Network access blocking is handled externally by sandbox.py

Task B (target discovery) uses TargetDiscoveryExecutor in executor_target.py, which has
its own block list covering the reference datasets it pre-loads with anonymized gene names.
"""

from __future__ import annotations

import contextlib
import io
import signal
import threading
import time
import traceback
from pathlib import Path

import matplotlib
matplotlib.use("Agg")  # non-interactive backend — must be set before any other matplotlib import
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from biodiscoverygym.tools.multimodal import multimodal_cluster


# Paths the Task A cohort agent must not read.
# data/tcga, data/external — raw source files contain real gene/sample names and could
#   reveal cohort identity or bypass anonymization entirely.
# results/ and _evaluation — block traversal to prior scored episodes and gene maps.
# Geneset paths are gated (see _GENESET_BLOCKS below) and lifted at Stage 5 codebook reveal.
# Reference databases (depmap, gtex, gnomad, etc.) are NOT blocked here — Task A agents
# may cross-reference them legitimately after the codebook is revealed. Task B has its own
# executor (executor_target.py) with a separate block list covering those paths.
_BLOCKED_SUBSTRINGS = (
    "data/sealed",
    ".biodiscoverygym/vault",
    "episode_key",
    "data/tcga",
    "data/external",  # raw source files (e.g. os_jia2022/) with real gene/sample names
    "data/subtypes",
    "data/genesets",
    "data/cancer_genes",
    "gene_map.json",
    "_gene_map",
    "_evaluation",
    "results/",
)

# Blocks that are lifted when the gene codebook is revealed at Stage 5.
# Genesets are blocked during anonymized stages to prevent inference of gene
# identity from pathway membership (e.g., reading KRAS signaling members to
# identify GENE_XXXXX = KRAS before the codebook is released).
_GENESET_BLOCKS = ("data/genesets", "data/cancer_genes")

# Hard cap on output length returned to Claude (characters)
_MAX_OUTPUT_CHARS = 20_000

# Wall-clock cap on a SINGLE run_code call. Agents occasionally write correct but
# pathologically slow analyses: a per-gene t-test loop plus a CNA enrichment loop that
# re-evaluated `[('amp', cc>0), ('del', cc<0)]` (two full copy-number matrix comparisons)
# inside its innermost loop once ran 21.4h and returned *successfully* — silently
# dominating a 21.5h episode whose science was otherwise correct. Observed healthy calls:
# median 0.1s, p99 37.5s — 600s leaves ~16x headroom over the p99 while bounding the tail.
_EXEC_TIMEOUT_S = 600

_TIMEOUT_MSG = (
    "TimeoutError: this run_code call exceeded the {t}s wall-clock limit and was interrupted.\n"
    "Any stdout above is partial (printed before the interrupt), and the namespace may now hold "
    "partially-assigned variables from this call — re-assign anything you intend to reuse.\n"
    "The usual cause is an un-vectorized loop over genes/samples. Prefer array operations: e.g. a "
    "per-gene `for g in genes: stats.ttest_ind(a[g], b[g])` over thousands of genes should become a "
    "single `stats.ttest_ind(A, B, axis=0)` on the stacked arrays, which is ~1000x faster.\n"
    "Rewrite the analysis vectorized and call run_code again."
)


class _ExecTimeout(Exception):
    """Raised inside exec() by the SIGALRM handler when a call overruns."""


@contextlib.contextmanager
def _time_limit(seconds: int):
    """
    Wall-clock cap on one exec() call, via SIGALRM.

    exec() runs in-process so the namespace persists across run_code calls, which rules
    out the usual subprocess-with-timeout approach. SIGALRM raises at the next bytecode
    boundary — that catches the Python-level loops which are the actual hazard here. A
    single long-running C call (one huge BLAS/numpy op) won't interrupt until it returns
    to the interpreter; that's an accepted gap, since those aren't the observed failure.

    No-ops where SIGALRM can't be used (non-Unix, or off the main thread).
    """
    if (
        seconds <= 0
        or not hasattr(signal, "SIGALRM")
        or threading.current_thread() is not threading.main_thread()
    ):
        yield
        return

    def _handler(signum, frame):  # noqa: ARG001
        raise _ExecTimeout

    prev = signal.signal(signal.SIGALRM, _handler)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, prev)


class CodeExecutor:
    """
    Stateful Python sandbox.

    Usage:
        executor = CodeExecutor(data_dir="data")
        out = executor.execute("print(expression.shape)")
        # → "(1095, 19938)\\n"
    """

    def __init__(
        self,
        data_dir: str | Path = "data",
        output_dir: str | Path | None = None,
        exec_timeout_s: int = _EXEC_TIMEOUT_S,
    ):
        data_dir = Path(data_dir)
        self.output_dir = Path(output_dir) if output_dir else Path("results") / "misc"
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self._blocked: list[str] = list(_BLOCKED_SUBSTRINGS)
        self.namespace: dict = self._build_namespace(data_dir)
        self.timing_log: list[dict] = []
        self._exec_count: int = 0
        self.exec_timeout_s = exec_timeout_s  # per-call wall-clock cap; <=0 disables

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def unblock_genesets(self) -> None:
        """Lift the geneset file blocks after the gene codebook has been revealed."""
        self._blocked = [b for b in self._blocked if b not in _GENESET_BLOCKS]

    def execute(self, code: str) -> str:
        """
        Execute code in the persistent namespace. Returns stdout (truncated
        to _MAX_OUTPUT_CHARS) or an error traceback string.
        """
        violation = self._check_blocked_paths(code)
        if violation:
            output = f"PermissionError: access to '{violation}' is not permitted during an episode."
            self.timing_log.append({
                "call_num": self._exec_count,
                "exec_time_s": 0.0,
                "output_chars": len(output),
                "is_error": True,
            })
            self._exec_count += 1
            return output

        buf = io.StringIO()
        t0 = time.perf_counter()
        timed_out = False
        try:
            with contextlib.redirect_stdout(buf), _time_limit(self.exec_timeout_s):
                exec(code, self.namespace)  # noqa: S102
            is_error = False
        except _ExecTimeout:
            # Recoverable by design: surfaced to the agent as a normal tool error so it can
            # rewrite the call vectorized and continue, rather than aborting the episode.
            buf.write("\n" + _TIMEOUT_MSG.format(t=self.exec_timeout_s))
            is_error = True
            timed_out = True
        except Exception:
            buf.write(traceback.format_exc())
            is_error = True
        finally:
            # Free any matplotlib figures the call created. pyplot keeps every figure
            # alive in its global registry until explicitly closed; across ~100 stateful
            # run_code calls on a large cohort that accumulation is a real memory leak
            # (a contributor to OOM kills on big cohorts like BRCA). Agents save figures
            # within the same call, so closing here is safe.
            plt.close("all")
        exec_time = time.perf_counter() - t0

        output = buf.getvalue()
        if is_error:
            output = f"Error:\n{output}"
        if len(output) > _MAX_OUTPUT_CHARS:
            output = output[:_MAX_OUTPUT_CHARS] + f"\n... [truncated — {len(output)} chars total]"
        output = output if output else "(no output)"

        self.timing_log.append({
            "call_num": self._exec_count,
            "exec_time_s": round(exec_time, 4),
            "output_chars": len(output),
            "is_error": is_error,
            "timed_out": timed_out,
        })
        self._exec_count += 1
        return output

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _build_namespace(self, data_dir: Path) -> dict:
        """
        Seed the execution namespace with episode data + standard imports.
        expression and metadata are the only data pre-loaded — everything
        else is accessed by the agent via file reads.
        """
        episode_dir = data_dir / "episode"
        expression = None
        metadata = None

        expr_path = episode_dir / "expression.parquet"
        if expr_path.exists():
            expression = pd.read_parquet(expr_path)

        meta_path = episode_dir / "metadata.tsv"
        if meta_path.exists():
            metadata = pd.read_csv(meta_path, sep="\t", index_col=0)

        mutation = None
        mut_path = episode_dir / "mutations.parquet"
        if mut_path.exists():
            mutation = pd.read_parquet(mut_path)

        methylation = None
        meth_path = episode_dir / "methylation.parquet"
        if meth_path.exists():
            methylation = pd.read_parquet(meth_path)

        cna = None
        cna_path = episode_dir / "cna.parquet"
        if cna_path.exists():
            cna = pd.read_parquet(cna_path)

        ns: dict = {
            # Episode data
            "expression":  expression,
            "metadata":    metadata,
            "mutation":    mutation,     # samples × genes binary matrix (or None)
            "methylation": methylation,  # samples × CpGs beta values (or None)
            "cna":         cna,          # samples × genes int8 CNA calls +1/0/-1 (or None)
            # Output directory — save all plots/tables here
            "output_dir": self.output_dir,
            # Standard scientific imports available without extra import
            "pd": pd,
            "np": np,
            "plt": plt,
            "matplotlib": matplotlib,
            # Multi-modal integrative clustering tool (MOFA+ / SNF / concat_pca)
            "multimodal_cluster": multimodal_cluster,
            # builtins available implicitly via exec — no need to re-add
        }
        return ns

    def _check_blocked_paths(self, code: str) -> str | None:
        """Return the first blocked substring found in code, or None."""
        for blocked in self._blocked:
            if blocked in code:
                return blocked
        return None
