"""
multimodal_cluster() — pre-loaded into the agent run_code namespace.

Methods:
  mofa       — MOFA+ latent factor model via mofapy2 (recommended; falls back to snf)
  snf        — Similarity Network Fusion, pure-numpy (no extra dependencies)
  concat_pca — PCA per modality + concatenated top PCs (fast baseline)

Usage:
    result = multimodal_cluster(
        {"expression": expression, "methylation": methylation},
        k=3, method="mofa",
    )
    labels  = result["labels"]            # pd.Series, sample → "C0" / "C1" / ...
    factors = result["factors"]           # pd.DataFrame, samples × latent dims
    nmi     = result["nmi_vs_expr_only"]  # float
    print(result["method"])               # actual method used (may differ if fallback)
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
    k : int
        Number of clusters.
    method : str
        "mofa"       — MOFA+ variational inference via mofapy2. Falls back to snf on failure.
        "snf"        — Similarity Network Fusion (built-in). Spectral clustering on fused
                       affinity matrix; returns spectral embedding as factors.
        "concat_pca" — PCA per modality, concatenate top n_factors PCs, k-means.
    n_factors : int
        MOFA/concat_pca: latent dims / PCs per view. SNF: ignored.
    seed : int
        Random seed.
    max_iter : int
        MOFA training iterations.
    verbose : bool
        MOFA training progress.

    Returns
    -------
    dict:
        "labels"           — pd.Series, sample → "C0", "C1", ...
        "method"           — str, method actually used
        "factors"          — pd.DataFrame, samples × latent dims
        "nmi_vs_expr_only" — float, NMI vs expression-only k-means (nan if no expression)
        "modalities_used"  — list[str]
    """
    if not modalities:
        raise ValueError("modalities dict is empty")

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

    expr_km_labels = None
    if "expression" in aligned:
        expr_km_labels = _expr_only_kmeans(aligned["expression"], k=k, seed=seed)

    if method == "mofa":
        try:
            factors_arr, method_used = _run_mofa(
                aligned, n_factors=n_factors, seed=seed,
                max_iter=max_iter, verbose=verbose,
            )
        except Exception as e:
            warnings.warn(f"MOFA+ failed ({e!r}) — falling back to snf.", stacklevel=2)
            factors_arr, method_used, raw_labels = _run_snf(aligned, k=k, seed=seed)
    elif method == "snf":
        factors_arr, method_used, raw_labels = _run_snf(aligned, k=k, seed=seed)
    elif method == "concat_pca":
        factors_arr, method_used = _run_concat_pca(aligned, n_factors=n_factors, seed=seed)
    else:
        raise ValueError(f"method must be 'mofa', 'snf', or 'concat_pca', got {method!r}")

    if method_used == "snf":
        raw_labels_final = raw_labels
    else:
        raw_labels_final = KMeans(n_clusters=k, random_state=seed, n_init=20).fit_predict(factors_arr)

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
        if expr_km_labels is not None else float("nan")
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
    import io, sys
    from mofapy2.run.entry_point import entry_point

    samples = list(list(aligned.values())[0].index)
    view_names = list(aligned.keys())

    data_list: list[list[np.ndarray]] = []
    features_names: list[list] = []
    for name in view_names:
        df = aligned[name]
        data_list.append([df.fillna(df.mean()).values.astype(float)])
        features_names.append([f"{name}::{c}" for c in df.columns])

    if not verbose:
        _real, sys.stdout = sys.stdout, io.StringIO()
    try:
        ent = entry_point()
        ent.set_data_options(scale_groups=False, scale_views=True)
        ent.set_data_matrix(
            data=data_list,
            likelihoods=["gaussian"] * len(view_names),
            views_names=view_names,
            groups_names=["group0"],
            samples_names=[samples],
            features_names=features_names,
        )
        ent.set_model_options(factors=n_factors)
        ent.set_train_options(seed=seed, verbose=verbose, iter=max_iter, convergence_mode="fast")
        ent.build()
        ent.run()
    finally:
        if not verbose:
            sys.stdout = _real

    Z = ent.model.nodes["Z"].getExpectations()["E"]
    return np.array(Z), "mofa"


