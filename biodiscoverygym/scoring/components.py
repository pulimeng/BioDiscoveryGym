"""
Scoring components for BioDiscoveryGym v2 evaluator.

Each function returns a raw float in [0, 1]; the orchestrator applies weights.
All functions are defensively coded — missing data returns 0.0, never raises.
"""
from __future__ import annotations

import gzip
import re
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


# ──────────────────────────────────────────────────────────────────────────────
# structure_validity  (weight 2)
# Bootstrap-stable silhouette on expression PCA + ARI against k-means re-cluster
# ──────────────────────────────────────────────────────────────────────────────

def score_structure_validity(
    grouping: dict[str, str],
    expression: pd.DataFrame,
    n_bootstrap: int = 100,
    pca_dims: int = 50,
    seed: int = 42,
) -> tuple[float, dict]:
    try:
        from sklearn.decomposition import PCA
        from sklearn.metrics import silhouette_score, adjusted_rand_score
        from sklearn.cluster import KMeans

        labels = pd.Series(grouping)
        common = expression.index.intersection(labels.index)
        if len(common) < 20:
            return 0.0, {"reason": "too few samples"}
        y = labels.loc[common].values
        if len(np.unique(y)) < 2:
            return 0.0, {"reason": "only one group"}

        X = expression.loc[common].values
        n_dims = min(pca_dims, X.shape[1], X.shape[0] - 1)
        X_pca = PCA(n_components=n_dims, random_state=seed).fit_transform(X)

        # Silhouette on full data
        sil = float(silhouette_score(X_pca, y))
        sil_norm = float(np.clip(sil, 0, 1))

        # Bootstrap ARI: re-cluster subsamples, compare to submitted labels
        k = len(np.unique(y))
        rng = np.random.default_rng(seed)
        ari_scores = []
        for _ in range(n_bootstrap):
            idx = rng.choice(len(common), size=int(0.8 * len(common)), replace=False)
            if len(np.unique(y[idx])) < 2:
                continue
            km = KMeans(n_clusters=k, n_init=3, random_state=int(rng.integers(1e6)))
            y_km = km.fit_predict(X_pca[idx])
            ari_scores.append(adjusted_rand_score(y[idx], y_km))

        ari_mean = float(np.clip(np.mean(ari_scores) if ari_scores else 0.0, 0, 1))

        score = 0.5 * sil_norm + 0.5 * ari_mean
        return float(score), {"silhouette": sil_norm, "bootstrap_ari": ari_mean, "n_bootstrap": len(ari_scores)}
    except Exception as e:
        return 0.0, {"error": str(e)}


# ──────────────────────────────────────────────────────────────────────────────
# clinical_signal  (weight 3)
# ΔC-index over null Cox + log HR between extreme-survival subtypes
# ──────────────────────────────────────────────────────────────────────────────

