# scripts/archive — superseded tooling, kept for the record

Nothing here is wired into the current pipeline. These files are kept because they document how a
result was originally produced, not because they still run. **Every one of them targets a layout or
a design that no longer exists**, so running one today either fails loudly or writes artifacts that
no reader looks at.

Archived 2026-08-25, with the reason:

| file | superseded by | why it was retired |
|---|---|---|
| `run_judge_panel.sh` | `scripts/run_judge.sh` | ran three replicates of ONE judge model into the flat `_cotsummary_j2/_j3` names. The study now runs one pass by each of three families into `<ep>/scoring/<judge>/`. It already exited 2 with a RETIRED banner. |
| `cot_compare.py` | `scripts/gen_cot_report.py`, `scripts/cot_flow.py` | globs `*_cotsummary.json`, the pre-reorg flat name. Exits loudly with "no _cotsummary.json found", so it was never silently wrong — just dead. |
| `resume_support.sh` | nothing needed | deleted *stale pre-migration* `_supportscores.json` files by mtime so a resume would re-judge them. That migration completed in `cca09cd`; the files it targets no longer exist, and an mtime-based delete against the current layout is a hazard rather than a tool. |
| `proto_belief_metrics.py` | `scripts/cot_flow.py` | the 63-episode prototype of the belief-trail metrics (`conf_rise`, `ttc`, `n_obs`, `revision`), written to test whether the `record_observation` trail separates the arms. It does the same job on 1/9th of the data, means only — and means are exactly what the outlier check later showed to be unsafe on these fields. Its findings are recorded in `docs/EXPLORE_EXPLOIT_SCORING.md` §3. |

Archived 2026-08-25 on request, and this one is **not superseded** — it is unused, which is a
different thing:

### `novelty_control.py` — a no-data baseline that was never run

Sends the benchmark's own **Examination questions** (Q1&ndash;Q4) to the model with **no dataset and
no code access**, so the answer can only come from literature memory. The intent was to measure how
much of a data-driven answer is recoverable from priors alone — a floor to score real episodes
against.

It still imports and still runs: `biodiscoverygym.examination.{lihc,os}` are present and both
expose `format_examination_prompt()`. But:

- it only covers **LIHC and OS**, the pre-ladder cohorts; there is no module for the seven TCGA
  cohorts the current study uses
- it wrote to `results/novelty_<cohort>.json`, and **no such file has ever existed** on disk, so
  as far as the repo can tell it was never run
- nothing references it, in code or docs

**Why it may be worth reviving.** It is the cleanest available answer to the question H1 currently
cannot address. H1 asks whether the outcome score can tell derivation from recall, and on the clean
run it is *not computable* because there are no `recalled-prior` episodes to contrast against —
under blinding essentially every episode derives. A no-data control manufactures the missing pole
directly: it is what pure recall scores, by construction, with no judge label needed.

To revive it: add an examination module for a current TCGA cohort alongside `lihc.py`/`os.py`, and
score its output through the same rubric as a real episode.

Earlier arrivals (pre-2026-08) are listed in git history rather than here.

**Before restoring anything from this directory**, check it against `docs/EVALUATION_ARCHITECTURE.md`
§4 for the current artifact layout — the flat `<episode>_<artifact>.json` names these scripts expect
were retired in `cca09cd`.
