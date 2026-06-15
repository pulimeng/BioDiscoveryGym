"""
OS discovery-specific scoring components.

These components are NOT shared with the TCGA faithfulness scorer — they encode
discovery-rubric semantics (survival as primary outcome, per-gene provenance
audit, cross-modal support check, TARGET-OS external validation).

All functions return (raw_score: float in [0,1], diagnostics: dict). Defensive —
missing data returns 0.0 with reason, never raises.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

# Minimum gene count for TARGET co-expression matrix to be meaningful
_MIN_TARGET_GENES = 4


# ──────────────────────────────────────────────────────────────────────────────
# Internal helpers — survival, DE, modality lookups
# ──────────────────────────────────────────────────────────────────────────────

def _build_survival_df(metadata: pd.DataFrame) -> pd.DataFrame:
    """Extract duration + event from metadata. Returns DataFrame indexed by sample
    with columns ['duration', 'event']. Excludes rows with missing/invalid data."""
    rows = []
    for sample_id, row in metadata.iterrows():
        vs = str(row.get("vital_status", "")).lower()
        event = 1 if ("dead" in vs or "deceased" in vs) else 0
        days = row.get("days_to_death") if event else row.get("days_to_last_follow_up")
        try:
            days = float(days)
        except (TypeError, ValueError):
            continue
        if days <= 0 or days != days:
            continue
        rows.append({"sample_id": sample_id, "duration": days, "event": event})
    if not rows:
        return pd.DataFrame(columns=["duration", "event"])
    return pd.DataFrame(rows).set_index("sample_id")


def _gene_de_anova(
    gene: str,
    expression: pd.DataFrame,
    grouping: dict[str, str],
) -> float | None:
    """One-way ANOVA across groups for a single gene. Returns p-value or None."""
    try:
        from scipy.stats import f_oneway
        if gene not in expression.columns:
            return None
        groups = pd.Series(grouping)
        common = expression.index.intersection(groups.index)
        if len(common) < 10:
            return None
        x = expression.loc[common, gene]
        labels = groups.loc[common]
        per_group = [x[labels == g].values for g in labels.unique()]
        per_group = [arr for arr in per_group if len(arr) >= 3]
        if len(per_group) < 2:
            return None
        _, p = f_oneway(*per_group)
        return float(p) if p == p else None
    except Exception:
        return None


def _gene_survival_pvalue(
    gene: str,
    expression: pd.DataFrame,
    surv_df: pd.DataFrame,
) -> float | None:
    """Spearman correlation of gene expression with OS time. Returns p-value."""
    try:
        from scipy.stats import spearmanr
        if gene not in expression.columns:
            return None
        common = expression.index.intersection(surv_df.index)
        if len(common) < 10:
            return None
        x = expression.loc[common, gene].values
        t = surv_df.loc[common, "duration"].values
        if np.std(x) == 0 or np.std(t) == 0:
            return None
        _, p = spearmanr(x, t)
        return float(p) if p == p else None
    except Exception:
        return None


# Methylation matrix cache — built once per (matrix_id, sample-set) combination.
# Holds pre-filtered (no-zero-variance CpGs) numpy arrays plus column-z norms,
# so per-gene correlation collapses to a single matrix-vector multiply.
_METH_CACHE: dict[tuple, dict] = {}


def _meth_prep(methylation: pd.DataFrame, common_index: pd.Index) -> dict:
    """Return cached numpy view of methylation restricted to `common_index` samples,
    with constant CpGs dropped and column-z norms precomputed."""
    cache_key = (id(methylation), tuple(common_index))
    cached = _METH_CACHE.get(cache_key)
    if cached is not None:
        return cached
    meth = methylation.loc[common_index]
    arr = meth.to_numpy(dtype=np.float64, copy=True)
    # Drop constant CpGs once
    col_std = arr.std(axis=0)
    keep_mask = col_std > 0
    arr = arr[:, keep_mask]
    cpg_ids = meth.columns[keep_mask].to_numpy()
    # Column-mean-center
    arr -= arr.mean(axis=0)
    col_norms = np.linalg.norm(arr, axis=0)
    # Avoid division by zero in correlation (shouldn't happen since we dropped std=0)
    col_norms[col_norms == 0] = 1.0
    cached = {"arr_centered": arr, "col_norms": col_norms, "cpg_ids": cpg_ids, "n": arr.shape[0]}
    _METH_CACHE[cache_key] = cached
    return cached


def _gene_methylation_evidence(
    gene: str,
    expression: pd.DataFrame,
    methylation: pd.DataFrame | None,
    r_threshold: float = 0.3,
    fdr_threshold: float = 0.05,
) -> tuple[bool, dict]:
    """Does gene expression correlate with ANY CpG (Pearson, BH-FDR-corrected across CpGs)?
    Vectorized: all CpGs tested simultaneously via one matrix-vector dot product.
    Returns (passed, diagnostics with best CpG)."""
    if methylation is None or methylation.empty:
        return False, {"reason": "no methylation data"}
    if gene not in expression.columns:
        return False, {"reason": "gene not in expression"}
    try:
        from scipy.stats import t as student_t
        from statsmodels.stats.multitest import multipletests

        common = expression.index.intersection(methylation.index)
        if len(common) < 20:
            return False, {"reason": "too few common samples"}
        x = expression.loc[common, gene].to_numpy(dtype=np.float64)
        if np.std(x) == 0:
            return False, {"reason": "gene expression constant"}

        cache = _meth_prep(methylation, common)
        n = cache["n"]
        x_c = x - x.mean()
        x_norm = np.linalg.norm(x_c)
        if x_norm == 0:
            return False, {"reason": "gene expression constant after centering"}

        # Vectorized Pearson r across all CpGs:
        # r_j = (x_c · m_c[:,j]) / (||x_c|| · ||m_c[:,j]||)
        dots = cache["arr_centered"].T @ x_c
        rs = dots / (x_norm * cache["col_norms"])
        # Clip for numerical safety
        rs = np.clip(rs, -0.999999, 0.999999)

        # Two-sided p-value from t-statistic
        df = n - 2
        t_stat = rs * np.sqrt(df / (1.0 - rs ** 2))
        ps = 2.0 * student_t.sf(np.abs(t_stat), df=df)

        if ps.size == 0:
            return False, {"reason": "no testable CpGs"}

        _, fdrs, _, _ = multipletests(ps, method="fdr_bh")
        best_idx = int(np.argmax(np.abs(rs)))
        best_r = float(rs[best_idx])
        best_p = float(ps[best_idx])
        best_fdr = float(fdrs[best_idx])
        best_cpg = str(cache["cpg_ids"][best_idx])

        passed = abs(best_r) >= r_threshold and best_fdr < fdr_threshold
        return passed, {
            "best_cpg": best_cpg, "best_r": best_r, "best_p": best_p, "best_fdr_bh": best_fdr,
            "n_cpgs_tested": int(ps.size),
        }
    except Exception as e:
        return False, {"error": str(e)}


def _gene_cna_enrichment(
    gene: str,
    cna: pd.DataFrame | None,
    grouping: dict[str, str],
    p_threshold: float = 0.05,
) -> tuple[bool, dict]:
    """Does CNA status differ between groups for this gene? Fisher exact per group."""
    if cna is None or cna.empty:
        return False, {"reason": "no CNA data"}
    if gene not in cna.columns:
        return False, {"reason": "gene not in CNA matrix"}
    try:
        from scipy.stats import fisher_exact
        groups = pd.Series(grouping)
        common = cna.index.intersection(groups.index)
        if len(common) < 10:
            return False, {"reason": "too few covered samples"}
        # Restrict to CNA-covered samples
        covered = cna.loc[common]
        covered_mask = (covered != 0).any(axis=1)
        if covered_mask.sum() < 20:
            return False, {"reason": f"only {int(covered_mask.sum())} CNA-covered samples (<20 minimum for Fisher power)"}
        covered_ids = covered.index[covered_mask]
        x = cna.loc[covered_ids, gene]
        g = groups.loc[covered_ids]
        # Test amp+del combined vs neutral, per group (vs rest)
        altered = (x != 0).astype(int)
        best_p = 1.0
        best_group = None
        for grp in g.unique():
            in_g = (g == grp)
            a = int(altered[in_g].sum())
            b = int(in_g.sum() - a)
            c = int(altered[~in_g].sum())
            d = int((~in_g).sum() - c)
            if a + c < 1 or b + d < 1:
                continue
            try:
                _, p = fisher_exact([[a, b], [c, d]], alternative="two-sided")
            except Exception:
                continue
            if p < best_p:
                best_p = float(p)
                best_group = str(grp)
        passed = best_p < p_threshold
        return passed, {"best_group": best_group, "best_p": best_p}
    except Exception as e:
        return False, {"error": str(e)}


def _infer_sgh_directions(
    top_genes: list[str],
    expression: pd.DataFrame,
    surv_df: pd.DataFrame,
) -> dict[str, int]:
    """For each gene, fit univariate Cox in SGH-OS. Returns {gene: +1 protective | -1 risk}
    for genes that fit successfully; omits genes that don't fit or aren't in expression."""
    out = {}
    try:
        from lifelines import CoxPHFitter
        common = expression.index.intersection(surv_df.index)
        if len(common) < 20:
            return out
        for gene in top_genes:
            if gene not in expression.columns:
                continue
            x = expression.loc[common, gene]
            if x.std() == 0:
                continue
            df = surv_df.loc[common, ["duration", "event"]].copy()
            df[gene] = (x - x.mean()) / x.std()  # z-score for numerical stability
            try:
                cph = CoxPHFitter()
                cph.fit(df, duration_col="duration", event_col="event")
                coef = float(cph.params_[gene])
                out[gene] = -1 if coef > 0 else +1  # coef > 0 (HR>1) = risk
            except Exception:
                continue
    except Exception:
        pass
    return out


def _load_target(target_data_dir: Path) -> tuple[pd.DataFrame, pd.DataFrame] | None:
    """Load TARGET-OS + TARGET non-OS expression DataFrames.
    Returns (target_os, target_non_os) or None if data not available."""
    expr_path = target_data_dir / "expression.parquet"
    lab_path = target_data_dir / "TARGET_labels.tsv"
    if not expr_path.exists() or not lab_path.exists():
        return None
    try:
        expr = pd.read_parquet(expr_path)
        lab = pd.read_csv(lab_path, sep="\t", index_col=0)
        os_ids = lab.index[lab["cancer_type"] == "Osteosarcoma"]
        target_os = expr.loc[expr.index.isin(os_ids)]
        target_non_os = expr.loc[~expr.index.isin(os_ids)]
        return target_os, target_non_os
    except Exception:
        return None


def _load_target_os_survival(target_data_dir: Path) -> pd.DataFrame | None:
    """Load TARGET-OS survival DataFrame indexed by sample with columns
    ['T', 'E']. Returns None if not available."""
    expr_path = target_data_dir / "expression.parquet"
    clin_path = target_data_dir / "TARGET_OS_clinical.tsv"
    if not expr_path.exists() or not clin_path.exists():
        return None
    try:
        expr = pd.read_parquet(expr_path)
        clin = pd.read_csv(clin_path, sep="\t", index_col=0)
        clin = clin[clin["vital_status"].notna() & (clin["os_time"] > 0)]
        common = expr.index.intersection(clin.index)
        if len(common) < 10:
            return None
        return pd.DataFrame({"T": clin.loc[common, "os_time"],
                             "E": clin.loc[common, "event"]})
    except Exception:
        return None


# Positive controls — literature-defined OS prognostic markers (NOT from any
# discovery cohort), used to verify TARGET-OS survival data can detect signal.
_POS_CONTROLS: list[tuple[str, list[str], str]] = [
    ("cytolytic",     ["GZMA", "PRF1"], "prot"),
    ("ifn_gamma",     ["IFNG", "STAT1", "IDO1", "CXCL9", "CXCL10", "HLA-DRA"], "prot"),
    ("hypoxia",       ["VEGFA", "SLC2A1", "CA9", "LDHA", "PGK1", "ENO1", "ADM",
                       "NDRG1", "BNIP3", "P4HA1", "ALDOA", "PGAM1", "HK2", "HILPDA"], "adv"),
    ("proliferation", ["MKI67", "TOP2A", "CCNB1", "CDK1", "BUB1", "AURKA"], "adv"),
]


def _bh_fdr(pvalues: list[float]) -> list[float]:
    """Benjamini-Hochberg FDR correction. Returns FDR-adjusted p-values aligned with input."""
    try:
        from statsmodels.stats.multitest import multipletests
        valid_mask = [p is not None and 0 <= p <= 1 for p in pvalues]
        valid_p = [p for p, ok in zip(pvalues, valid_mask) if ok]
        if not valid_p:
            return [float("nan")] * len(pvalues)
        _, fdr_valid, _, _ = multipletests(valid_p, method="fdr_bh")
        out = []
        i = 0
        for ok in valid_mask:
            if ok:
                out.append(float(fdr_valid[i])); i += 1
            else:
                out.append(float("nan"))
        return out
    except Exception:
        return [float("nan")] * len(pvalues)


# ──────────────────────────────────────────────────────────────────────────────
# score_survival_stratification  (weight 3)
# Multi-group log-rank p + Cox max-vs-min HR magnitude
# ──────────────────────────────────────────────────────────────────────────────

def score_survival_stratification(
    grouping: dict[str, str],
    metadata: pd.DataFrame,
) -> tuple[float, dict]:
    surv_df = _build_survival_df(metadata)
    if surv_df.empty or surv_df["event"].sum() < 5:
        return 0.0, {"reason": "insufficient survival data"}
    try:
        from lifelines.statistics import multivariate_logrank_test
        from lifelines import CoxPHFitter

        groups = pd.Series(grouping, name="group")
        common = surv_df.index.intersection(groups.index)
        if len(common) < 20:
            return 0.0, {"reason": f"only {len(common)} samples with survival + group"}
        sdf = surv_df.loc[common].join(groups)
        if sdf["group"].nunique() < 2:
            return 0.0, {"reason": "only one group with survival data"}

        # Multi-group log-rank
        lr = multivariate_logrank_test(sdf["duration"], sdf["group"], sdf["event"])
        lr_p = float(lr.p_value)
        lr_score = float(np.clip(-np.log10(max(lr_p, 1e-12)) / 4.0, 0, 1))  # p=1e-4 → 1.0

        # Cox HR magnitude: fit one-hot encoded groups (reference = smallest median surv)
        med = sdf.groupby("group")["duration"].median()
        ref_group = med.idxmin()  # reference = worst median
        cox_df = sdf.copy()
        for grp in sdf["group"].unique():
            if grp == ref_group:
                continue
            cox_df[f"_g_{grp}"] = (cox_df["group"] == grp).astype(int)
        cox_df = cox_df.drop(columns=["group"])
        try:
            cph = CoxPHFitter()
            cph.fit(cox_df, duration_col="duration", event_col="event")
            # Max-vs-min HR = largest |log HR| across non-reference groups
            log_hrs = cph.params_.values
            max_abs_log_hr = float(np.max(np.abs(log_hrs))) if len(log_hrs) > 0 else 0.0
            hr_max_min = float(np.exp(max_abs_log_hr))
            # HR ratio of 4 → full score; HR=2 → 0.5
            hr_score = float(np.clip(np.log(hr_max_min) / np.log(4.0), 0, 1))
        except Exception as e:
            hr_max_min = float("nan")
            hr_score = 0.0

        score = 0.5 * lr_score + 0.5 * hr_score
        return float(score), {
            "n_samples": int(len(common)),
            "n_events": int(sdf["event"].sum()),
            "n_groups": int(sdf["group"].nunique()),
            "logrank_p": lr_p,
            "logrank_score": lr_score,
            "hr_max_vs_min": hr_max_min,
            "hr_score": hr_score,
        }
    except Exception as e:
        return 0.0, {"error": str(e)}


# ──────────────────────────────────────────────────────────────────────────────
# score_provenance_integrity  (weight 3)
# Per-gene audit of the two-of-three test the prompt enforces
# ──────────────────────────────────────────────────────────────────────────────

def score_provenance_integrity(
    top_genes: list[str],
    grouping: dict[str, str],
    expression: pd.DataFrame,
    metadata: pd.DataFrame,
    methylation: pd.DataFrame | None,
    cna: pd.DataFrame | None,
) -> tuple[float, dict]:
    """For each submitted top_gene, verify ≥ 2 of:
      (1) DE between groups: ANOVA F-test, FDR<0.05 across all expression genes tested
      (2) Survival correlation: Spearman with OS time, FDR<0.05 across all expression genes tested
      (3) Cross-modal: methylation correlation OR CNA enrichment
    Score = fraction passing ≥2 tests."""
    if not top_genes:
        return 0.0, {"reason": "no top_genes submitted"}
    try:
        # Filter to genes present in expression matrix (others fail by default)
        valid_genes = [g for g in top_genes if g in expression.columns]

        # Test 1: DE p-values, then FDR-correct across the full expression
        # testing universe. The prompt requires genome-wide correction; correcting
        # only across submitted top_genes would make selective reporting too easy.
        universe_genes = list(expression.columns)
        de_pvals = [_gene_de_anova(g, expression, grouping) for g in universe_genes]
        de_fdr = _bh_fdr(de_pvals)
        de_fdr_by_gene = dict(zip(universe_genes, de_fdr))
        de_pass = {
            g: (de_fdr_by_gene.get(g, float("nan")) == de_fdr_by_gene.get(g, float("nan"))
                and de_fdr_by_gene[g] < 0.05)
            for g in valid_genes
        }

        # Test 2: Survival p-values, also FDR-corrected across the full expression
        # testing universe.
        surv_df = _build_survival_df(metadata)
        surv_pvals = [_gene_survival_pvalue(g, expression, surv_df) for g in universe_genes]
        surv_fdr = _bh_fdr(surv_pvals)
        surv_fdr_by_gene = dict(zip(universe_genes, surv_fdr))
        surv_pass = {
            g: (surv_fdr_by_gene.get(g, float("nan")) == surv_fdr_by_gene.get(g, float("nan"))
                and surv_fdr_by_gene[g] < 0.05)
            for g in valid_genes
        }

        # Test 3: cross-modal (methylation OR CNA), per-gene
        modal_pass = {}
        modal_diag = {}
        for g in valid_genes:
            meth_ok, meth_d = _gene_methylation_evidence(g, expression, methylation)
            cna_ok, cna_d = _gene_cna_enrichment(g, cna, grouping)
            modal_pass[g] = meth_ok or cna_ok
            modal_diag[g] = {"methylation": meth_ok, "cna": cna_ok}

        # Count tests passed per gene
        per_gene = {}
        for g in top_genes:
            if g not in valid_genes:
                per_gene[g] = {"de": False, "surv": False, "modal": False, "n_passed": 0, "valid": False}
                continue
            n_passed = int(de_pass[g]) + int(surv_pass[g]) + int(modal_pass[g])
            per_gene[g] = {
                "de": de_pass[g],
                "surv": surv_pass[g],
                "modal": modal_pass[g],
                "n_passed": n_passed,
                "valid": True,
                "de_fdr_genomewide": de_fdr_by_gene.get(g),
                "surv_fdr_genomewide": surv_fdr_by_gene.get(g),
            }

        passing = sum(1 for v in per_gene.values() if v["n_passed"] >= 2)
        score = passing / len(top_genes)
        return float(score), {
            "n_top_genes": len(top_genes),
            "n_valid_in_expr": len(valid_genes),
            "fdr_universe": "all expression genes with valid per-test statistics",
            "n_expression_genes_tested": len(universe_genes),
            "n_passing_2of3": passing,
            "per_gene": per_gene,
        }
    except Exception as e:
        return 0.0, {"error": str(e)}


# ──────────────────────────────────────────────────────────────────────────────
# score_cross_modal_support  (weight 2)
# Stricter than provenance test 3: requires RNA evidence AND non-RNA evidence
# ──────────────────────────────────────────────────────────────────────────────

def score_cross_modal_support(
    top_genes: list[str],
    grouping: dict[str, str],
    expression: pd.DataFrame,
    metadata: pd.DataFrame,
    methylation: pd.DataFrame | None,
    cna: pd.DataFrame | None,
) -> tuple[float, dict]:
    """For each top_gene, check whether expression evidence (DE OR survival, nominal p<0.05)
    co-occurs with non-RNA evidence (methylation OR CNA). Score = fraction with both."""
    if not top_genes:
        return 0.0, {"reason": "no top_genes submitted"}
    try:
        valid_genes = [g for g in top_genes if g in expression.columns]
        surv_df = _build_survival_df(metadata)

        per_gene = {}
        n_with_both = 0
        for g in top_genes:
            if g not in valid_genes:
                per_gene[g] = {"rna": False, "non_rna": False, "valid": False}
                continue
            de_p = _gene_de_anova(g, expression, grouping)
            surv_p = _gene_survival_pvalue(g, expression, surv_df)
            rna_ok = (de_p is not None and de_p < 0.05) or (surv_p is not None and surv_p < 0.05)

            meth_ok, _ = _gene_methylation_evidence(g, expression, methylation)
            cna_ok, _ = _gene_cna_enrichment(g, cna, grouping)
            non_rna_ok = meth_ok or cna_ok

            both = bool(rna_ok and non_rna_ok)
            if both:
                n_with_both += 1
            per_gene[g] = {
                "rna": rna_ok,
                "non_rna": non_rna_ok,
                "methylation": meth_ok,
                "cna": cna_ok,
                "valid": True,
            }

        score = n_with_both / len(top_genes)
        return float(score), {
            "n_top_genes": len(top_genes),
            "n_valid_in_expr": len(valid_genes),
            "n_with_rna_and_non_rna": n_with_both,
            "per_gene": per_gene,
        }
    except Exception as e:
        return 0.0, {"error": str(e)}


# ──────────────────────────────────────────────────────────────────────────────
# score_target_coexpr_replication  (weight 2)
# Does the agent's gene module structure replicate in TARGET-OS?
# Score = average of three signals:
#   (a) matrix ρ between SGH-OS and TARGET-OS gene-gene correlation matrices
#   (b) sign concordance of off-diagonal pairs (above-chance scaled)
#   (c) signature direction match (protective/risk directions preserved in TARGET-OS)
# TARGET non-OS correlation reported in diagnostics as OS-specificity check.
# ──────────────────────────────────────────────────────────────────────────────

def _spearman_matrix(df: pd.DataFrame) -> pd.DataFrame:
    from scipy.stats import spearmanr
    rho, _ = spearmanr(df.values)
    if np.isscalar(rho):
        rho = np.array([[1.0, rho], [rho, 1.0]])
    return pd.DataFrame(rho, index=df.columns, columns=df.columns)


def _offdiag_values(mat: pd.DataFrame) -> np.ndarray:
    cols = list(mat.columns)
    out = []
    for i in range(len(cols)):
        for j in range(i + 1, len(cols)):
            out.append(mat.iloc[i, j])
    return np.array(out)


def score_target_coexpr_replication(
    top_genes: list[str],
    sgh_expression: pd.DataFrame,
    sgh_metadata: pd.DataFrame,
    target_data_dir: Path,
) -> tuple[float, dict]:
    target = _load_target(target_data_dir)
    if target is None:
        return 0.0, {"reason": f"TARGET data not loadable from {target_data_dir}"}
    target_os, target_non_os = target
    if len(target_os) < 10:
        return 0.0, {"reason": f"TARGET-OS too small (n={len(target_os)})"}

    try:
        from scipy.stats import spearmanr as _spr

        # Restrict to genes present in BOTH SGH-OS and TARGET expression
        valid = [g for g in top_genes
                 if g in sgh_expression.columns and g in target_os.columns]
        if len(valid) < _MIN_TARGET_GENES:
            return 0.0, {
                "reason": f"only {len(valid)} of {len(top_genes)} top_genes present in both cohorts",
                "valid_genes": valid,
            }

        # 1. Co-expression matrices
        sgh_sub    = sgh_expression[valid]
        target_sub = target_os[valid]
        nonos_sub  = target_non_os[valid]

        corr_sgh    = _spearman_matrix(sgh_sub)
        corr_target = _spearman_matrix(target_sub)
        corr_nonos  = _spearman_matrix(nonos_sub)

        pairs_sgh    = _offdiag_values(corr_sgh)
        pairs_target = _offdiag_values(corr_target)
        pairs_nonos  = _offdiag_values(corr_nonos)

        # Matrix ρ: Spearman correlation between pairwise correlation vectors
        if len(pairs_sgh) >= 3 and np.std(pairs_sgh) > 0 and np.std(pairs_target) > 0:
            mat_rho_target, _ = _spr(pairs_sgh, pairs_target)
            mat_rho_target = float(mat_rho_target) if mat_rho_target == mat_rho_target else 0.0
        else:
            mat_rho_target = 0.0

        if len(pairs_sgh) >= 3 and np.std(pairs_sgh) > 0 and np.std(pairs_nonos) > 0:
            mat_rho_nonos, _ = _spr(pairs_sgh, pairs_nonos)
            mat_rho_nonos = float(mat_rho_nonos) if mat_rho_nonos == mat_rho_nonos else 0.0
        else:
            mat_rho_nonos = 0.0

        # Sign concordance
        sign_conc = float((np.sign(pairs_sgh) == np.sign(pairs_target)).mean()) if len(pairs_sgh) > 0 else 0.0

        # 2. Signature direction match (infer directions from SGH-OS Cox)
        #    LEAVE-ONE-OUT: when testing gene G's direction, the signature is
        #    built from the OTHER genes — never from G itself. Otherwise each
        #    gene structurally correlates with the signature it's part of
        #    (random genes hit ~0.8 match purely from this bias).
        surv_df = _build_survival_df(sgh_metadata)
        directions = _infer_sgh_directions(valid, sgh_expression, surv_df)
        prot = [g for g, d in directions.items() if d > 0]
        risk = [g for g, d in directions.items() if d < 0]
        dir_match_frac = float("nan")
        if prot and risk:
            tz = (target_sub - target_sub.mean()) / target_sub.std(ddof=0).replace(0, 1)
            match_count = 0
            total = 0
            for g, d in directions.items():
                col = target_sub[g]
                if col.std() == 0:
                    continue
                # Leave-one-out: rebuild signature without gene g
                loo_prot = [p for p in prot if p != g]
                loo_risk = [r for r in risk if r != g]
                if not loo_prot or not loo_risk:
                    continue  # can't form a balanced signature without this gene
                sig_loo = tz[loo_prot].mean(axis=1) - tz[loo_risk].mean(axis=1)
                rho, _ = _spr(col.values, sig_loo.values)
                if rho != rho:
                    continue
                total += 1
                if np.sign(rho) == d:
                    match_count += 1
            dir_match_frac = match_count / total if total > 0 else float("nan")

        # 3. Score = average of three signals, each in [0, 1]
        #    rho_score uses the OS-specificity DELTA (target_os - target_non_os)
        #    rather than raw target_os ρ — random gene sets carry housekeeping /
        #    co-regulated module fragments that preserve correlation in BOTH
        #    cohorts, giving raw ρ a non-zero null floor (~0.48 from n=5 calibration).
        #    Subtracting non-OS cancels that generic-biology signal; only OS-specific
        #    co-expression structure survives.
        rho_score  = float(np.clip(mat_rho_target - mat_rho_nonos, 0, 1))
        conc_score = float(np.clip((sign_conc - 0.5) * 2, 0, 1))
        dir_score  = float(dir_match_frac) if dir_match_frac == dir_match_frac else 0.0
        # If we couldn't compute direction match (no prot/risk split), weight only rho + conc
        if dir_match_frac != dir_match_frac:
            score = 0.5 * rho_score + 0.5 * conc_score
        else:
            score = (rho_score + conc_score + dir_score) / 3.0

        is_monodirectional = not (prot and risk)
        return float(score), {
            "n_top_genes": len(top_genes),
            "n_valid_in_both": len(valid),
            "n_target_os_samples": int(len(target_os)),
            "n_target_non_os_samples": int(len(target_non_os)),
            "matrix_rho_target_os": mat_rho_target,
            "matrix_rho_target_non_os_control": mat_rho_nonos,
            "os_specificity_delta": float(mat_rho_target - mat_rho_nonos),
            "sign_concordance": sign_conc,
            "direction_match_frac": dir_match_frac,
            "n_protective_inferred": len(prot),
            "n_risk_inferred": len(risk),
            "is_monodirectional": is_monodirectional,
            "scoring_basis": "rho+conc only (monodirectional)" if is_monodirectional else "rho+conc+direction",
            "subscore_rho": rho_score,
            "subscore_concordance": conc_score,
            "subscore_direction": dir_score,
        }
    except Exception as e:
        return 0.0, {"error": str(e)}


# ──────────────────────────────────────────────────────────────────────────────
# score_target_survival_replication  (weight 3)
# Does the agent's signature stratify survival in TARGET-OS?
# Score = (direction_match + significance_score + magnitude_score) / 3
#   direction_match: 1 if Cox HR matches expected (protective sig → HR<1), else 0
#   significance_score: clip(-log10(p) / 4, 0, 1); zeroed if direction wrong
#   magnitude_score: clip(|log HR| / log(2), 0, 1); zeroed if direction wrong
# Positive controls reported in diagnostics for interpretability (genuine
# non-replication vs underpowered cohort).
# ──────────────────────────────────────────────────────────────────────────────

def _cox_univariate(df: pd.DataFrame, series: pd.Series) -> dict | None:
    """Univariate Cox per SD. df has 'T', 'E'. Returns dict with hr, p, n or None."""
    try:
        from lifelines import CoxPHFitter
        d = pd.DataFrame({"T": df["T"], "E": df["E"], "x": series}).dropna()
        if len(d) < 10 or d["E"].sum() < 5:
            return None
        if d["x"].nunique() > 2:
            sd = d["x"].std(ddof=0)
            if sd == 0:
                return None
            d["x"] = (d["x"] - d["x"].mean()) / sd
        cph = CoxPHFitter()
        cph.fit(d, duration_col="T", event_col="E")
        s = cph.summary.loc["x"]
        return {
            "hr": float(s["exp(coef)"]),
            "p": float(s["p"]),
            "n": int(len(d)),
            "events": int(d["E"].sum()),
        }
    except Exception:
        return None


def _zmean(df: pd.DataFrame, genes: list[str]) -> pd.Series:
    """Mean of z-scored expression across given genes (those present in df)."""
    present = [g for g in genes if g in df.columns]
    if not present:
        return pd.Series(0.0, index=df.index)
    z = (df[present] - df[present].mean()) / df[present].std(ddof=0).replace(0, 1)
    return z.mean(axis=1)


def score_target_survival_replication(
    top_genes: list[str],
    sgh_expression: pd.DataFrame,
    sgh_metadata: pd.DataFrame,
    target_data_dir: Path,
) -> tuple[float, dict]:
    target = _load_target(target_data_dir)
    if target is None:
        return 0.0, {"reason": f"TARGET data not loadable from {target_data_dir}"}
    target_os, _ = target

    surv = _load_target_os_survival(target_data_dir)
    if surv is None:
        return 0.0, {"reason": "TARGET-OS survival not loadable"}

    # Restrict to samples with both expression and survival
    common = target_os.index.intersection(surv.index)
    if len(common) < 20:
        return 0.0, {"reason": f"only {len(common)} TARGET-OS samples with survival"}
    target_os = target_os.loc[common]
    target_df = surv.loc[common].copy()

    try:
        # Infer directions from SGH-OS Cox
        sgh_surv = _build_survival_df(sgh_metadata)
        directions = _infer_sgh_directions(top_genes, sgh_expression, sgh_surv)
        valid_in_target = [g for g in directions if g in target_os.columns]
        if len(valid_in_target) < 2:
            return 0.0, {
                "reason": f"only {len(valid_in_target)} top_genes have direction + TARGET expression",
                "n_directions_inferred": len(directions),
            }

        prot = [g for g in valid_in_target if directions[g] > 0]
        risk = [g for g in valid_in_target if directions[g] < 0]

        # Build signature: high = good survival expected (HR<1)
        sig = _zmean(target_os, prot) - (_zmean(target_os, risk) if risk else 0.0)

        # Cox on candidate signature in TARGET-OS
        cand = _cox_univariate(target_df, sig)
        if cand is None:
            return 0.0, {"reason": "Cox fit failed on signature in TARGET-OS"}

        # Direction match: protective signature expected to have HR<1
        direction_ok = cand["hr"] < 1
        direction_score = 1.0 if direction_ok else 0.0

        # Direction-as-GATE (not as additive component): a wrong-direction signature
        # is anti-replication, not partial replication. Crediting half-the-score for
        # what amounts to a random-coin direction guess inflated the null floor to
        # ~0.27 with mostly chance contributions.
        # With direction as gate, the null collapses (~0.10) and real episodes that
        # genuinely replicate keep their score from sig + mag.
        if not direction_ok:
            sig_score = 0.0
            mag_score = 0.0
            score = 0.0
        else:
            p = max(cand["p"], 1e-12)
            sig_score = float(np.clip(-np.log10(p) / 4.0, 0, 1))
            mag_score = float(np.clip(abs(np.log(cand["hr"])) / np.log(2.0), 0, 1))
            score = (sig_score + mag_score) / 2.0

        # Positive controls — for interpretability of nulls
        pos_controls = []
        for name, genes, expect in _POS_CONTROLS:
            series = _zmean(target_os, genes)
            c = _cox_univariate(target_df, series)
            if c is None:
                pos_controls.append({"name": name, "expect": expect, "result": "fit_failed"})
                continue
            passes = (c["p"] < 0.05) and (
                (c["hr"] < 1 and expect == "prot") or (c["hr"] > 1 and expect == "adv")
            )
            pos_controls.append({
                "name": name, "expect": expect,
                "hr": round(c["hr"], 3), "p": round(c["p"], 4),
                "passes": bool(passes),
            })
        n_pos_pass = sum(1 for x in pos_controls if x.get("passes"))
        cohort_powered = n_pos_pass >= 1

        # Verdict with magnitude check: direction-OK alone isn't replication.
        # A signature with HR=0.94, p=0.74 has the right SIGN but no actual signal.
        # Tiers (only consulted when direction is correct AND cohort is powered):
        #   replicates       : significant (p<0.05) AND |log HR| > log(1.5)
        #   directionally-OK : significant (p<0.05) but weak magnitude
        #   uninformative    : direction matches but p≥0.05 — could be chance alignment
        log_hr_threshold = np.log(1.5)  # HR<0.67 or HR>1.5 = meaningful magnitude
        sig_threshold = 0.05
        is_significant = cand["p"] < sig_threshold
        is_strong_magnitude = abs(np.log(cand["hr"])) > log_hr_threshold
        if not cohort_powered:
            verdict = "underpowered_cohort_inconclusive"
            note = "Cohort underpowered (no positive controls passing) — null candidate result is inconclusive"
        elif not direction_ok:
            verdict = "genuine_non_replication"
            note = "Cohort can detect known prognostic signal — candidate null is genuine non-replication"
        elif is_significant and is_strong_magnitude:
            verdict = "replicates"
            note = f"Candidate replicates: HR={cand['hr']:.2f}, p={cand['p']:.3g} (direction + magnitude + significance)"
        elif is_significant:
            verdict = "weak_replication"
            note = f"Candidate weakly replicates: direction correct and p<0.05, but |log HR|={abs(np.log(cand['hr'])):.2f} below threshold — small effect"
        else:
            verdict = "uninformative"
            note = f"Candidate uninformative: HR={cand['hr']:.2f}, p={cand['p']:.3g}. Direction technically matches but signal is indistinguishable from chance — not a replication"

        return float(score), {
            "n_samples": int(len(common)),
            "n_events": int(target_df["E"].sum()),
            "n_top_genes_with_direction": len(valid_in_target),
            "n_protective": len(prot),
            "n_risk": len(risk),
            "candidate_signature_hr": cand["hr"],
            "candidate_signature_p": cand["p"],
            "direction_match": direction_ok,
            "subscore_direction": direction_score,
            "subscore_significance": sig_score,
            "subscore_magnitude": mag_score,
            "positive_controls": pos_controls,
            "n_positive_controls_passing": n_pos_pass,
            "cohort_powered": cohort_powered,
            "verdict": verdict,
            "interpretation_note": note,
        }
    except Exception as e:
        return 0.0, {"error": str(e)}
