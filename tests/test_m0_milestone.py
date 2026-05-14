"""
M0 milestone — validates the Phase 0 infrastructure using only synthetic data.
No real LLM or TCGA data required.

Tests:
  1. DataLoader.load_synthetic() — shape, labels
  2. DataAnonymizer.mask() — strips leaky columns
  3. Episode._anonymize_sample_ids() — SAMPLE_XXXX remapping
  4. CodeExecutor — pre-load, execution, stateful namespace, path blocking
  5. DiscoveryPackage — from_dict, remap_sample_ids
  6. Evaluator.score() — returns EpisodeResult with all stage keys
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd

from biodiscoverygym.utils.data_loader import DataLoader
from biodiscoverygym.utils.hidden_context import DataAnonymizer
from biodiscoverygym.episode import Episode, DiscoveryPackage
from biodiscoverygym.evaluator import Evaluator, EpisodeResult
from biodiscoverygym.executor import CodeExecutor


# ------------------------------------------------------------------
# 1. DataLoader
# ------------------------------------------------------------------

def test_load_synthetic_shape():
    loader = DataLoader()
    dataset, hidden_labels = loader.load_synthetic(n_samples=100, n_genes=200, seed=42)
    assert dataset["expression"].shape == (100, 200)
    assert dataset["metadata"].shape[0] == 100
    assert len(hidden_labels) == 100


def test_load_synthetic_labels():
    loader = DataLoader()
    _, hidden_labels = loader.load_synthetic(n_samples=100, n_context_groups=2, seed=42)
    label_set = set(hidden_labels.values())
    assert label_set == {"Context_A", "Context_B"}


# ------------------------------------------------------------------
# 2. DataAnonymizer
# ------------------------------------------------------------------

def test_anonymizer_strips_leaky_column():
    loader = DataLoader()
    dataset, _ = loader.load_synthetic(n_samples=100, n_genes=200, seed=42)
    assert "tissue_type" in dataset["metadata"].columns
    anon = DataAnonymizer.mask(dataset)
    assert "tissue_type" not in anon["metadata"].columns


def test_anonymizer_preserves_expression():
    loader = DataLoader()
    dataset, _ = loader.load_synthetic(n_samples=50, n_genes=100, seed=1)
    anon = DataAnonymizer.mask(dataset)
    assert anon["expression"].shape == dataset["expression"].shape


# ------------------------------------------------------------------
# 3. Episode._anonymize_sample_ids
# ------------------------------------------------------------------

def test_anonymize_sample_ids_format():
    loader = DataLoader()
    dataset, _ = loader.load_synthetic(n_samples=50, n_genes=20, seed=7)
    anon_dataset, sample_id_map = Episode._anonymize_sample_ids(dataset, seed=7)
    ids = list(anon_dataset["expression"].index)
    assert all(i.startswith("SAMPLE_") for i in ids), f"Unexpected IDs: {ids[:5]}"
    assert len(ids) == 50


def test_anonymize_sample_ids_invertible():
    loader = DataLoader()
    dataset, _ = loader.load_synthetic(n_samples=30, n_genes=50, seed=0)
    original_ids = set(dataset["expression"].index)
    anon_dataset, sample_id_map = Episode._anonymize_sample_ids(dataset, seed=0)
    remapped = set(sample_id_map.values())
    assert remapped == original_ids


def test_anonymize_renames_metadata_index():
    loader = DataLoader()
    dataset, _ = loader.load_synthetic(n_samples=20, n_genes=50, seed=3)
    anon_dataset, sample_id_map = Episode._anonymize_sample_ids(dataset, seed=3)
    meta_ids = set(anon_dataset["metadata"].index)
    expr_ids = set(anon_dataset["expression"].index)
    assert meta_ids == expr_ids


# ------------------------------------------------------------------
# 4. CodeExecutor
# ------------------------------------------------------------------

def test_executor_no_data_dir(tmp_path):
    """Executor initialises without error even if episode data doesn't exist."""
    ex = CodeExecutor(data_dir=tmp_path)
    assert ex.namespace["expression"] is None
    assert ex.namespace["metadata"] is None


