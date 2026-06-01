"""
multimodal_cluster() — pre-loaded into the agent run_code namespace.

Wraps three multi-modal integrative clustering methods:

  mofa       — MOFA+ latent factor model (requires mofapy2; falls back to
               concat_pca if not installed)
  snf        — Similarity Network Fusion, built-in pure-numpy implementation
               (no extra dependencies)
  concat_pca — PCA per modality + concatenate top PCs (ad-hoc baseline)

Usage in run_code:
    result = multimodal_cluster(
        {"expression": expression, "methylation": methylation},
        k=3, method="mofa",
    )
    labels  = result["labels"]     # pd.Series, sample → "C0" / "C1" / ...
    factors = result["factors"]    # pd.DataFrame, samples × latent dims
    nmi     = result["nmi_vs_expr_only"]  # float
    print(result["method"])        # actual method used (may differ if fallback)
"""
from __future__ import annotations

import warnings
from typing import Any

import numpy as np
import pandas as pd
from sklearn.cluster import KMeans, SpectralClustering
from sklearn.decomposition import PCA
from sklearn.metrics import normalized_mutual_info_score
from sklearn.preprocessing import StandardScaler


def multimodal_cluster(
    modalities: dict[str, pd.DataFrame | None],
    k: int = 3,
    method: str = "mofa",
    n_factors: int = 10,
    seed: int = 42,
    max_iter: int = 500,
    verbose: bool = False,
) -> dict[str, Any]:
    """
    Multi-modal integrative clustering.

    Parameters
    ----------
    modalities : dict[str, DataFrame | None]
        Named data matrices, each samples × features with a shared sample index.
        None values are silently skipped.
        E.g. {"expression": expression, "methylation": methylation, "rppa": rppa}
    k : int
        Number of clusters.
    method : str
        "mofa"       — MOFA+ variational inference via mofapy2.  Falls back to
                       concat_pca if mofapy2 is not installed.
        "snf"        — Similarity Network Fusion (built-in, no extra deps).
                       Spectral clustering on the fused affinity matrix; returns
                       spectral embedding as factors.
        "concat_pca" — StandardScaler + PCA per modality, concatenate top
                       n_factors PCs per view, k-means.  Equivalent to the
                       ad-hoc approach agents write manually.
    n_factors : int
        MOFA: number of latent factors.
        concat_pca: PCs per modality before concatenation.
        SNF: ignored (spectral embedding dimension fixed to min(k+3, n-1)).
    seed : int
        Random seed for k-means / MOFA / spectral clustering.
    max_iter : int
        Maximum MOFA training iterations.
    verbose : bool
        Print MOFA training progress.

    Returns
    -------
    dict with keys
        "labels"           : pd.Series — sample → "C0", "C1", ...
        "method"           : str — method actually used (may differ if fallback)
        "factors"          : pd.DataFrame — samples × latent dims
                             (latent factors for mofa/concat_pca;
                              spectral embedding for snf)
        "nmi_vs_expr_only" : float — NMI between this partition and k-means on
                             expression alone (nan if expression not in modalities)
        "modalities_used"  : list[str] — view names actually included
    """
    if not modalities:
        raise ValueError("modalities dict is empty")

    # Drop None entries and intersect sample indices
    aligned = {name: df for name, df in modalities.items() if df is not None}
    if len(aligned) < 2:
        raise ValueError(f"Need at least 2 non-None modalities, got {len(aligned)}")

    common = None
    for df in aligned.values():
        common = set(df.index) if common is None else common & set(df.index)
    if not common:
        raise ValueError("No common samples across modalities")

    common = sorted(common)
    aligned = {name: df.loc[common].copy() for name, df in aligned.items()}

    # Expression-only baseline for NMI
    expr_km_labels = None
    if "expression" in aligned:
        expr_km_labels = _expr_only_kmeans(aligned["expression"], k=k, seed=seed)

    # Dispatch
    if method == "mofa":
        try:
            factors_arr, method_used = _run_mofa(
                aligned, n_factors=n_factors, seed=seed,
                max_iter=max_iter, verbose=verbose,
            )
        except ImportError:
            warnings.warn(
                "mofapy2 not installed — falling back to concat_pca. "
                "Install with: pip install mofapy2",
                stacklevel=2,
            )
            factors_arr, method_used = _run_concat_pca(aligned, n_factors=n_factors, seed=seed)
    elif method == "snf":
        factors_arr, method_used, raw_labels = _run_snf(aligned, k=k, seed=seed)
    elif method == "concat_pca":
        factors_arr, method_used = _run_concat_pca(aligned, n_factors=n_factors, seed=seed)
    else:
        raise ValueError(f"method must be 'mofa', 'snf', or 'concat_pca', got {method!r}")

    # Cluster (SNF already clustered internally)
    if method_used == "snf":
        raw_labels_final = raw_labels
    else:
        km = KMeans(n_clusters=k, random_state=seed, n_init=20)
        raw_labels_final = km.fit_predict(factors_arr)

    labels = pd.Series(
        [f"C{l}" for l in raw_labels_final],
        index=common,
        name="multimodal_cluster",
    )

    factors_df = pd.DataFrame(
        factors_arr,
        index=common,
        columns=[f"F{i + 1}" for i in range(factors_arr.shape[1])],
    )

    nmi = (
        float(normalized_mutual_info_score(expr_km_labels, raw_labels_final))
        if expr_km_labels is not None
        else float("nan")
    )

    return {
        "labels": labels,
        "method": method_used,
        "factors": factors_df,
        "nmi_vs_expr_only": round(nmi, 4),
        "modalities_used": list(aligned.keys()),
    }


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _expr_only_kmeans(expr_df: pd.DataFrame, k: int, seed: int) -> np.ndarray:
    n_pc = min(30, expr_df.shape[1], expr_df.shape[0] - 1)
    X = StandardScaler().fit_transform(expr_df.fillna(0).values.astype(float))
    pcs = PCA(n_components=n_pc, random_state=seed).fit_transform(X)
    return KMeans(n_clusters=k, random_state=seed, n_init=10).fit_predict(pcs)


