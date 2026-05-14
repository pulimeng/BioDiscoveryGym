"""
TCGA DataLoader integration tests.

Validates that load_tcga() produces correctly shaped, well-formed matrices
and that DataAnonymizer strips leaky clinical columns before an agent sees data.

Requires: data/tcga/{brca,prad,ucec,luad}/ with expression.parquet cached.
Run after cache is built:
    pytest tests/test_tcga_loader.py -v
"""

import re
from pathlib import Path

import pandas as pd
import pytest

from biodiscoverygym.utils.data_loader import DataLoader
from biodiscoverygym.utils.hidden_context import DataAnonymizer

DATA_DIR = Path(__file__).parent.parent / "data"
TCGA_DIR = DATA_DIR / "tcga"

COHORTS = ["brca", "prad", "ucec", "luad"]

# Skip cohort if its parquet cache hasn't been built yet
def cohort_ready(cohort: str) -> bool:
    return (TCGA_DIR / cohort / "expression.parquet").exists()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def loader():
    return DataLoader()


@pytest.fixture(scope="module", params=COHORTS)
def cohort_dataset(request, loader):
    cohort = request.param
    if not cohort_ready(cohort):
        pytest.skip(f"Cache not built for {cohort} — run load_tcga() first")
    return cohort, loader.load_tcga(cohort.upper(), tcga_dir=TCGA_DIR / cohort)


# ---------------------------------------------------------------------------
# Expression matrix tests
# ---------------------------------------------------------------------------

def test_expression_shape(cohort_dataset):
    cohort, ds = cohort_dataset
    expr = ds["expression"]
    assert expr.ndim == 2, "Expression must be 2D"
    assert expr.shape[0] > 100, f"{cohort}: too few samples ({expr.shape[0]})"
    assert expr.shape[1] > 10_000, f"{cohort}: too few genes ({expr.shape[1]})"


def test_expression_values_log1p_range(cohort_dataset):
    cohort, ds = cohort_dataset
    expr = ds["expression"]
    mn, mx = float(expr.min().min()), float(expr.max().max())
    assert mn >= 0.0, f"{cohort}: negative expression values (min={mn:.3f})"
    assert mx < 20.0, f"{cohort}: suspiciously large max value ({mx:.3f}) — log1p applied?"


def test_expression_no_all_zero_genes(cohort_dataset):
    cohort, ds = cohort_dataset
    expr = ds["expression"]
    all_zero = (expr == 0).all(axis=0).sum()
    frac = all_zero / expr.shape[1]
    assert frac < 0.10, f"{cohort}: {frac:.1%} of genes are all-zero (expected <10%)"


def test_expression_no_duplicate_genes(cohort_dataset):
    cohort, ds = cohort_dataset
    cols = ds["expression"].columns
    dupes = cols[cols.duplicated()].tolist()
    assert dupes == [], f"{cohort}: duplicate gene columns: {dupes[:10]}"


def test_expression_no_ensembl_ids_in_columns(cohort_dataset):
    cohort, ds = cohort_dataset
    ensembl_pattern = re.compile(r"^ENSG\d+")
    ensembl_cols = [c for c in ds["expression"].columns if ensembl_pattern.match(str(c))]
    assert ensembl_cols == [], f"{cohort}: Ensembl IDs in columns (expected gene symbols): {ensembl_cols[:5]}"


def test_sample_ids_look_like_tcga(cohort_dataset):
    cohort, ds = cohort_dataset
    tcga_pattern = re.compile(r"^TCGA-[A-Z0-9]{2}-[A-Z0-9]{4}")
    bad = [s for s in ds["expression"].index if not tcga_pattern.match(str(s))]
    assert bad == [], f"{cohort}: non-TCGA sample IDs: {bad[:5]}"


# ---------------------------------------------------------------------------
# Metadata tests
# ---------------------------------------------------------------------------

def test_metadata_aligned_to_expression(cohort_dataset):
    cohort, ds = cohort_dataset
    expr_idx = set(ds["expression"].index)
    meta_idx = set(ds["metadata"].index)
    assert expr_idx == meta_idx, (
        f"{cohort}: expression and metadata indices differ. "
        f"Only in expr: {list(expr_idx - meta_idx)[:3]}, "
        f"only in meta: {list(meta_idx - expr_idx)[:3]}"
    )


def test_metadata_has_expected_columns(cohort_dataset):
    cohort, ds = cohort_dataset
    expected = {"gender", "primary_diagnosis", "vital_status", "age_at_diagnosis"}
    actual = set(ds["metadata"].columns)
    missing = expected - actual
    assert not missing, f"{cohort}: metadata missing expected columns: {missing}"


# ---------------------------------------------------------------------------
# DataAnonymizer tests
# ---------------------------------------------------------------------------

def test_anonymizer_strips_leaky_columns(cohort_dataset):
    cohort, ds = cohort_dataset
    anon = DataAnonymizer.mask(ds)
    # Cancer-type-revealing columns must be stripped
    for col in ("primary_diagnosis", "morphology"):
        assert col not in anon["metadata"].columns, \
            f"{cohort}: cancer-type column '{col}' not stripped by DataAnonymizer"
    # Prognostic columns must be kept (used as phenotype anchor)
    for col in ("vital_status", "days_to_death", "days_to_last_follow_up", "tumor_stage"):
        if col in ds["metadata"].columns:
            assert col in anon["metadata"].columns, \
                f"{cohort}: prognostic column '{col}' was incorrectly stripped"


def test_anonymizer_preserves_expression_shape(cohort_dataset):
    cohort, ds = cohort_dataset
    anon = DataAnonymizer.mask(ds)
    assert anon["expression"].shape == ds["expression"].shape, \
        f"{cohort}: expression shape changed after anonymization"
