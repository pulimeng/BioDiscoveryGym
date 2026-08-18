"""Single source of truth for which run directories the analysis reads.

WHY THIS EXISTS. Thirteen scripts hardcoded the pilot paths
(`results/tcga/pilot/ladder/gpt55_20260707`, …). After the clean rerun they would keep analysing the
CONTAMINATED pilot and report its numbers without erroring — the project's signature failure mode:
a wrong result that renders as a normal one. Nothing would have flagged it.

USAGE — point every analysis at the clean run with one variable:

    export BDG_RUNS=clean            # reads results/tcga/clean/*  + results/tcga/clean_lean/*
    python scripts/cot_deepdive.py

or give explicit roots:

    export BDG_DETAILED_ROOT=results/tcga/clean
    export BDG_LEAN_ROOT=results/tcga/clean_lean

Default is the pilot, so existing behaviour is unchanged until you opt in — and every script that
imports this prints which run set it used, so a report can never quietly describe the wrong data.
"""
from __future__ import annotations

import glob
import os
import sys

# (display label, directory stem, colour, tier)
#
# BOTH Gemini entries are listed on purpose. The pilot ran Gemini 3.5 Flash; the clean run uses
# Gemini 3.1 Pro after Flash was abandoned at 60/95 on sustained 503s and an 18h hang
# (results/tcga/_abandoned/gemini35flash_20260805_incomplete/WHY_ABANDONED.md). Replacing the row
# outright would have silently dropped Gemini from every pilot analysis, since triples() filters
# on `stem in RUNS[prompt]` and would simply have found nothing to iterate — no error, one fewer
# arm in the tables. Listing both means each run set resolves the Gemini it actually has.
#
# TIER NOTE: the clean run is now three flagships. That removes the tier confound the pilot had,
# and with it the flash-vs-flagship contrast. See docs/MODEL_LADDER.md.
MODELS = [
    ('GPT-5.5', 'gpt55', '#1D9E75', 'flagship'),
    ('Sonnet 5', 'sonnet5', '#7F77DD', 'flagship'),
    ('Gemini 3.5 Flash', 'gemini35flash', '#EF9F27', 'flash'),
    ('Gemini 2.5 Pro', 'gemini25pro', '#EF9F27', 'flagship'),
]
# GENERATION NOTE for the write-up: GPT-5.5 and Sonnet 5 are current flagships; Gemini 2.5 Pro is
# a generation behind. It is here because gemini-3.1-pro-preview (released 2026-02-19) is on a
# saturated shared serving lane and returned 503 on even a 1-token preflight, and Gemini 3.5 Flash
# was abandoned at 60/95 for the same reason. 2.5 Pro is GA, so it is the newest Gemini that can
# actually complete 95 episodes. Any Gemini-vs-others gap is therefore confounded with model
# generation and must not be read as a vendor difference.

_PILOT = {
    'detailed': {'gpt55': 'results/tcga/pilot/ladder/gpt55_20260707',
                 'sonnet5': 'results/tcga/pilot/ladder/sonnet5_20260713',
                 'gemini35flash': 'results/tcga/pilot/ladder/gemini35flash_20260716'},
    'lean': {'gpt55': 'results/tcga/pilot/lean/gpt55_20260721',
             'sonnet5': 'results/tcga/pilot/lean/sonnet5_20260722',
             'gemini35flash': 'results/tcga/pilot/lean/gemini35flash_20260722'},
}


def _resolve() -> tuple[dict, str]:
    """Return ({prompt: {stem: path}}, human-readable label for what was selected)."""
    det_root = os.environ.get('BDG_DETAILED_ROOT')
    lean_root = os.environ.get('BDG_LEAN_ROOT')
    tag = os.environ.get('BDG_RUNS')
    if tag and not (det_root and lean_root):
        det_root = det_root or f'results/tcga/{tag}'
        lean_root = lean_root or f'results/tcga/{tag}_lean'
    if not (det_root or lean_root):
        return _PILOT, 'PILOT (path-contaminated — see docs/DATA_INTEGRITY_AUDIT.md)'

    out = {'detailed': {}, 'lean': {}}
    for prompt, root in (('detailed', det_root), ('lean', lean_root)):
        if not root:
            continue
        for _, stem, _, _ in MODELS:
            # accept either <root>/<stem> or <root>/<stem>_<date>
            hits = sorted(glob.glob(f'{root}/{stem}') + glob.glob(f'{root}/{stem}_*'))
            if hits:
                out[prompt][stem] = hits[0]
    return out, f'{det_root} + {lean_root}'


RUNS, SOURCE = _resolve()
_announced = False


def announce() -> None:
    """Print which run set is in use. Called by every consumer, once.

    The PILOT default gets a banner, not a line. It is path-contaminated and superseded, yet it is
    what a bare `python scripts/gen_*.py` still reads — and this session produced two reports dated
    today built entirely on it, one of which printed a conclusion the clean run contradicts at
    p=2.4e-14. Nothing failed; the only signal was a single quiet stderr line that scrolled past.
    Behaviour is unchanged (changing the default would silently repoint thirteen scripts); what
    changes is that choosing the contaminated campaign can no longer be done by accident.
    """
    global _announced
    if not _announced:
        if SOURCE.startswith('PILOT'):
            bar = '!' * 78
            print(f"\n{bar}\n  READING THE CONTAMINATED PILOT — results are NOT publication-safe.\n"
                  f"  {SOURCE}\n"
                  f"  The pilot leaked the cohort through output_dir; see docs/DATA_INTEGRITY_AUDIT.md.\n"
                  f"  For the clean campaign:  export BDG_RUNS=clean\n{bar}\n", file=sys.stderr)
        else:
            print(f"  [runs] {SOURCE}", file=sys.stderr)
        _announced = True


def triples() -> list[tuple[str, str, str]]:
    """[(model_label, prompt, path)] — for scripts that iterate arms flatly."""
    announce()
    return [(lbl, prompt, RUNS[prompt][stem])
            for prompt in ('detailed', 'lean')
            for lbl, stem, _, _ in MODELS if stem in RUNS.get(prompt, {})]


def pairs() -> list[tuple[str, str, str, str, str]]:
    """[(model_label, detailed_path, lean_path, colour, tier)] — for ablation-style scripts."""
    announce()
    out = []
    for lbl, stem, col, tier in MODELS:
        d, l = RUNS.get('detailed', {}).get(stem), RUNS.get('lean', {}).get(stem)
        if d and l:
            out.append((lbl, d, l, col, tier))
    return out


def flat(prompt: str | None = None) -> list[str]:
    """[path] — every run directory; `prompt` ('detailed'|'lean') restricts to one wave.

    Filtering matters for anything that SPENDS money or writes labels. The two waves finish at
    different times, so a combined list will happily schedule work against a wave that is still
    being generated — judging a 12/95 lane, then re-judging it once the other 83 land.
    """
    announce()
    if prompt is not None and prompt not in RUNS:
        raise ValueError(f"unknown prompt set {prompt!r}; expected 'detailed' or 'lean'")
    prompts = (prompt,) if prompt else ('detailed', 'lean')
    return [p for pr in prompts for p in RUNS.get(pr, {}).values()]
