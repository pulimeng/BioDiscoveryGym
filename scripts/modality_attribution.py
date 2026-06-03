"""
Modality attribution scan — post-hoc analysis of run7 traces.

For each episode, walks every run_code call and record_observation call and
classifies which data modalities were actively used (not just available).

Modalities tracked:
  expression  — expression DataFrame, PCA, DEG, variance
  mutation    — mutation DataFrame, mutation rates, Fisher tests
  methylation — methylation DataFrame, CpG analysis, beta values
  cna         — cna DataFrame, copy number, amplification/deletion
  multimodal  — multimodal_cluster(), SNF, MOFA, concat_pca

Output:
  - Per-episode table: n_code_calls per modality, % calls using each modality
  - Aggregate across all runs
  - Finding-level breakdown: which stage used which modality
"""

from __future__ import annotations

import json
import re
from pathlib import Path

RESULTS_DIR = Path("results/external/run7_unified")

# Regex patterns to detect active use of each modality in run_code blocks
MODALITY_PATTERNS = {
    "expression": re.compile(
        r"\bexpression\b(?!\s*is\s*None)|\bexpr\b|\bpca\b|PCA\b|top_var|variance|log2|cpm|deg\b|differential.*express",
        re.IGNORECASE,
    ),
    "mutation": re.compile(
        r"\bmutation\b(?!\s*is\s*None)|\bmut\b|\bfisher\b|mut_rate|somatic|variant|oncokb|mutated|snv\b",
        re.IGNORECASE,
    ),
    "methylation": re.compile(
        r"\bmethylation\b(?!\s*is\s*None)|\bmeth\b|\bcpg\b|beta.*value|delta.*beta|promoter.*methyl|hypermethyl",
        re.IGNORECASE,
    ),
    "cna": re.compile(
        r"\bcna\b(?!\s*is\s*None)|copy.*number|amplif|delet.*focal|gistic|\bcnv\b",
        re.IGNORECASE,
    ),
    "multimodal": re.compile(
        r"multimodal_cluster|mofa|snf\b|concat_pca|multi.*modal|integrat.*modal",
        re.IGNORECASE,
    ),
}

# Keywords in record_observation evidence_for strings
FINDING_PATTERNS = {
    "expression": re.compile(r"express|pca|pc[0-9]|log2fc|deg|variance|cluster|subtype|survival", re.IGNORECASE),
    "mutation": re.compile(r"mutati|tp53|rb1|atrx|h3f3a|somatic|driver.*gene|oncokb", re.IGNORECASE),
    "methylation": re.compile(r"methylat|cpg|beta|promoter.*hyper|epigeneti", re.IGNORECASE),
    "cna": re.compile(r"copy.*number|amplif|cdkn2a|mdm2|deletion.*focal|gistic|cna\b", re.IGNORECASE),
}


def classify_code(code: str) -> list[str]:
    """Return list of modalities actively used in a code snippet."""
    return [mod for mod, pat in MODALITY_PATTERNS.items() if pat.search(code)]


def classify_finding(text: str) -> list[str]:
    """Return list of modalities evidenced in an observation string."""
    return [mod for mod, pat in FINDING_PATTERNS.items() if pat.search(text)]


def scan_episode(ep_path: Path) -> dict:
    data = json.load(open(ep_path))
    label = ep_path.stem
    msgs = data.get("messages", [])

    code_calls: list[dict] = []        # {call_n, modalities, code_snippet}
    observations: list[dict] = []      # {stage_hint, modalities, evidence_for}

    call_n = 0
    for m in msgs:
        content = m.get("content", [])
        if not isinstance(content, list):
            continue
        for b in content:
            if not isinstance(b, dict):
                continue
            if b.get("type") == "tool_use":
                name = b.get("name", "")
                inp = b.get("input", {})
                if name == "run_code":
                    code = inp.get("code", "")
                    mods = classify_code(code)
                    # Extract stage hint from WHY comment
                    why_match = re.search(r"# WHY:(.*?)(?:\n|$)", code)
                    why = why_match.group(1).strip() if why_match else ""
                    code_calls.append({"call_n": call_n, "modalities": mods, "why": why})
                    call_n += 1
                elif name == "record_observation":
                    ev_for = inp.get("evidence_for", [])
                    hyp    = inp.get("current_hypothesis", "")
                    all_text = " ".join(ev_for) + " " + hyp
                    mods = classify_finding(all_text)
                    observations.append({"modalities": mods, "evidence_for": ev_for})

    # Per-modality code call counts
    total_code = len(code_calls)
    mod_code_counts: dict[str, int] = {m: 0 for m in MODALITY_PATTERNS}
    for c in code_calls:
        for m in c["modalities"]:
            mod_code_counts[m] += 1

    # Per-modality observation counts
    mod_obs_counts: dict[str, int] = {m: 0 for m in FINDING_PATTERNS}
    for o in observations:
        for m in o["modalities"]:
            mod_obs_counts[m] += 1

    return {
        "label": label,
        "total_code_calls": total_code,
        "total_observations": len(observations),
        "code_counts": mod_code_counts,
        "obs_counts": mod_obs_counts,
        "code_calls": code_calls,
    }