def test_executor_with_data(tmp_path):
    episode_dir = tmp_path / "episode"
    episode_dir.mkdir()
    df = pd.DataFrame({"GENE1": [1.0, 2.0], "GENE2": [3.0, 4.0]},
                      index=["SAMPLE_0000", "SAMPLE_0001"])
    df.to_parquet(episode_dir / "expression.parquet")
    meta = pd.DataFrame({"age": [40, 55]}, index=["SAMPLE_0000", "SAMPLE_0001"])
    meta.to_csv(episode_dir / "metadata.tsv", sep="\t")

    ex = CodeExecutor(data_dir=tmp_path)
    assert ex.namespace["expression"].shape == (2, 2)
    assert ex.namespace["metadata"].shape == (2, 1)


def test_executor_stateful():
    ex = CodeExecutor(data_dir="/nonexistent")
    ex.execute("x = 99")
    out = ex.execute("print(x + 1)")
    assert out.strip() == "100"


def test_executor_captures_stdout():
    ex = CodeExecutor(data_dir="/nonexistent")
    out = ex.execute("print('hello world')")
    assert "hello world" in out


def test_executor_captures_error():
    ex = CodeExecutor(data_dir="/nonexistent")
    out = ex.execute("1 / 0")
    assert "Error" in out
    assert "ZeroDivisionError" in out


def test_executor_blocks_sealed_path():
    ex = CodeExecutor(data_dir="/nonexistent")
    out = ex.execute("open('data/sealed/brca/public_labels.json')")
    assert "PermissionError" in out


def test_executor_blocks_vault_path():
    ex = CodeExecutor(data_dir="/nonexistent")
    out = ex.execute("f = open('.biodiscoverygym/vault/abc/episode_key.json')")
    assert "PermissionError" in out


def test_executor_no_output():
    ex = CodeExecutor(data_dir="/nonexistent")
    out = ex.execute("x = 42")
    assert out == "(no output)"


def test_executor_numpy_available():
    ex = CodeExecutor(data_dir="/nonexistent")
    out = ex.execute("print(np.zeros(3))")
    assert "0." in out


def test_executor_pandas_available():
    ex = CodeExecutor(data_dir="/nonexistent")
    out = ex.execute("print(pd.Series([1, 2, 3]).sum())")
    assert "6" in out


# ------------------------------------------------------------------
# 5. DiscoveryPackage
# ------------------------------------------------------------------

def test_discovery_package_from_dict():
    d = {
        "proposed_grouping": {"SAMPLE_0001": "Subtype_A", "SAMPLE_0002": "Subtype_B"},
        "top_genes": ["CDH1", "ESR1"],
        "pathway_evidence": ["Estrogen response"],
        "mechanism_hypothesis": "Test hypothesis",
        "confidence": "high",
        "next_experiment": "CRISPR KO of CDH1",
    }
    pkg = DiscoveryPackage.from_dict(d)
    assert pkg.confidence == "high"
    assert "CDH1" in pkg.top_genes
    assert pkg.proposed_grouping["SAMPLE_0001"] == "Subtype_A"


def test_discovery_package_missing_fields():
    """from_dict is tolerant — missing fields default to empty."""
    pkg = DiscoveryPackage.from_dict({})
    assert pkg.proposed_grouping == {}
    assert pkg.top_genes == []
    assert pkg.confidence == "low"


# ------------------------------------------------------------------
# 6. Evaluator
# ------------------------------------------------------------------

def test_evaluator_returns_result():
    evaluator = Evaluator()
    pkg = DiscoveryPackage.from_dict({
        "proposed_grouping": {"TCGA-BH-A001": "Subtype_A", "TCGA-BH-A002": "Subtype_B"},
        "top_genes": ["CDH1"],
        "pathway_evidence": ["Estrogen response"],
        "mechanism_hypothesis": "hypothesis",
        "confidence": "medium",
        "next_experiment": "experiment",
    })
    result = evaluator.score(pkg, wall_time_s=5.0)
    assert isinstance(result, EpisodeResult)
    assert result.wall_time_s == 5.0
    assert result.total_score >= 0.0


def test_evaluator_has_all_components():
    evaluator = Evaluator()
    pkg = DiscoveryPackage.from_dict({"proposed_grouping": {}})
    result = evaluator.score(pkg)
    expected = {
        "subtype_recovery", "survival_separation", "marker_discriminability",
        "grouping_coverage", "submission_quality",
    }
    assert expected == set(result.scores.keys())


def test_evaluator_normalized_score_range():
    evaluator = Evaluator()
    pkg = DiscoveryPackage.from_dict({})
    result = evaluator.score(pkg)
    assert 0.0 <= result.normalized_score <= 1.0


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
