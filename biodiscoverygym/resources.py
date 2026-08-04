"""Per-episode resource accounting: tokens in/out and where the wall-clock went.

WHAT THIS IS FOR
----------------
Two questions this project keeps having to answer from scratch:

  "What did a run cost?"      -> tokens, which are measured and never change
  "Why did a run take 21h?"   -> the wall-clock split, which is how we caught that a stalled
                                 Gemini episode was retry backoff (0% CPU) and not a runaway
                                 `run_code` loop (99.8% CPU). Those look identical from the
                                 outside and have opposite fixes.

Both were previously recoverable only by summing `run_log.usage_log` by hand, per episode, in
whatever script happened to need them. This puts one rollup on the episode JSON so downstream
analysis reads a field instead of re-deriving it (and re-deriving it differently each time).

NO PRICES HERE, DELIBERATELY. Token counts are measurements and are true forever; prices are
supplied by the project owner, change without notice, and already rewrote the model cost ranking
once. Baking dollars into the episode record would freeze a guess next to a measurement and make
them indistinguishable a year later. Cost stays in scripts/gen_cost_report.py, where the price
table carries its own provenance date and can be overridden per run.

THE TIME SPLIT IS APPROXIMATE and labelled as such. `api_s` is measured per turn and includes
retry backoff on purpose (see `retries`); `exec_s` comes from the executor's own timing log.
`unaccounted_s` is the remainder -- data staging, serialization, scoring hooks. It is reported
rather than silently folded into either bucket, because a large remainder is itself the signal
that something is wrong somewhere we are not currently measuring.
"""
from __future__ import annotations


def _isum(rows: list[dict], key: str) -> int:
    """Sum a token field, tolerating None from providers that omit usage on some turns."""
    return sum(int(r.get(key) or 0) for r in rows)


def summarize(run_log: dict, wall_time_s: float | None = None) -> dict:
    """Roll a run_log up into one flat, JSON-safe resource record."""
    usage = run_log.get("usage_log") or []
    timing = run_log.get("timing_log") or []

    tin, tout = _isum(usage, "input_tokens"), _isum(usage, "output_tokens")
    api_s = round(sum(float(r.get("api_s") or 0.0) for r in usage), 2)
    exec_s = round(sum(float(r.get("exec_time_s") or 0.0) for r in timing), 2)

    # Per-turn API timing was added after the pilot runs. On a pre-existing episode every turn
    # lacks `api_s`, which sums to a perfectly innocent 0.0 -- and would then render as "0% of
    # wall-clock spent on the API, 93% unaccounted", i.e. a measurement gap wearing the costume
    # of a finding. Flag it instead, and suppress the percentages that would be lies.
    api_measured = any("api_s" in r for r in usage)

    # A provider that reports no usage at all must not render as a free episode. Distinguish
    # "measured zero" from "never reported" so a downstream cost table can exclude it instead of
    # averaging a fake 0 into the mean.
    reported = [r for r in usage if r.get("input_tokens") is not None]

    out: dict = {
        "input_tokens": tin,
        "output_tokens": tout,
        "total_tokens": tin + tout,
        "n_turns": len(usage),
        "n_turns_with_usage": len(reported),
        "tokens_reported": len(reported) > 0,
        "api_s": api_s if api_measured else None,
        "api_time_measured": api_measured,
        "exec_s": exec_s,
        "n_code_execs": len(timing),
        "n_exec_timeouts": sum(1 for r in timing if r.get("timed_out")),
        "n_exec_errors": sum(1 for r in timing if r.get("is_error")),
        "api_retries": sum(int(r.get("retries") or 0) for r in usage),
    }

    if wall_time_s is not None:
        out["wall_time_s"] = round(float(wall_time_s), 2)
        if wall_time_s > 0:
            out["pct_exec"] = round(100 * exec_s / wall_time_s, 1)
        # Only meaningful once API time is actually measured; otherwise the remainder is just
        # "everything", which says nothing.
        if api_measured:
            out["unaccounted_s"] = round(max(0.0, float(wall_time_s) - api_s - exec_s), 2)
            if wall_time_s > 0:
                out["pct_api"] = round(100 * api_s / wall_time_s, 1)

    # Per-turn averages: the number that tells you whether a long episode was many cheap turns or
    # few expensive ones. Guarded so a zero-turn episode reports nothing rather than dividing.
    if reported:
        out["mean_output_tokens_per_turn"] = round(tout / len(reported), 1)
        if api_measured:
            out["mean_api_s_per_turn"] = round(api_s / len(reported), 2)

    return out


def format_line(res: dict) -> str:
    """One-line human summary for the end-of-episode console block."""
    if not res.get("tokens_reported"):
        tok = "tokens: NOT REPORTED by provider"
    else:
        tok = (f"tokens: {res['input_tokens']:,} in / {res['output_tokens']:,} out "
               f"over {res['n_turns']} turns")
    if res.get("api_time_measured"):
        t = (f"time: {res.get('wall_time_s', 0):.0f}s wall "
             f"({res.get('pct_api', 0):.0f}% API, {res.get('pct_exec', 0):.0f}% exec)")
    else:
        t = (f"time: {res.get('wall_time_s', 0):.0f}s wall "
             f"({res.get('pct_exec', 0):.0f}% exec, API time not measured)")
    extra = ""
    if res.get("api_retries"):
        extra += f"  retries: {res['api_retries']}"
    if res.get("n_exec_timeouts"):
        extra += f"  exec timeouts: {res['n_exec_timeouts']}"
    return f"{tok}   {t}{extra}"