def _run_mofa(
    aligned: dict[str, pd.DataFrame],
    n_factors: int,
    seed: int,
    max_iter: int,
    verbose: bool,
) -> tuple[np.ndarray, str]:
    """MOFA+ via mofapy2. Raises ImportError if not installed."""
    from mofapy2.run.entry_point import entry_point  # guarded import

    samples = list(list(aligned.values())[0].index)

    data_dict: dict[str, list] = {}
    features_names: dict[str, list] = {}
    for name, df in aligned.items():
        arr = df.fillna(df.mean()).values.astype(float)
        data_dict[name] = [arr]  # list of groups (single group)
        features_names[name] = list(df.columns)

    ent = entry_point()
    ent.set_data_options(scale_groups=False, scale_views=True)
    ent.set_model_options(factors=n_factors)
    ent.set_train_options(
        seed=seed,
        verbose=verbose,
        maxiter=max_iter,
        convergence_mode="fast",
    )
    ent.set_data_dict(
        data=data_dict,
        samples_names=[samples],
        features_names=features_names,
    )
    ent.build()
    ent.run()

    Z = ent.model.nodes["Z"].getExpectations()["E"]  # samples × factors
    return np.array(Z), "mofa"


def _run_snf(
    aligned: dict[str, pd.DataFrame],
    k: int,
    seed: int,
    n_snf_iter: int = 20,
) -> tuple[np.ndarray, str, np.ndarray]:
    """
    Similarity Network Fusion (Wang et al. 2014).

    Pure numpy/scipy — no snfpy dependency.
    Returns (spectral_embedding, "snf", cluster_labels).
    """
    n = len(list(aligned.values())[0])
    K = max(5, min(int(np.sqrt(n)), n // 5))  # KNN parameter
    mu = 0.5  # bandwidth scaling

    def _full_affinity(X_scaled: np.ndarray) -> np.ndarray:
        dists = np.sum((X_scaled[:, None, :] - X_scaled[None, :, :]) ** 2, axis=2)
        np.fill_diagonal(dists, np.inf)
        knn_dists = np.sort(dists, axis=1)[:, :K]
        row_sigma = knn_dists.mean(axis=1)
        sigma = (row_sigma[:, None] + row_sigma[None, :]) / 2 + 1e-10
        np.fill_diagonal(dists, 0.0)
        W = np.exp(-dists / (mu * sigma))
        np.fill_diagonal(W, 0.0)
        row_sum = W.sum(axis=1, keepdims=True) + 1e-10
        return W / row_sum

    def _knn_affinity(W_full: np.ndarray) -> np.ndarray:
        """Keep only K nearest neighbors per row; row-normalize."""
        W_knn = np.zeros_like(W_full)
        for i in range(n):
            top_k = np.argpartition(W_full[i], -K)[-K:]
            W_knn[i, top_k] = W_full[i, top_k]
        row_sum = W_knn.sum(axis=1, keepdims=True) + 1e-10
        return W_knn / row_sum

    # Build per-modality full and KNN affinity matrices
    Ws, Ps = [], []
    for df in aligned.values():
        X = StandardScaler().fit_transform(df.fillna(df.mean()).values.astype(float))
        W = _full_affinity(X)
        Ws.append(W)
        Ps.append(_knn_affinity(W))

    m = len(Ps)

    # SNF diffusion iterations
    for _ in range(n_snf_iter):
        P_new = []
        for i in range(m):
            others = sum(Ps[j] for j in range(m) if j != i)
            Pt = Ws[i] @ (others / (m - 1)) @ Ws[i].T
            row_sum = Pt.sum(axis=1, keepdims=True) + 1e-10
            P_new.append(Pt / row_sum)
        Ps = P_new

    # Fused network: average of updated KNN affinities
    fused = sum(Ps) / m
    fused = (fused + fused.T) / 2  # symmetrize

    # Spectral clustering on fused affinity
    n_components = min(k + 3, n - 1)
    sc = SpectralClustering(
        n_clusters=k,
        affinity="precomputed",
        n_components=n_components,
        random_state=seed,
        n_init=10,
    )
    raw_labels = sc.fit_predict(fused)

    # Spectral embedding for visualization (eigenvectors of normalized Laplacian)
    d = fused.sum(axis=1)
    d_inv_sqrt = np.where(d > 0, d ** -0.5, 0.0)
    L_sym = (fused * d_inv_sqrt[:, None]) * d_inv_sqrt[None, :]
    _, vecs = np.linalg.eigh(L_sym)
    embed = vecs[:, -(n_components):][: , ::-1]  # top eigenvectors, descending

    return embed, "snf", raw_labels


def _run_concat_pca(
    aligned: dict[str, pd.DataFrame],
    n_factors: int,
    seed: int,
) -> tuple[np.ndarray, str]:
    """PCA per modality, concatenate, return stacked PCs."""
    pcs_list = []
    for df in aligned.values():
        n_pc = min(n_factors, df.shape[1], df.shape[0] - 1)
        X = StandardScaler().fit_transform(df.fillna(df.mean()).values.astype(float))
        pcs_list.append(PCA(n_components=n_pc, random_state=seed).fit_transform(X))
    return np.hstack(pcs_list), "concat_pca"
