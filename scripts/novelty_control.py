#!/usr/bin/env python3
"""
Novelty control: answer Examination questions with no data access.

Sends the same Examination Q1-Q4 to Claude without any dataset or code access.
Used as a baseline to measure how much of a data-driven answer is literature recall.

Usage:
    python scripts/novelty_control.py --cohort LIHC --save-log results/novelty_lihc.json
    python scripts/novelty_control.py --cohort OS   --save-log results/novelty_os.json
"""
import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import anthropic

FRAMING = (
    "You are a cancer biologist. You have previously analyzed a cancer cohort "
    "and identified two molecular subtypes using gene expression data. "
    "You do NOT have access to the dataset — you cannot run code or look up "
    "specific numbers from this cohort. "
    "Answer the following questions from general biological knowledge only. "
    "If a question requires a specific number from this dataset that you cannot "
    "know without data access, say so explicitly rather than guessing."
)

_EXAMINATION_MODULES = {
    "LIHC": "biodiscoverygym.examination.lihc",
    "OS":   "biodiscoverygym.examination.os",
}


def run_novelty_control(cohort: str, model: str, save_log: str | None) -> None:
    mod_name = _EXAMINATION_MODULES.get(cohort.upper())
    if mod_name is None:
        print(f"Error: no Examination questions defined for cohort {cohort}.", file=sys.stderr)
        print(f"  Supported: {', '.join(_EXAMINATION_MODULES)}", file=sys.stderr)
        sys.exit(1)

    import importlib
    mod = importlib.import_module(mod_name)
    questions = mod.format_examination_prompt()

    client = anthropic.Anthropic()
    messages = [{"role": "user", "content": f"{FRAMING}\n\n{questions}"}]

    t0 = time.time()
    response = client.messages.create(
        model=model,
        max_tokens=4096,
        messages=messages,
    )
    elapsed = time.time() - t0

    answer = response.content[0].text
    print("=" * 70)
    print("NOVELTY CONTROL — no-data answer")
    print("=" * 70)
    print(answer)
    print("=" * 70)
    print(f"Elapsed: {elapsed:.1f}s | Tokens: {response.usage.input_tokens} in / {response.usage.output_tokens} out")

    if save_log:
        out = {
            "mode": "novelty_control",
            "cohort": cohort.upper(),
            "model": model,
            "framing": FRAMING,
            "questions": questions,
            "answer": answer,
            "elapsed_s": round(elapsed, 1),
            "usage": {
                "input_tokens": response.usage.input_tokens,
                "output_tokens": response.usage.output_tokens,
            },
        }
        Path(save_log).parent.mkdir(parents=True, exist_ok=True)
        with open(save_log, "w") as f:
            json.dump(out, f, indent=2)
        print(f"Saved: {save_log}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--cohort", default="LIHC", choices=list(_EXAMINATION_MODULES))
    parser.add_argument("--model", default="claude-sonnet-4-6")
    parser.add_argument("--save-log", default=None)
    args = parser.parse_args()
    run_novelty_control(args.cohort, args.model, args.save_log)