def main():
    ep_files = sorted(
        f for f in RESULTS_DIR.rglob("*.json")
        if "v3scores" not in f.name and "trace" not in f.name
        and "codebook" not in f.name and "grouping" not in f.name
        and "gene_map" not in f.name and f.name.startswith("os_")
    )

    if not ep_files:
        print(f"No episode files found in {RESULTS_DIR}")
        return

    results = [scan_episode(f) for f in ep_files]
    results.sort(key=lambda r: r["label"])

    # ── Per-episode table ─────────────────────────────────────────────────────
    mods = list(MODALITY_PATTERNS.keys())
    print(f"\n{'='*70}")
    print(f"  Modality Attribution — run7_unified  ({len(results)} episodes)")
    print(f"{'='*70}")
    print(f"\n{'label':<28} {'calls':>6}", end="")
    for m in mods:
        print(f"  {m[:5]:>5}", end="")
    print(f"  {'obs':>4}", end="")
    for m in ["expression","mutation","methylation","cna"]:
        print(f"  {m[:4]:>4}", end="")
    print()
    print("-" * 70)

    for r in results:
        n = r["total_code_calls"]
        short = r["label"].replace("_run7_unified","")
        print(f"{short:<28} {n:>6}", end="")
        for m in mods:
            cnt = r["code_counts"][m]
            pct = int(100 * cnt / n) if n else 0
            print(f"  {pct:>4}%", end="")
        print(f"  {r['total_observations']:>4}", end="")
        for m in ["expression","mutation","methylation","cna"]:
            print(f"  {r['obs_counts'][m]:>4}", end="")
        print()

    # ── Group means ───────────────────────────────────────────────────────────
    print("\nGroup means (% of code calls using modality):")
    for grp in ["g0","g1","g2"]:
        grp_r = [r for r in results if r["label"].startswith(f"os_{grp}")]
        if not grp_r:
            continue
        print(f"  {grp}:", end="")
        for m in mods:
            vals = [100 * r["code_counts"][m] / r["total_code_calls"]
                    for r in grp_r if r["total_code_calls"] > 0]
            print(f"  {m}={sum(vals)/len(vals):.0f}%", end="")
        print()

    # ── Modality sequence per episode ─────────────────────────────────────────
    print("\n\nModality usage sequence (first 15 code calls per episode):")
    print("  expr=E  mut=M  meth=T  cna=C  multi=X  none=.")
    for r in results:
        short = r["label"].replace("_run7_unified","")
        seq = []
        for c in r["code_calls"][:15]:
            mset = set(c["modalities"])
            if not mset:
                seq.append(".")
            else:
                s = ""
                if "expression" in mset:   s += "E"
                if "mutation" in mset:     s += "M"
                if "methylation" in mset:  s += "T"
                if "cna" in mset:          s += "C"
                if "multimodal" in mset:   s += "X"
                seq.append(s)
        print(f"  {short:<28} {'|'.join(seq)}")

    # ── Mutation/CNA/methylation usage stats ──────────────────────────────────
    print("\n\nNon-expression modality usage summary:")
    for m in ["mutation","methylation","cna","multimodal"]:
        users = [r["label"].replace("_run7_unified","")
                 for r in results if r["code_counts"][m] > 0]
        non_users = [r["label"].replace("_run7_unified","")
                     for r in results if r["code_counts"][m] == 0]
        print(f"\n  {m}:")
        print(f"    Used in {len(users)}/{len(results)} episodes: {', '.join(users) if users else 'none'}")
        if non_users:
            print(f"    NOT used: {', '.join(non_users)}")

    print()


if __name__ == "__main__":
    main()
