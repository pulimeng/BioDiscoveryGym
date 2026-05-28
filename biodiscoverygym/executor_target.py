"""
TargetDiscoveryExecutor: CodeExecutor variant that pre-loads all reference datasets
for target discovery sessions.

All gene identifiers are anonymized to GENE_XXXXX using a single consistent
seed-based mapping applied across every dataset at construction time.

Datasets loaded:
  depmap_crispr  — DepMap CRISPR dependency (cell_lines × GENE_XXXXX)
  depmap_expr    — DepMap RNA expression (cell_lines × GENE_XXXXX)
  depmap_meta    — DepMap cell line metadata (lineage/disease kept)
  gtex_median    — GTEx normal tissue RNA (GENE_XXXXX × tissues)
  gnomad         — gnomAD constraint metrics (GENE_XXXXX × metrics)
  tcga_expr      — TCGA patient tumor RNA (samples × GENE_XXXXX, pan-cancer)
  tcga_mut       — TCGA patient tumor mutations (samples × GENE_XXXXX, binary)
  tcga_meta      — TCGA patient metadata (cancer_type, vital_status, etc.)
  prism_viability— PRISM drug screen (cell_lines × compounds, log fold-change)
  hpa_normal     — HPA protein expression in normal tissues (GENE_XXXXX × tissue_celltype)
  ccle_proteomics— CCLE mass-spec protein abundance (cell_lines × GENE_XXXXX, log2 normalized)
  cosmic_cgc     — COSMIC CGC (GENE_XXXXX × tier/role/somatic/tumour_types)
  cosmic_hallmarks — COSMIC hallmarks per gene (GENE_XXXXX → semicolon-joined hallmark list)
  cosmic_fusions — COSMIC fusion gene pairs (GENE_XXXXX × GENE_XXXXX, n_samples)
  cosmic_resistance — COSMIC drug resistance mutations (GENE_XXXXX, drug_name, mutation_aa)
  cosmic_mut_freq — COSMIC mutation frequency (GENE_XXXXX → n_mutated_samples across all COSMIC)
"""

from __future__ import annotations

import contextlib
import io
import traceback
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from biodiscoverygym.executor import _MAX_OUTPUT_CHARS

# Task B-specific block list. All reference datasets are pre-loaded into the namespace
# with genes anonymized to GENE_XXXXX — the raw files contain real gene symbols, so
# direct file access would allow trivial de-anonymization by column-name lookup.
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

_TCGA_COHORTS = ["brca", "coad", "hnsc", "kirc", "lihc", "luad", "lusc", "ov", "prad", "skcm"]


