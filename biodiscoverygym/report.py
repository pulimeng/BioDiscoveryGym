"""
Generate a markdown episode report from an EpisodeResult + metadata.
"""

from __future__ import annotations

from collections import Counter
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from biodiscoverygym.episode import EpisodeResult


def generate_markdown(
    result: "EpisodeResult",
    episode_id: str,
    cohort: str,
    model: str,
    seed: int,
) -> str:
    d = result.discovery or {}
    grouping = d.get("proposed_grouping", {})
    subtype_counts = Counter(grouping.values())

    lines: list[str] = []

    # ── Header ──────────────────────────────────────────────────────────
    lines += [
        f"# BioDiscoveryGym Episode Report",
        f"",
        f"| Field | Value |",
        f"|---|---|",
        f"| Episode ID | `{episode_id}` |",
        f"| Cohort | {cohort} |",
        f"| Model | {model} |",
        f"| Seed | {seed} |",
        f"| Wall time | {result.wall_time_s/60:.1f} min |",
        f"| Confidence | {d.get('confidence', 'N/A')} |",
        f"",
    ]

    # ── Subtype distribution ─────────────────────────────────────────────
    lines += ["## Proposed Grouping", ""]
    lines += [f"**{len(grouping)} samples** assigned to {len(subtype_counts)} subtypes:", ""]
    lines += ["| Subtype | Count | % |", "|---|---|---|"]
    for subtype, count in sorted(subtype_counts.items(), key=lambda x: -x[1]):
        pct = 100 * count / len(grouping) if grouping else 0
        lines.append(f"| {subtype} | {count} | {pct:.1f}% |")
    lines.append("")

    # ── Top genes ────────────────────────────────────────────────────────
    lines += ["## Top Marker Genes", ""]
    genes = d.get("top_genes", [])
    lines.append(", ".join(f"`{g}`" for g in genes))
    lines.append("")

    # ── Pathways ─────────────────────────────────────────────────────────
    lines += ["## Pathway Evidence", ""]
    for p in d.get("pathway_evidence", []):
        lines.append(f"- {p}")
    lines.append("")

    # ── Hypothesis ───────────────────────────────────────────────────────
    lines += ["## Mechanistic Hypothesis", ""]
    lines.append(d.get("mechanism_hypothesis", "N/A"))
    lines.append("")

    # ── Next experiment ───────────────────────────────────────────────────
    lines += ["## Proposed Next Experiment", ""]
    lines.append(d.get("next_experiment", "N/A"))
    lines.append("")

    # ── Full conversation log ─────────────────────────────────────────────
    if result.messages:
        lines += ["---", "", "## Full Analysis Log", ""]
        turn = 0
        code_call = 0
        for msg in result.messages:
            role = msg.get("role", "")
            content = msg.get("content", "")

            if role == "user":
                if isinstance(content, str):
                    continue  # skip the initial "Begin." message
                # tool results
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "tool_result":
                        output = block.get("content", "")
                        if output and output != "Submission received. Episode complete.":
                            lines += [
                                "<details>",
                                f"<summary>Output</summary>",
                                "",
                                "```",
                                output[:3000] + ("..." if len(output) > 3000 else ""),
                                "```",
                                "</details>",
                                "",
                            ]

            elif role == "assistant":
                turn += 1
                blocks = content if isinstance(content, list) else []
                for block in blocks:
                    # handle both dict and SDK objects
                    btype = block.get("type") if isinstance(block, dict) else getattr(block, "type", None)

                    if btype == "text":
                        text = block.get("text") if isinstance(block, dict) else getattr(block, "text", "")
                        if text and text.strip():
                            lines += [f"### Turn {turn} — Analysis", "", text.strip(), ""]

                    elif btype == "tool_use":
                        name = block.get("name") if isinstance(block, dict) else getattr(block, "name", "")
                        inp = block.get("input") if isinstance(block, dict) else getattr(block, "input", {})

                        if name == "run_code":
                            code_call += 1
                            code = inp.get("code", "") if isinstance(inp, dict) else ""
                            lines += [
                                f"### Turn {turn} — Code Call #{code_call}",
                                "",
                                "```python",
                                code.strip(),
                                "```",
                                "",
                            ]
                        elif name == "submit_discovery":
                            lines += ["### Submission", "", "> `submit_discovery` called", ""]

    return "\n".join(lines)