def score_clinical_signal(
    grouping: dict[str, str],
    metadata: pd.DataFrame,
) -> tuple[float, dict]:
    try:
        from lifelines import CoxPHFitter
        from lifelines.utils import concordance_index

        groups = pd.Series(grouping, name="group")
        df = metadata.join(groups, how="inner").copy()
        df = df[df["group"].notna()]

        # Build duration/event columns
        rows = []
        for _, row in df.iterrows():
            vs = str(row.get("vital_status", "")).lower()
            event = 1 if ("dead" in vs or "deceased" in vs) else 0
            days = row.get("days_to_death") if event else row.get("days_to_last_follow_up")
            try:
                days = float(days)
            except (TypeError, ValueError):
                continue
            if days <= 0 or days != days:  # also rejects NaN
                continue
            rows.append({"duration": days, "event": event, "group": row["group"]})

        if len(rows) < 20:
            return 0.0, {"reason": "insufficient survival data"}
        sdf = pd.DataFrame(rows)
        if sdf["event"].sum() < 5:
            return 0.0, {"reason": "too few events"}
        if sdf["group"].nunique() < 2:
            return 0.0, {"reason": "only one group"}

        # C-index: encode groups by median survival rank
        med_surv = sdf.groupby("group")["duration"].median().rank()
        sdf["group_rank"] = sdf["group"].map(med_surv)
        c_idx = concordance_index(sdf["duration"], sdf["group_rank"], sdf["event"])
        c_idx = max(c_idx, 1.0 - c_idx)
        delta_c = float(np.clip((c_idx - 0.5) / 0.3, 0, 1))  # 0.3 ΔC → full score

        # Log HR between worst and best survival groups
        best = med_surv.idxmax()
        worst = med_surv.idxmin()
        extreme = sdf[sdf["group"].isin([best, worst])].copy()
        extreme["is_best"] = (extreme["group"] == best).astype(int)
        try:
            cph = CoxPHFitter()
            cph.fit(extreme[["duration", "event", "is_best"]], duration_col="duration", event_col="event")
            log_hr = float(abs(cph.params_["is_best"]))
            hr_score = float(np.clip(log_hr / 2.0, 0, 1))  # log HR of 2 → full score
        except Exception:
            hr_score = 0.0
            log_hr = float("nan")

        score = 0.6 * delta_c + 0.4 * hr_score
        return float(score), {"c_index": c_idx, "delta_c": delta_c, "log_hr": log_hr, "hr_score": hr_score}
    except Exception as e:
        return 0.0, {"error": str(e)}


# ──────────────────────────────────────────────────────────────────────────────
# genomic_coherence — driver enrichment  (weight 2 of 4)
# FDR-corrected Fisher's exact for OncoKB/COSMIC drivers per subtype
# ──────────────────────────────────────────────────────────────────────────────

def score_driver_enrichment(
    grouping: dict[str, str],
    mutation: pd.DataFrame | None,
    cancer_genes_path: Path,
) -> tuple[float, dict]:
    if mutation is None or mutation.empty:
        return 0.0, {"reason": "no mutation data"}
    try:
        from scipy.stats import fisher_exact
        from statsmodels.stats.multitest import multipletests

        drivers = _load_driver_genes(cancer_genes_path)
        driver_cols = [c for c in mutation.columns if c in drivers]
        if not driver_cols:
            return 0.0, {"reason": "no driver genes in mutation matrix"}

        groups = pd.Series(grouping)
        common = mutation.index.intersection(groups.index)
        if len(common) < 10:
            return 0.0, {"reason": "too few samples with mutation data"}

        mut = mutation.loc[common, driver_cols]
        grp = groups.loc[common]
        unique_groups = grp.unique()

        pvals = []
        for gene in driver_cols:
            for g in unique_groups:
                in_g = grp == g
                a = int(mut.loc[in_g, gene].sum())
                b = int(in_g.sum() - a)
                c = int(mut.loc[~in_g, gene].sum())
                d = int((~in_g).sum() - c)
                _, p = fisher_exact([[a, b], [c, d]], alternative="two-sided")
                pvals.append(p)

        if not pvals:
            return 0.0, {"reason": "no valid tests"}

        _, fdr, _, _ = multipletests(pvals, method="fdr_bh")
        n_sig = int((fdr < 0.05).sum())
        # Score: 5 significant driver associations → full score
        score = float(np.clip(n_sig / 5.0, 0, 1))
        return score, {"n_drivers_tested": len(driver_cols), "n_significant_fdr05": n_sig}
    except Exception as e:
        return 0.0, {"error": str(e)}


def _load_driver_genes(path: Path) -> set[str]:
    try:
        df = pd.read_csv(path, sep="\t")
        col = "Hugo Symbol" if "Hugo Symbol" in df.columns else df.columns[0]
        return set(df[col].dropna().astype(str))
    except Exception:
        return set()