class TargetDiscoveryExecutor:
    """
    Stateful Python sandbox for target discovery sessions.
    Gene map property exposes GENE_XXXXX → real_symbol for post-hoc evaluation.
    """

    def __init__(
        self,
        data_dir: str | Path = "data",
        output_dir: str | Path | None = None,
        seed: int = 42,
    ):
        data_dir = Path(data_dir)
        self.output_dir = Path(output_dir) if output_dir else Path("results") / "target_misc"
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self._gene_map: dict[str, str] = {}
        self.namespace: dict = self._build_namespace(data_dir, seed)

    @property
    def gene_map(self) -> dict[str, str]:
        """GENE_XXXXX → real gene symbol (for evaluation use only)."""
        return dict(self._gene_map)

    def add_pathway_namespace(self, data_dir: str | Path = "data") -> None:
        """
        Load pathway databases with real gene names and inject into the namespace.
        Called at the start of Phase 3 (gene revelation) — after the anonymized session ends.
        Adds: msigdb_hallmarks, msigdb_kegg, msigdb_reactome, string_ppi, oncokb_genes.
        """
        data_dir = Path(data_dir)
        msigdb_dir = data_dir / "genesets" / "msigdb"
        stringdb_dir = data_dir / "genesets" / "stringdb"
        cancer_genes_dir = data_dir / "cancer_genes"

        self.namespace["msigdb_hallmarks"] = _parse_gmt(
            msigdb_dir / "h.all.v2023.2.Hs.symbols.gmt"
        )
        self.namespace["msigdb_kegg"] = _parse_gmt(
            msigdb_dir / "c2.cp.kegg_medicus.v2023.2.Hs.symbols.gmt"
        )
        self.namespace["msigdb_reactome"] = _parse_gmt(
            msigdb_dir / "c2.cp.reactome.v2023.2.Hs.symbols.gmt"
        )
        self.namespace["string_ppi"] = _load_string_ppi(stringdb_dir / "human_ppi_high_conf.tsv")
        self.namespace["oncokb_genes"] = _load_oncokb(cancer_genes_dir / "oncokb_cancer_gene_list.tsv")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def execute(self, code: str) -> str:
        violation = self._check_blocked_paths(code)
        if violation:
            return f"PermissionError: access to '{violation}' is not permitted."

        buf = io.StringIO()
        try:
            with contextlib.redirect_stdout(buf):
                exec(code, self.namespace)  # noqa: S102
        except Exception:
            return f"Error:\n{traceback.format_exc()}"

        output = buf.getvalue()
        if len(output) > _MAX_OUTPUT_CHARS:
            output = output[:_MAX_OUTPUT_CHARS] + f"\n... [truncated — {len(output)} chars total]"
        return output if output else "(no output)"

    # ------------------------------------------------------------------
    # Namespace construction
    # ------------------------------------------------------------------

    def _build_namespace(self, data_dir: Path, seed: int) -> dict:
        print("  Loading DepMap...", flush=True)
        crispr_raw = _load_csv(data_dir / "depmap" / "CRISPRGeneEffect.csv")
        expr_raw   = _load_csv(data_dir / "depmap" / "OmicsExpressionProteinCodingGenesTPMLogp1.csv")
        meta_raw   = _load_model_meta(data_dir / "depmap" / "Model.csv")

        print("  Loading GTEx...", flush=True)
        gtex_raw = _load_gtex(data_dir / "gtex")

        print("  Loading gnomAD...", flush=True)
        gnomad_raw = _load_gnomad(data_dir / "gnomad")

        print("  Loading TCGA (pan-cancer)...", flush=True)
        tcga_expr_raw, tcga_mut_raw, tcga_meta_raw = _load_tcga(data_dir / "tcga")

        print("  Loading PRISM drug screen...", flush=True)
        prism_raw = _load_prism(data_dir / "prism")

        print("  Loading HPA normal tissue...", flush=True)
        hpa_raw = _load_hpa(data_dir / "hpa")

        print("  Loading CCLE proteomics...", flush=True)
        ccle_prot_raw = _load_ccle_proteomics(data_dir / "ccle_proteomics")

        print("  Loading COSMIC...", flush=True)
        cosmic_dir = data_dir / "cosmic"
        cosmic_cgc_raw        = _load_parquet_indexed(cosmic_dir / "cancer_gene_census.parquet")
        cosmic_hallmarks_raw  = _load_parquet_indexed(cosmic_dir / "hallmarks.parquet")
        cosmic_fusions_raw    = _load_parquet_flat(cosmic_dir / "fusions.parquet")
        cosmic_resistance_raw = _load_parquet_flat(cosmic_dir / "resistance_mutations.parquet")
        cosmic_mut_freq_raw   = _load_parquet_indexed(cosmic_dir / "mutation_freq.parquet")

        # --- build unified gene set across ALL sources ---
        gene_symbols: set[str] = set()
        for df, col_type in [
            (crispr_raw, "depmap"), (expr_raw, "depmap"),
        ]:
            if df is not None:
                gene_symbols.update(_depmap_col_to_symbol(c) for c in df.columns)
        if gtex_raw is not None:
            gene_symbols.update(gtex_raw.index.tolist())
        if gnomad_raw is not None and "gene" in gnomad_raw.columns:
            gene_symbols.update(gnomad_raw["gene"].dropna().tolist())
        if tcga_expr_raw is not None:
            gene_symbols.update(tcga_expr_raw.columns.tolist())
        if tcga_mut_raw is not None:
            gene_symbols.update(tcga_mut_raw.columns.tolist())
        if hpa_raw is not None and "Gene" in hpa_raw.columns:
            gene_symbols.update(hpa_raw["Gene"].dropna().tolist())
        if ccle_prot_raw is not None:
            gene_symbols.update(ccle_prot_raw.columns.tolist())
        if cosmic_cgc_raw is not None:
            gene_symbols.update(cosmic_cgc_raw.index.tolist())
        if cosmic_hallmarks_raw is not None:
            gene_symbols.update(cosmic_hallmarks_raw.index.tolist())
        if cosmic_fusions_raw is not None:
            for col in ("gene_5prime", "gene_3prime"):
                if col in cosmic_fusions_raw.columns:
                    gene_symbols.update(cosmic_fusions_raw[col].dropna().tolist())
        if cosmic_resistance_raw is not None and "gene" in cosmic_resistance_raw.columns:
            gene_symbols.update(cosmic_resistance_raw["gene"].dropna().tolist())
        if cosmic_mut_freq_raw is not None:
            gene_symbols.update(cosmic_mut_freq_raw.index.tolist())

        gene_symbols.discard("")
        sorted_genes = sorted(gene_symbols)
        rng = np.random.default_rng(seed)
        perm = rng.permutation(len(sorted_genes))
        anon_ids = [f"GENE_{i:05d}" for i in perm]
        real_to_anon: dict[str, str] = dict(zip(sorted_genes, anon_ids))
        self._gene_map = {v: k for k, v in real_to_anon.items()}

        print(f"  Gene map: {len(real_to_anon):,} genes → GENE_XXXXX", flush=True)

        # --- apply anonymization ---
        depmap_crispr = _anonymize_depmap_cols(crispr_raw, real_to_anon)
        depmap_expr   = _anonymize_depmap_cols(expr_raw, real_to_anon)
        gtex_median   = _anonymize_index(gtex_raw, real_to_anon)
        gnomad        = _anonymize_gnomad(gnomad_raw, real_to_anon)
        tcga_expr     = _anonymize_cols(tcga_expr_raw, real_to_anon)
        tcga_mut      = _anonymize_cols(tcga_mut_raw, real_to_anon)
        hpa_normal    = _anonymize_hpa(hpa_raw, real_to_anon)
        ccle_proteomics   = _anonymize_cols(ccle_prot_raw, real_to_anon)
        cosmic_cgc        = _anonymize_index(cosmic_cgc_raw, real_to_anon)
        cosmic_hallmarks  = _anonymize_index(cosmic_hallmarks_raw, real_to_anon)
        cosmic_fusions    = _anonymize_fusion_cols(cosmic_fusions_raw, real_to_anon)
        cosmic_resistance = _anonymize_resistance(cosmic_resistance_raw, real_to_anon)
        cosmic_mut_freq   = _anonymize_index(cosmic_mut_freq_raw, real_to_anon)

        ns: dict = {
            # DepMap
            "depmap_crispr": depmap_crispr,
            "depmap_expr":   depmap_expr,
            "depmap_meta":   meta_raw,
            # Normal tissue
            "gtex_median":   gtex_median,
            "hpa_normal":    hpa_normal,
            # Population genetics
            "gnomad":        gnomad,
            # Patient tumors
            "tcga_expr":     tcga_expr,
            "tcga_mut":      tcga_mut,
            "tcga_meta":     tcga_meta_raw,
            # Drug screens
            "prism_viability": prism_raw,
            # Proteomics
            "ccle_proteomics": ccle_proteomics,
            # COSMIC cancer gene annotations
            "cosmic_cgc":        cosmic_cgc,
            "cosmic_hallmarks":  cosmic_hallmarks,
            "cosmic_fusions":    cosmic_fusions,
            "cosmic_resistance": cosmic_resistance,
            "cosmic_mut_freq":   cosmic_mut_freq,
            # Utilities
            "output_dir":    self.output_dir,
            "pd":  pd,
            "np":  np,
            "plt": plt,
            "matplotlib": matplotlib,
        }
        return ns

    @staticmethod
    def _check_blocked_paths(code: str) -> str | None:
        for blocked in _BLOCKED_SUBSTRINGS:
            if blocked in code:
                return blocked
        return None