def _run_snf(
    aligned: dict[str, pd.DataFrame],
    k: int,
    seed: int,
    n_snf_iter: int = 20,
) -> tuple[np.ndarray, str, np.ndarray]:
    n = len(list(aligned.values())[0])
    K = max(5, min(int(np.sqrt(n)), n // 5))
    mu = 0.5

    def _full_affinity(X_scaled: np.ndarray) -> np.ndarray:
        # Pairwise squared Euclidean distances via ‖a-b‖² = ‖a‖² + ‖b‖² - 2·a·b.
        # The naive broadcasting form X[:,None,:]-X[None,:,:] materializes an (n,n,d)
        # tensor first — for d≈20k features that's ~190 GB and OOM-kills the process
        # (observed on BRCA, 1095×19938). This form only builds n×n matrices (and the
        # n×n Gram matrix), and is numerically identical.
        sq = np.einsum("ij,ij->i", X_scaled, X_scaled)
        dists = sq[:, None] + sq[None, :] - 2.0 * (X_scaled @ X_scaled.T)
        np.maximum(dists, 0.0, out=dists)  # clip tiny negatives from float round-off
        np.fill_diagonal(dists, np.inf)
        row_sigma = np.sort(dists, axis=1)[:, :K].mean(axis=1)
        sigma = (row_sigma[:, None] + row_sigma[None, :]) / 2 + 1e-10
        np.fill_diagonal(dists, 0.0)
        W = np.exp(-dists / (mu * sigma))
        np.fill_diagonal(W, 0.0)
        return W / (W.sum(axis=1, keepdims=True) + 1e-10)

    def _knn_affinity(W_full: np.ndarray) -> np.ndarray:
        W_knn = np.zeros_like(W_full)
        for i in range(n):
            top_k = np.argpartition(W_full[i], -K)[-K:]
            W_knn[i, top_k] = W_full[i, top_k]
        return W_knn / (W_knn.sum(axis=1, keepdims=True) + 1e-10)

    Ws, Ps = [], []
    for df in aligned.values():
        X = StandardScaler().fit_transform(df.fillna(df.mean()).values.astype(float))
        W = _full_affinity(X)
        Ws.append(W)
        Ps.append(_knn_affinity(W))

    m = len(Ps)
    for _ in range(n_snf_iter):
        P_new = []
        for i in range(m):
            others = sum(Ps[j] for j in range(m) if j != i)
            Pt = Ws[i] @ (others / (m - 1)) @ Ws[i].T
            P_new.append(Pt / (Pt.sum(axis=1, keepdims=True) + 1e-10))
        Ps = P_new

    fused = sum(Ps) / m
    fused = (fused + fused.T) / 2

    n_components = min(k + 3, n - 1)
    raw_labels = SpectralClustering(
        n_clusters=k, affinity="precomputed", n_components=n_components,
        random_state=seed, n_init=10,
    ).fit_predict(fused)

    d = fused.sum(axis=1)
    d_inv_sqrt = np.where(d > 0, d ** -0.5, 0.0)
    L_sym = (fused * d_inv_sqrt[:, None]) * d_inv_sqrt[None, :]
    _, vecs = np.linalg.eigh(L_sym)
    embed = vecs[:, -n_components:][:, ::-1]

    return embed, "snf", raw_labels


def _run_concat_pca(
    aligned: dict[str, pd.DataFrame],
    n_factors: int,
    seed: int,
) -> tuple[np.ndarray, str]:
    pcs_list = []
    for df in aligned.values():
        n_pc = min(n_factors, df.shape[1], df.shape[0] - 1)
        X = StandardScaler().fit_transform(df.fillna(df.mean()).values.astype(float))
        pcs_list.append(PCA(n_components=n_pc, random_state=seed).fit_transform(X))
    return np.hstack(pcs_list), "concat_pca"
