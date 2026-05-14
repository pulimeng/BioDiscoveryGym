# BioDiscoveryGym

A benchmark for evaluating LLM agents on open-ended cancer biology discovery tasks.

---

## Overview

BioDiscoveryGym tests whether frontier language models can perform **genuine data-driven biological discovery** — or whether correct answers are produced primarily by recalling training knowledge. It does this by controlling how much identity information is available to the agent and measuring whether reasoning quality degrades when recall is blocked.

Two benchmark tasks:

| Task | Description |
|------|-------------|
| **Task A: Cohort Analysis** | Given an anonymized patient cohort (expression ± mutations ± RPPA), discover molecular subtypes without being told the cancer type, number of groups, or scoring criteria |
| **Task B: Target Discovery** | Given population-scale cancer dependency and normal tissue data, reason to a computationally supported therapeutic target without being told what criteria define a good target |

---

## Key Design Features

- **5-layer identity blinding** — cancer-type columns stripped, demographics removed, sample IDs → `SAMPLE_XXXX`, gene symbols → `GENE_XXXXX`, data served from neutral path
- **4 experimental groups** — G0 (explicit retrieval ceiling), G1 (implicit retrieval), G2 (data-driven blind phase), G3 (mislead — wrong barcodes injected)
- **Post-hoc v2 scoring** — 9 components, 18 points max; quantitative + LLM judge; agent never sees scoring criteria
- **Multi-model** — designed to run across Claude, GPT, and Gemini model families

---

## Setup

```bash
conda env create -f environment.yaml
conda activate biodiscoverygym
pip install -e .
export ANTHROPIC_API_KEY="sk-..."

# Download data (~50 GB total)
bash scripts/download_all.sh
```

See [SETUP.md](SETUP.md) for detailed data setup instructions.

---

## Running Benchmarks

```bash
# Task A — full benchmark (67 runs × 5 models)
bash taskA.sh              # all groups
bash taskA.sh --group G2   # single group
bash taskA.sh --dry-run    # preview commands

# Single episode
python scripts/run_episode.py --cohort BRCA --seed 42 --save-log results/ep.json

# Score an episode
python scripts/score_episode_v2.py results/ep.json --save

# Task B — target discovery
python scripts/run_target_discovery.py --indication "Acute Myeloid Leukemia" --save-log results/aml.json
```

---

## Models

| Model | Family | API ID |
|-------|--------|--------|
| Claude Sonnet 4.6 | Claude | `claude-sonnet-4-6` |
| Claude Opus 4.7 | Claude | `claude-opus-4-7` |
| GPT-5.4 | OpenAI | `gpt-5.4-2026-03-05` |
| GPT-5.5 | OpenAI | `gpt-5.5-2026-04-23` |
| Gemini 3.1 Pro | Google | `gemini-3.1-pro` |

Override model: `TASK_A_MODEL=claude-opus-4-7 bash taskA.sh`

---

## Docs

- [`docs/GRAND_DESIGN.md`](docs/GRAND_DESIGN.md) — architecture overview
- [`docs/TASK_A_COHORT.md`](docs/TASK_A_COHORT.md) — Task A full design and empirical findings
- [`docs/BENCHMARK_PLAN.md`](docs/BENCHMARK_PLAN.md) — multi-model benchmark plan and budget
- [`docs/PROGRESS.md`](docs/PROGRESS.md) — current status and resume commands

---

## Tests

```bash
pytest tests/ -v
```
