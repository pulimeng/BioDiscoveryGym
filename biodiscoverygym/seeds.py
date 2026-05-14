"""
Fixed random seed management.

All stochastic operations in the benchmark must call set_global_seed(seed)
at episode start so that results are reproducible across runs and agents.
"""

import random
import numpy as np

_CANONICAL_SEEDS = [42, 1337, 2024, 7, 99]


def set_global_seed(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed)
    try:
        import torch
        torch.manual_seed(seed)
        torch.backends.cudnn.deterministic = True
    except ImportError:
        pass


def get_canonical_seeds() -> list[int]:
    return list(_CANONICAL_SEEDS)


def episode_seed(base_seed: int, episode_idx: int) -> int:
    """Derive a per-episode seed that is deterministic from base + index."""
    return (base_seed * 1000003 + episode_idx) % (2**31)