# ------------------------------------------------------------------
# Data loading helpers
# ------------------------------------------------------------------

def _load_csv(path: Path) -> pd.DataFrame | None:
    if not path.exists():
        return None
    return pd.read_csv(path, index_col=0)


def _load_model_meta(path: Path) -> pd.DataFrame | None:
    if not path.exists():
        return None
    df = pd.read_csv(path)
    keep = [
        "ModelID", "OncotreeLineage", "OncotreePrimaryDisease", "OncotreeSubtype",
        "Age", "AgeCategory", "Sex", "PrimaryOrMetastasis", "SampleCollectionSite",
    ]
    keep = [c for c in keep if c in df.columns]
    return df[keep].set_index("ModelID") if "ModelID" in keep else df[keep]


def _load_gtex(gtex_dir: Path) -> pd.DataFrame | None:
    p = gtex_dir / "gene_median_tpm.parquet"
    if p.exists():
        return pd.read_parquet(p)
    gct = gtex_dir / "gene_median_tpm.gct.gz"
    if not gct.exists():
        return None
    try:
        df = pd.read_csv(gct, sep="\t", skiprows=2, index_col=0)
        if "Description" in df.columns:
            df = df.drop(columns=["Description"])
        return df
    except Exception:
        return None


def _load_gnomad(gnomad_dir: Path) -> pd.DataFrame | None:
    for fname in ("gnomad.v2.1.1.lof_metrics.by_gene.tsv", "gnomad.v4.1.constraint_metrics.tsv"):
        p = gnomad_dir / fname
        if p.exists():
            return pd.read_csv(p, sep="\t", low_memory=False)
    return None