# ──────────────────────────────────────────────────────────────────────────────
# genomic_coherence — RPPA cross-modal  (weight 2 of 4)
# ARI between expression-based grouping and RPPA k-means re-cluster
# ──────────────────────────────────────────────────────────────────────────────

def score_rppa_concordance(
    grouping: dict[str, str],
    rppa: pd.DataFrame | None,
    seed: int = 42,
) -> tuple[float, dict]:
    if rppa is None or rppa.empty:
        return 0.0, {"reason": "no RPPA data"}
    try:
        from sklearn.cluster import KMeans
        from sklearn.metrics import adjusted_rand_score
        from sklearn.preprocessing import StandardScaler

        groups = pd.Series(grouping)
        common = rppa.index.intersection(groups.index)
        if len(common) < 20:
            return 0.0, {"reason": "too few samples with RPPA data"}

        k = groups.loc[common].nunique()
        if k < 2:
            return 0.0, {"reason": "only one group"}

        X = StandardScaler().fit_transform(rppa.loc[common].fillna(0))
        y_expr = groups.loc[common].values
        y_rppa = KMeans(n_clusters=k, n_init=10, random_state=seed).fit_predict(X)

        ari = float(adjusted_rand_score(y_expr, y_rppa))
        score = float(np.clip(ari, 0, 1))
        return score, {"ari": ari, "k": k, "n_samples": len(common)}
    except Exception as e:
        return 0.0, {"error": str(e)}


# ──────────────────────────────────────────────────────────────────────────────
# reference_concordance  (weight 2)
# Max NMI across all available TCGA subtype schemes
# ──────────────────────────────────────────────────────────────────────────────

def score_reference_concordance(
    grouping: dict[str, str],
    sample_id_map: dict[str, str],
    cohort: str,
    pancan_path: Path,
    tcgasubtype_path: Path,
) -> tuple[float, dict]:
    try:
        from sklearn.metrics import normalized_mutual_info_score

        # Reverse map: original_barcode → SAMPLE_XXXX
        orig_to_anon = {v: k for k, v in sample_id_map.items()}

        results = {}

        # --- pancan_subtypes.tsv (one scheme per cohort) ---
        try:
            pan = pd.read_csv(pancan_path, sep="\t")
            pan = pan[pan["cohort"] == cohort.upper()]
            gt = dict(zip(pan["sample_id"], pan["subtype"]))
            y_pred, y_true = _align_grouping(grouping, orig_to_anon, gt)
            if len(y_true) >= 10:
                results["pancan"] = normalized_mutual_info_score(y_true, y_pred)
        except Exception:
            pass

        # --- TCGASubtype multi-scheme ---
        try:
            with gzip.open(tcgasubtype_path, "rt") as f:
                tdf = pd.read_csv(f, sep="\t")
            # Truncate barcode to TCGA-XX-XXXX (first 3 parts)
            tdf["barcode"] = tdf["sampleID"].str.rsplit("-", n=1).str[0]
            scheme_cols = [c for c in tdf.columns if c.startswith("Subtype_")]
            for col in scheme_cols:
                sub = tdf[["barcode", col]].dropna(subset=[col])
                gt = dict(zip(sub["barcode"], sub[col]))
                y_pred, y_true = _align_grouping(grouping, orig_to_anon, gt)
                if len(y_true) >= 10:
                    results[col] = normalized_mutual_info_score(y_true, y_pred)
        except Exception:
            pass

        if not results:
            return 0.0, {"reason": "no reference scheme matched"}

        best_scheme = max(results, key=results.get)
        best_nmi = float(results[best_scheme])
        return float(np.clip(best_nmi, 0, 1)), {"best_scheme": best_scheme, "best_nmi": best_nmi, "all_nmi": results}
    except Exception as e:
        return 0.0, {"error": str(e)}


