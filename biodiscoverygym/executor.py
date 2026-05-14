"""
CodeExecutor: stateful Python execution environment for BioDiscoveryGym agents.

- Maintains a persistent namespace across calls (variables survive between run_code invocations)
- Pre-loads expression + metadata from data/episode/ on construction
- Captures stdout and returns it as a string
- Blocks access to data/sealed/ and vault paths (trusted-agent level enforcement)
- Network access blocking is handled externally by sandbox.py
"""

from __future__ import annotations

import contextlib
import io
import traceback
from pathlib import Path

import matplotlib
matplotlib.use("Agg")  # non-interactive backend — must be set before any other matplotlib import
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


# Paths the agent must not be able to read.
# data/ is blocked entirely for TargetDiscoveryExecutor sessions: all datasets are
# pre-loaded and anonymized in the namespace — raw files contain real gene symbols.
# results/ and _evaluation block dynamic path traversal to gene maps from prior sessions.
_BLOCKED_SUBSTRINGS = (
    "data/sealed",
    ".biodiscoverygym/vault",
    "episode_key",
    "data/depmap",
    "data/gtex",
    "data/gnomad",
    "data/tcga",
    "data/hpa",
    "data/cosmic",
    "data/ccle_proteomics",
    "data/prism",
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


class CodeExecutor:
    """
    Stateful Python sandbox.

    Usage:
        executor = CodeExecutor(data_dir="data")
        out = executor.execute("print(expression.shape)")
        # → "(1095, 19938)\\n"
    """

    def __init__(self, data_dir: str | Path = "data", output_dir: str | Path | None = None):
        data_dir = Path(data_dir)
        self.output_dir = Path(output_dir) if output_dir else Path("results") / "misc"
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self._blocked: list[str] = list(_BLOCKED_SUBSTRINGS)
        self.namespace: dict = self._build_namespace(data_dir)

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
            return f"PermissionError: access to '{violation}' is not permitted during an episode."

        buf = io.StringIO()
        try:
            with contextlib.redirect_stdout(buf):
                exec(code, self.namespace)  # noqa: S102
        except Exception:
            tb = traceback.format_exc()
            return f"Error:\n{tb}"

        output = buf.getvalue()
        if len(output) > _MAX_OUTPUT_CHARS:
            output = output[:_MAX_OUTPUT_CHARS] + f"\n... [truncated — {len(output)} chars total]"
        return output if output else "(no output)"

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

        rppa = None
        rppa_path = episode_dir / "rppa.parquet"
        if rppa_path.exists():
            rppa = pd.read_parquet(rppa_path)

        ns: dict = {
            # Episode data
            "expression": expression,
            "metadata":   metadata,
            "mutation":   mutation,   # samples × genes binary matrix (or None)
            "rppa":       rppa,       # samples × proteins (or None)
            # Output directory — save all plots/tables here
            "output_dir": self.output_dir,
            # Standard scientific imports available without extra import
            "pd": pd,
            "np": np,
            "plt": plt,
            "matplotlib": matplotlib,
            # builtins available implicitly via exec — no need to re-add
        }
        return ns

    def _check_blocked_paths(self, code: str) -> str | None:
        """Return the first blocked substring found in code, or None."""
        for blocked in self._blocked:
            if blocked in code:
                return blocked
        return None