def _load_tcga(tcga_dir: Path) -> tuple[pd.DataFrame | None, pd.DataFrame | None, pd.DataFrame | None]:
    if not tcga_dir.exists():
        return None, None, None

    expr_frames, mut_frames, meta_rows = [], [], []
    for cohort in _TCGA_COHORTS:
        cdir = tcga_dir / cohort
        expr_p = cdir / "expression.parquet"
        mut_p  = cdir / "mutations.parquet"
        clin_p = cdir / f"{cohort.upper()}_clinical.tsv"

        if not expr_p.exists():
            continue

        expr = pd.read_parquet(expr_p).astype("float32")
        expr.index = [f"{cohort.upper()}::{s}" for s in expr.index]
        expr_frames.append(expr)

        if mut_p.exists():
            mut = pd.read_parquet(mut_p).astype("float32")
            mut.index = [f"{cohort.upper()}::{s}" for s in mut.index]
            mut_frames.append(mut)

        if clin_p.exists():
            clin = pd.read_csv(clin_p, sep="\t", index_col=0)
            clin.index = [f"{cohort.upper()}::{s}" for s in clin.index]
            clin.insert(0, "cancer_type", cohort.upper())
            meta_rows.append(clin)

    if not expr_frames:
        return None, None, None

    tcga_expr = pd.concat(expr_frames, axis=0, join="inner")
    tcga_mut  = pd.concat(mut_frames,  axis=0, join="inner") if mut_frames  else None
    tcga_meta = pd.concat(meta_rows,   axis=0, join="outer") if meta_rows   else None

    return tcga_expr, tcga_mut, tcga_meta


def _load_prism(prism_dir: Path) -> pd.DataFrame | None:
    lfc_path = prism_dir / "secondary-screen-replicate-collapsed-logfold-change.csv"
    if not lfc_path.exists():
        return None
    # Rows are already ACH-XXXXXX IDs
    return pd.read_csv(lfc_path, index_col=0)