def _align_grouping(
    grouping: dict,
    orig_to_anon: dict,
    ground_truth: dict,
) -> tuple[list, list]:
    y_pred, y_true = [], []
    for sample_id, agent_label in grouping.items():
        original = {v: k for k, v in orig_to_anon.items()}.get(sample_id, sample_id)
        # Also try direct lookup (some paths use original barcodes)
        gt_label = ground_truth.get(original) or ground_truth.get(sample_id)
        if gt_label:
            y_pred.append(str(agent_label))
            y_true.append(str(gt_label))
    return y_pred, y_true


# ──────────────────────────────────────────────────────────────────────────────
# marker_evidence  (weight 2)
# HGNC validity + one-vs-rest AUC across all subtypes + OncoKB overlap bonus
# ──────────────────────────────────────────────────────────────────────────────

def score_marker_evidence(
    top_genes: list[str],
    grouping: dict[str, str],
    expression: pd.DataFrame,
    cancer_genes_path: Path,
) -> tuple[float, dict]:
    if not top_genes or not grouping:
        return 0.0, {"reason": "no genes or no grouping"}
    try:
        from sklearn.metrics import roc_auc_score

        # HGNC validity: gene must exist in expression matrix
        valid_genes = [g for g in top_genes if g in expression.columns]
        validity_rate = len(valid_genes) / len(top_genes) if top_genes else 0.0

        groups = pd.Series(grouping)
        common = expression.index.intersection(groups.index)
        if len(common) < 10 or not valid_genes:
            return float(validity_rate * 0.3), {
                "validity_rate": validity_rate,
                "valid_genes": valid_genes,
                "reason": "too few samples or no valid genes for AUC",
            }

        # One-vs-rest AUC across all subtypes
        unique_groups = groups.loc[common].unique()
        aucs = []
        for gene in valid_genes[:15]:
            x = expression.loc[common, gene]
            gene_aucs = []
            for g in unique_groups:
                y = (groups.loc[common] == g).astype(int)
                if y.sum() < 3 or (1 - y).sum() < 3:
                    continue
                try:
                    auc = roc_auc_score(y, x)
                    gene_aucs.append(max(auc, 1.0 - auc))
                except Exception:
                    pass
            if gene_aucs:
                aucs.append(np.mean(gene_aucs))

        auc_score = float(np.clip((np.mean(aucs) - 0.5) * 2, 0, 1)) if aucs else 0.0

        # OncoKB overlap
        drivers = _load_driver_genes(cancer_genes_path)
        oncokb_overlap = len([g for g in valid_genes if g in drivers]) / max(len(valid_genes), 1)

        # Combine: 0.4 validity + 0.4 AUC + 0.2 OncoKB
        score = 0.4 * validity_rate + 0.4 * auc_score + 0.2 * oncokb_overlap
        return float(score), {
            "validity_rate": validity_rate,
            "valid_genes": valid_genes[:5],
            "mean_ovr_auc": float(np.mean(aucs)) if aucs else None,
            "auc_score": auc_score,
            "oncokb_overlap": oncokb_overlap,
        }
    except Exception as e:
        return 0.0, {"error": str(e)}


# ──────────────────────────────────────────────────────────────────────────────
# pathway_validity  (weight 1)
# Pathway names must exist in MSigDB/Reactome/GO/KEGG; bonus for ORA enrichment
# ──────────────────────────────────────────────────────────────────────────────

