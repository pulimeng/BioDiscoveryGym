"""
Prize-Collecting Steiner Tree (PCST) for mechanistic gene network analysis.

Given a set of prize genes (e.g. cluster marker genes ranked by differential
expression) and a PPI network, finds the minimal connected subgraph that
connects the highest-prize genes through biologically meaningful paths.

Intermediate nodes not in the prize set (Steiner nodes) are structurally
necessary connectors — often the most mechanistically interesting genes.

Algorithm: node-weighted Steiner tree approximation (Kou-Markowsky-Berman)
via networkx. Equivalent to PCST with hard terminal selection by prize rank.

Reference: Kou, Markowsky & Berman (1981) Acta Informatica 15:141–145.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

_KG_GENE_GENE = Path("data/networks/primekg_gene_gene.parquet")


@dataclass
class SteinerResult:
    """Result of a PCST/Steiner tree run."""
    terminal_genes: list[str]          # prize genes used as terminals
    steiner_nodes: list[str]           # intermediate connector genes (Steiner nodes)
    edges: list[tuple[str, str, str]]  # (gene_a, gene_b, relation)
    prize_scores: dict[str, float]     # gene → KW H-stat (prize)
    n_terminals: int = 0
    n_steiner: int = 0
    coverage: float = 0.0             # fraction of terminals connected

    def __post_init__(self):
        self.n_terminals = len(self.terminal_genes)
        self.n_steiner = len(self.steiner_nodes)

    def summary(self) -> str:
        lines = [
            f"Steiner tree: {self.n_terminals} terminals + {self.n_steiner} Steiner nodes",
            f"Edges: {len(self.edges)}",
            f"Terminal coverage: {self.coverage:.0%}",
            "",
            "Terminal genes (by prize score):",
        ]
        for g in sorted(self.terminal_genes, key=lambda x: -self.prize_scores.get(x, 0)):
            lines.append(f"  {g:20s}  prize={self.prize_scores.get(g, 0):.2f}")
        if self.steiner_nodes:
            lines.append("\nSteiner nodes (connectors not in prize set):")
            for g in self.steiner_nodes:
                lines.append(f"  {g}")
        lines.append("\nEdges:")
        for a, b, rel in self.edges:
            lines.append(f"  {a} — {b}  [{rel}]")
        return "\n".join(lines)


def compute_prizes(
    expression: pd.DataFrame,
    labels: pd.Series,
) -> pd.Series:
    """
    Compute per-gene prize scores using Kruskal-Wallis H-statistic.
    Higher = more differentially expressed across clusters.
    """
    from scipy.stats import kruskal

    scores = {}
    cluster_vals = {c: expression.loc[labels == c] for c in labels.unique()}

    for gene in expression.columns:
        groups = [v[gene].dropna().values for v in cluster_vals.values()]
        groups = [g for g in groups if len(g) >= 3]
        if len(groups) < 2:
            scores[gene] = 0.0
            continue
        try:
            h, _ = kruskal(*groups)
            scores[gene] = float(h)
        except Exception:
            scores[gene] = 0.0

    return pd.Series(scores).sort_values(ascending=False)


def run_pcst(
    expression: pd.DataFrame,
    labels: pd.Series,
    n_terminals: int = 20,
    kg_path: str | Path = _KG_GENE_GENE,
    degree_penalty: bool = True,
) -> Optional[SteinerResult]:
    """
    Run Prize-Collecting Steiner Tree on PrimeKG gene-gene network.

    Parameters
    ----------
    expression : samples × genes DataFrame (real gene symbols)
    labels     : Series of cluster assignments (same index as expression)
    n_terminals: number of top prize genes to use as Steiner terminals
    kg_path    : path to primekg_gene_gene.parquet
    degree_penalty: if True, edge costs penalize high-degree hub genes
                   (avoids routing everything through TP53/EGFR)

    Returns
    -------
    SteinerResult, or None if the network has no coverage of prize genes
    """
    import networkx as nx
    from networkx.algorithms.approximation import steiner_tree

    kg_path = Path(kg_path)
    if not kg_path.exists():
        raise FileNotFoundError(
            f"PrimeKG gene-gene network not found at {kg_path}. "
            f"Run: python scripts/download_primekg.py"
        )

    # 1. Compute prizes
    prize_scores = compute_prizes(expression, labels)

    # 2. Load PPI network
    gg = pd.read_parquet(kg_path)
    genes_in_kg = set(gg["x_name"]) | set(gg["y_name"])

    # 3. Select terminals: top prize genes that exist in PrimeKG
    top_genes = [g for g in prize_scores.index if g in genes_in_kg]
    if len(top_genes) < 2:
        return None
    terminals = top_genes[:n_terminals]

    # 4. Build networkx graph
    G = nx.Graph()
    for _, row in gg.iterrows():
        G.add_edge(row["x_name"], row["y_name"], relation=row["display_relation"])

    # Degree-penalized edge weights: cheaper to traverse low-degree nodes
    # Prevents routing through EGFR/TP53/etc. that connect to everything
    if degree_penalty:
        for u, v in G.edges():
            deg_u = G.degree(u)
            deg_v = G.degree(v)
            # Cost inversely proportional to specificity (lower degree = more specific)
            G[u][v]["weight"] = (deg_u + deg_v) / 2.0
    else:
        for u, v in G.edges():
            G[u][v]["weight"] = 1.0

    # 5. Filter terminals to those reachable in the graph
    reachable = [t for t in terminals if t in G.nodes]
    if len(reachable) < 2:
        return None

    # 6. Run Steiner tree approximation
    try:
        tree = steiner_tree(G, reachable, weight="weight")
    except Exception:
        return None

    # 7. Parse result
    tree_nodes = set(tree.nodes)
    terminal_set = set(reachable)
    steiner_nodes = sorted(tree_nodes - terminal_set)
    terminal_genes = sorted(terminal_set & tree_nodes)

    edges = [
        (u, v, G[u][v].get("relation", "interacts"))
        for u, v in tree.edges()
    ]

    coverage = len(terminal_genes) / len(terminals) if terminals else 0.0

    return SteinerResult(
        terminal_genes=terminal_genes,
        steiner_nodes=steiner_nodes,
        edges=edges,
        prize_scores={g: float(prize_scores.get(g, 0)) for g in terminal_genes + steiner_nodes},
        coverage=coverage,
    )