def _parse_gmt(path: Path) -> dict[str, list[str]]:
    """Parse MSigDB GMT file → {pathway_name: [gene_list]}."""
    if not path.exists():
        return {}
    result = {}
    for line in path.read_text().splitlines():
        parts = line.strip().split("\t")
        if len(parts) < 3:
            continue
        result[parts[0]] = parts[2:]
    return result


def _load_string_ppi(path: Path) -> pd.DataFrame | None:
    """Load pre-filtered STRING PPI (gene1, gene2, combined_score)."""
    if not path.exists():
        return None
    return pd.read_csv(path, sep="\t")


def _load_oncokb(path: Path) -> pd.DataFrame | None:
    """Load OncoKB cancer gene list → DataFrame with gene and gene_type columns."""
    if not path.exists():
        return None
    df = pd.read_csv(path, sep="\t")
    col_map = {}
    for c in df.columns:
        if "hugo" in c.lower() or (c.lower() == "gene symbol"):
            col_map[c] = "gene"
        elif "gene type" in c.lower():
            col_map[c] = "gene_type"
    df = df.rename(columns=col_map)
    keep = [c for c in ("gene", "gene_type") if c in df.columns]
    return df[keep].dropna(subset=["gene"]) if keep else df


def _load_parquet_indexed(path: Path) -> pd.DataFrame | None:
    """Load a parquet that is already indexed by gene symbol."""
    return pd.read_parquet(path) if path.exists() else None


def _load_parquet_flat(path: Path) -> pd.DataFrame | None:
    """Load a parquet with no special index (flat row table)."""
    return pd.read_parquet(path) if path.exists() else None


def _load_ccle_proteomics(ccle_dir: Path) -> pd.DataFrame | None:
    """
    Load CCLE proteomics (Nusinow et al. 2020).

    Raw format: proteins × (metadata + CELLLINE_TISSUE_TenPxNN columns)
    Output: cell_lines × gene_symbols DataFrame (log2 normalized abundance, ACH- index)

    Cell line mapping uses data/depmap/Model.csv to convert CCLE names → ACH IDs.
    Duplicate gene symbols are resolved by keeping the row with the most non-NaN values.
    """
    p = ccle_dir / "protein_quant_current_normalized.csv.gz"
    if not p.exists():
        p = ccle_dir / "protein_quant_current_normalized.csv"
    if not p.exists():
        return None

    META_COLS = {"Protein_Id", "Gene_Symbol", "Description", "Group_ID", "Uniprot", "Uniprot_Acc"}
    df = pd.read_csv(p)
    df.columns = df.columns.str.strip('"')

    gene_col = "Gene_Symbol" if "Gene_Symbol" in df.columns else "Gene_name"
    if gene_col not in df.columns:
        return None

    # Identify data columns (not metadata, not peptide-count columns)
    data_cols = [c for c in df.columns if c not in META_COLS and not c.endswith("_Peptides")]
    if not data_cols:
        return None

    df = df[[gene_col] + data_cols].copy()
    df[gene_col] = df[gene_col].str.strip()
    df = df.dropna(subset=[gene_col])

    # Deduplicate: keep the row with the most non-NaN values per gene
    df["_n_valid"] = df[data_cols].notna().sum(axis=1)
    df = df.sort_values("_n_valid", ascending=False).drop_duplicates(subset=gene_col)
    df = df.drop(columns=["_n_valid"]).set_index(gene_col)

    # Transpose → cell_lines × genes; strip TenPxNN suffix from column names
    mat = df.T.copy()
    mat.index = mat.index.str.replace(r"_TenPx\d+$", "", regex=True)

    # Map CCLE names → DepMap ACH IDs using Model.csv (best-effort)
    model_path = p.parent.parent / "depmap" / "Model.csv"
    if model_path.exists():
        try:
            model = pd.read_csv(model_path, usecols=["ModelID", "CCLEName"]).dropna()
            ccle_to_ach = dict(zip(model["CCLEName"], model["ModelID"]))
            mat.index = [ccle_to_ach.get(idx, idx) for idx in mat.index]
        except Exception:
            pass

    mat = mat.astype("float32")
    mat.index.name = "ModelID"
    mat.columns.name = None
    return mat


