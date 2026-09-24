# Scripts — what to run, and when

> Manuscript-side analysis, figure and report generators moved to `paper/` on 2026-09-11 (`paper/analysis`, `paper/figures`, `paper/reports`; see `paper/README.md`). `scripts/` is production only: running, scoring, judging, data building, audits.


Grouped by job. Anything that spends API credit is marked **$**; those are run by the PI, not by an
assistant.

## Gates — run these before trusting a run

| script | asserts | exit |
|---|---|---|
| `audit_blinding.py` | nothing the **harness** showed the agent reveals identity | 1 on any hit |
| `audit_integrity.py` | the `output_dir` leak + failed identity gates | 1 if a gate errored |
| `check_judge_integrity.py` | every judge output parses, is complete, schema-valid | 1 if corrupt |
| `check_judge_symmetry.py` | the judge sees the same reasoning channel for every model | 1 on asymmetry |

```bash
python scripts/audit_blinding.py <run_dir>      # MUST exit 0 for a blinding claim to stand
python scripts/audit_integrity.py --json out.json
python scripts/check_judge_integrity.py --delete-bad   # removes corrupt so a resume re-judges
```

`audit_blinding.py` is **arm-aware**: G0 discloses the true cohort and G3 a false one *by design*,
so cohort checks are suppressed there; plumbing checks (episode label, results path, arm token,
arm+seed, the word `mislead`) apply to every arm. Validated against known-bad data — 422/450 pilot
episodes fail.

## Running episodes  **$**

| script | |
|---|---|
| `run_episode.py` | single episode |
| `run_tcga.sh` | a full run directory |
| `score_tcga_episode.py` / `score_all_tcga.sh` | outcome scoring, resume-safe |
| `score_sghos_episode.py` / `score_all_sghos.sh` | OS track (parked) |

Both scorers **refuse to write a score file if any LLM judge errored** and exit non-zero — a failed
judge returns `0.0`, which is indistinguishable from a real zero. That defect once produced a
retracted finding; see `docs/DATA_INTEGRITY_AUDIT.md`.

## Process judging  **$**

| script | |
|---|---|
| `summarize_cot.py` | CoT judge, one pass; `--out-suffix` for replicates, records `judge_model` |
| ~~`run_judge_panel.sh`~~ | **archived** &rarr; `scripts/archive/` — replaced by `run_judge.sh`, one judge family per terminal |
| `score_support.py` | support/grounding judge (D1/D2/D3) |
| ~~`cot_compare.py`~~ | **archived** &rarr; `scripts/archive/` — read the flat `*_cotsummary.json`; use `gen_cot_report.py` or `cot_flow.py` |

## Analysis — no API

| script | answers | writes |
|---|---|---|
| `cot_deepdive.py` | H1 (outcome vs derivation), H2 (derivation vs fooled) | `manuscript/figures/cot_stats.json` |
| `shortcut_analysis.py` | how identity is reached, and what it costs | `manuscript/figures/shortcut_stats.json` |
| `extract_cot.py` | trace distiller + `count_based_identity` probe | *(imported, also a CLI)* |
| `episode_resources.py` | tokens in/out and wall-clock **per episode**; `--by-arm`, `--csv` | stdout / CSV |

## Reports — no API

All write to `results/tcga/`.

| script | output |
|---|---|
| `gen_manuscript_report.py` | `MANUSCRIPT_REPORT.html` — paper-shaped summary |
| `gen_cot_report.py` | `COT_REPORT.html` — per-episode CoT deep-dive |
| `gen_summary_report.py` | `SUMMARY.html` — **the narrative summary**: how each model works, a representative episode's hypothesis arc, what the ladder changes, what the judges keep criticising. Charts inline, no p-values. Needs `cot_flow.py` first |
| `cot_flow.py` | `manuscript/figures/cot_flow.json` + `FLOW_REPORT.html` — deterministic process record for all 570 episodes: tool sequence, modalities reached for, methods, confidence trajectory, pivots. **No LLM judge anywhere in it** |
| `gen_hypothesis_report.py` | `HYPOTHESIS_REPORT.html` — renders `cot_stats.json` (H1/H2). An internal validity check, not a paper deliverable: this study is descriptive |
| `svg_charts.py` | inline-SVG chart helpers shared by the reports — no CDN, so a report opened offline still draws |
| `gen_ablation_report.py` | `ABLATION_REPORT.html` — detailed-vs-lean |
| `gen_cost_report.py` | `COST_REPORT.html` — measured tokens; prices in an editable table |
| `gen_ladder_report.py` | `LADDER_3MODEL.html` — per-cohort/modality (`--out` for the lean variant) |

## OS track — parked

`internal_robustness.py`, `target_qc.py`, `process_os_jia2022.py`, `process_target.py`,
`signed_correlation_diagnostic.py`, `calibrate_os_null.py`. See `docs/OS_PHASE3_DIAGNOSIS.md` —
Phase 3 is unwinnable as specified; not being worked on.

## Regenerate everything after a re-score

```bash
python paper/analysis/cot_deepdive.py && python paper/analysis/shortcut_analysis.py
python paper/reports/gen_manuscript_report.py && python paper/reports/gen_cot_report.py
python paper/reports/gen_ablation_report.py && python paper/reports/gen_cost_report.py
```