def score_pathway_validity(
    pathway_evidence: list[str],
    top_genes: list[str],
    genesets_dir: Path,
) -> tuple[float, dict]:
    if not pathway_evidence:
        return 0.0, {"reason": "no pathway evidence submitted"}
    try:
        all_pathways, gene_sets = _load_all_genesets(genesets_dir)

        # Name validity — match against GMT names with space/underscore normalization.
        # Agents sometimes write "REACTOME INNATE_IMMUNE_SYSTEM" (space before module)
        # instead of the canonical "REACTOME_INNATE_IMMUNE_SYSTEM"; normalizing catches these.
        def _normalize(s: str) -> str:
            return s.upper().strip().replace(" ", "_")

        normalized_pathways = {_normalize(n): n for n in all_pathways}

        valid = []
        for pw in pathway_evidence:
            pw_norm = _normalize(pw)
            pw_upper = pw.upper().strip()
            match = (
                # Original substring match (exact GMT name embedded in string)
                any(pw_upper in name or name in pw_upper for name in all_pathways)
                or
                # Normalized match (handles space↔underscore variations)
                any(norm in pw_norm or pw_norm in norm for norm in normalized_pathways)
            )
            if match:
                valid.append(pw)

        validity_rate = len(valid) / len(pathway_evidence)

        # ORA bonus: do valid pathways enrich in top_genes?
        ora_score = 0.0
        if valid and top_genes and gene_sets:
            universe_size = 20000
            top_set = set(top_genes)
            ora_hits = 0
            for pw in valid:
                pw_upper = pw.upper().strip()
                pw_norm = _normalize(pw)
                matched_gs = next(
                    (gs for name, gs in gene_sets.items()
                     if pw_upper in name or name in pw_upper
                     or pw_norm in _normalize(name) or _normalize(name) in pw_norm), None
                )
                if matched_gs is None:
                    continue
                from scipy.stats import hypergeom
                k = len(top_set & matched_gs)
                M = universe_size
                n = len(matched_gs)
                N = len(top_set)
                if k > 0:
                    p = hypergeom.sf(k - 1, M, n, N)
                    if p < 0.05:
                        ora_hits += 1
            ora_score = float(np.clip(ora_hits / max(len(valid), 1), 0, 1))

        score = 0.6 * validity_rate + 0.4 * ora_score
        return float(score), {
            "n_submitted": len(pathway_evidence),
            "n_valid": len(valid),
            "validity_rate": validity_rate,
            "ora_score": ora_score,
        }
    except Exception as e:
        return 0.0, {"error": str(e)}


def _load_all_genesets(genesets_dir: Path) -> tuple[set[str], dict[str, set[str]]]:
    all_names: set[str] = set()
    gene_sets: dict[str, set[str]] = {}
    for gmt in Path(genesets_dir).glob("**/*.gmt"):
        try:
            with open(gmt) as f:
                for line in f:
                    parts = line.strip().split("\t")
                    if len(parts) < 3:
                        continue
                    name = parts[0].upper()
                    genes = set(parts[2:])
                    all_names.add(name)
                    gene_sets[name] = genes
        except Exception:
            pass
    return all_names, gene_sets


# ──────────────────────────────────────────────────────────────────────────────
# p2_commit_quality  (Phase 2, weight 1)
# Check that the commit report contains all 5 required analysis sections.
# ──────────────────────────────────────────────────────────────────────────────

def score_exam_data_lock_quality(commit_report: str) -> tuple[float, dict]:
    if not commit_report:
        return 0.0, {"reason": "no commit report submitted"}

    r = commit_report.lower()

    sections = {
        "pc_loadings": bool(re.search(
            r"pc[\s_]?[23]\b|pc2|pc3|principal component [23]|loading", r
        )),
        "survival": bool(re.search(
            r"median.*survival|survival.*median|log.rank|kaplan|hazard ratio|\bhr\b.*=|\bci\b", r
        )),
        "mutation": bool(re.search(
            r"mutation|fisher.*exact|odds ratio|mutant|mutation rate|enriched.*gene", r
        )),
        "rppa": bool(re.search(
            r"rppa|protein.*diff|phospho|mann.whitn|clinical.*variable", r
        )),
        "unexpected": bool(re.search(
            r"unexpected|surprise|surprising|expected instead|contrary|most.*surprise", r
        )),
    }

    n_found = sum(sections.values())
    score = float(n_found / len(sections))
    return score, {
        "sections_found": [k for k, v in sections.items() if v],
        "sections_missing": [k for k, v in sections.items() if not v],
        "n_sections": n_found,
        "coverage": score,
    }
