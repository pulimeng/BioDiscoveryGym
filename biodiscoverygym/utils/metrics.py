"""
Shared evaluation metrics (Phase 1 will fill these out fully).
"""

from __future__ import annotations

import numpy as np


def compute_auroc(y_true, y_score) -> float:
    from sklearn.metrics import roc_auc_score
    return float(roc_auc_score(y_true, y_score))


def compute_ari(labels_true, labels_pred) -> float:
    from sklearn.metrics import adjusted_rand_score
    return float(adjusted_rand_score(labels_true, labels_pred))


def compute_nmi(labels_true, labels_pred) -> float:
    from sklearn.metrics import normalized_mutual_info_score
    return float(normalized_mutual_info_score(labels_true, labels_pred))


def cohens_d(group_a: np.ndarray, group_b: np.ndarray) -> float:
    """Effect size between two groups."""
    pooled_std = np.sqrt((group_a.std() ** 2 + group_b.std() ** 2) / 2)
    if pooled_std == 0:
        return 0.0
    return float((group_a.mean() - group_b.mean()) / pooled_std)
