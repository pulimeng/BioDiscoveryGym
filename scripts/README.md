# Scripts (v2)

Grouped by job. Run everything from the repo root. Anything that spends API credit is marked **$**;
the PI launches those. Scripts find the repo root themselves (the folder holding `setup.py`), so the
folder depth does not matter.

```
scripts/
  run/      run_episode.py, run_tcga.sh            episodes                          $
  audit/    audit_blinding.py, g3_exposure.py      blinding + label-delivery gate
  score/    score_tcga_episode.py, score_all_tcga.sh   outcome scoring              $ (LLM parts)
  judge/    run_evidence_judge.py                  v2 evidence-support judge        $ (gateway)
  report/   v2_report.py, episode_resources.py     judge-free reports
  data/     process_tcga.py, perturb_lihc.py, download_all.sh, download/   data building
  tools/    list_models.py                         provider catalogues
```

Judge routing and score-file names (`judges_config`) are library code:
`biodiscoverygym/scoring/judges_config.py`.

## run/  **$**

| script | |
|---|---|
| `run_episode.py` | one episode; output defaults to `results/v2/` |
| `run_tcga.sh` | a run directory under `results/v2/<tag>`; `--group`, `--cohorts OV,LUSC`, `--model`, `--dry-run` |

## audit/  (run before trusting a run)

| script | asserts | exit |
|---|---|---|
| `audit_blinding.py` | nothing the harness showed the agent reveals the cohort; labels arrived at the arm's gate | 1 on any hit |
| `g3_exposure.py` | locates the label delivery (`check_disclosure`); imported by `audit_blinding.py` | |

```bash
python scripts/audit/audit_blinding.py <run_dir>     # must exit 0 for a blinding claim to stand
python scripts/audit/audit_blinding.py --self-test
```

## score/  **$** (LLM components)

| script | |
|---|---|
| `score_tcga_episode.py` | one episode; `--skip-llm` for the deterministic parts only; adds the protocol check |
| `score_all_tcga.sh` | a run directory, resume-safe, `--rescore` to overwrite |

Both refuse to write a score file if any LLM judge errored.

## judge/  **$** (institutional gateway, campus network)

| script | |
|---|---|
| `run_evidence_judge.py` | does the evidence an agent cited support its claim? `--swap` adds the sensitivity test; writes `<run_dir>/_judging/evidence_<judge>.jsonl` |

## report/

| script | |
|---|---|
| `v2_report.py` | protocol compliance, label exposure, identity timing, basis-vs-visibility and anchoring flags; `--calls` lists every call and its code |
| `episode_resources.py` | tokens, turns and timing per episode (no prices) |

## data/

| script | |
|---|---|
| `process_tcga.py` | builds the TCGA cohort files under `data/` |
| `perturb_lihc.py` | perturbed LIHC files for `run_episode.py --perturb` |
| `download_all.sh`, `download/` | source downloads |

## tools/

| script | |
|---|---|
| `list_models.py` | the model ids each provider serves (check before adding one to `biodiscoverygym/models.py`) |