def _load_hpa(hpa_dir: Path) -> pd.DataFrame | None:
    p = hpa_dir / "normal_tissue.tsv"
    if not p.exists():
        return None
    return pd.read_csv(p, sep="\t", low_memory=False)


# ------------------------------------------------------------------
# Anonymization helpers
# ------------------------------------------------------------------

def _depmap_col_to_symbol(col: str) -> str:
    """'BRCA1 (672)' → 'BRCA1'"""
    return col.split(" (")[0].strip()


def _anonymize_depmap_cols(df: pd.DataFrame | None, real_to_anon: dict) -> pd.DataFrame | None:
    if df is None:
        return None
    return df.rename(columns={c: real_to_anon.get(_depmap_col_to_symbol(c), c) for c in df.columns})


def _anonymize_cols(df: pd.DataFrame | None, real_to_anon: dict) -> pd.DataFrame | None:
    """Anonymize DataFrames where gene symbols are column names (TCGA style)."""
    if df is None:
        return None
    return df.rename(columns={c: real_to_anon.get(c, c) for c in df.columns})


def _anonymize_index(df: pd.DataFrame | None, real_to_anon: dict) -> pd.DataFrame | None:
    """Anonymize DataFrames where gene symbols are in the index (GTEx style)."""
    if df is None:
        return None
    df = df.copy()
    df.index = [real_to_anon.get(g, g) for g in df.index]
    return df


def _anonymize_gnomad(df: pd.DataFrame | None, real_to_anon: dict) -> pd.DataFrame | None:
    if df is None or "gene" not in df.columns:
        return df
    keep = ["gene", "pLI", "oe_lof_upper", "oe_lof_upper_bin", "obs_lof", "exp_lof"]
    keep = [c for c in keep if c in df.columns]
    df = df[keep].copy()
    df["gene"] = df["gene"].map(lambda g: real_to_anon.get(g, g))
    return df.set_index("gene")


def _anonymize_fusion_cols(df: pd.DataFrame | None, real_to_anon: dict) -> pd.DataFrame | None:
    """Anonymize gene_5prime and gene_3prime columns in the fusions table."""
    if df is None:
        return None
    df = df.copy()
    for col in ("gene_5prime", "gene_3prime"):
        if col in df.columns:
            df[col] = df[col].map(lambda g: real_to_anon.get(g, g))
    return df


def _anonymize_resistance(df: pd.DataFrame | None, real_to_anon: dict) -> pd.DataFrame | None:
    """Anonymize the gene column in the resistance mutations table."""
    if df is None or "gene" not in df.columns:
        return df
    df = df.copy()
    df["gene"] = df["gene"].map(lambda g: real_to_anon.get(g, g))
    return df


def _anonymize_hpa(df: pd.DataFrame | None, real_to_anon: dict) -> pd.DataFrame | None:
    """
    HPA format: Gene | Gene name | Tissue | Cell type | Level | Reliability
    Output: pivot table GENE_XXXXX × 'tissue__celltype', values = numeric level
    """
    if df is None:
        return None
    level_map = {"Not detected": 0, "Low": 1, "Medium": 2, "High": 3}
    df = df.copy()
    gene_col = "Gene" if "Gene" in df.columns else "Gene name"
    df[gene_col] = df[gene_col].map(lambda g: real_to_anon.get(str(g), str(g)))
    df["tissue_cell"] = df["Tissue"].str.strip() + "__" + df["Cell type"].str.strip()
    df["level_num"] = df["Level"].map(level_map).fillna(-1).astype(int)
    # Keep only reliable entries
    if "Reliability" in df.columns:
        df = df[df["Reliability"].isin(["Enhanced", "Supported", "Approved"])]
    pivot = df.pivot_table(
        index=gene_col, columns="tissue_cell", values="level_num",
        aggfunc="max", fill_value=-1,
    )
    return pivot
