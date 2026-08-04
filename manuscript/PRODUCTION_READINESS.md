# Production-run readiness

**Status: everything code-side is ready.**

*Note: API calls require working TLS trust for the network you are on. If SDK calls fail with a
certificate error, resolve that with local IT before running — it is an environment matter, not a
project one.*

## ✅ Ready

| item | status |
|---|---|
| Blinding fix | `48d1db0` — agent works in opaque `_work/<uuid12>` |
| — partially validated | the failed smoke still relocated artifacts correctly out of `_work` |
| Channel sweep | complete — no further leaks (`PLAN.md` §0.2) |
| Blinding gate | `audit_blinding.py`, arm-aware, **fails on zero episodes** |
| Scorer guard | refuses to save when any LLM judge errors (`c28336a`) |
| Preregistration | frozen and committed (`373b742`) |
| Cost/time model | 450 eps ≈ $1,273, 1–2 days across 6 lanes |

## Run order

**1 — Smoke (~$12, ~1h)**
```bash
source ./load_keys.sh <path-to-keys.txt>
bash scripts/run_tcga.sh --smoke-test --tag smoke_blindfix
python scripts/audit_blinding.py results/tcga/smoke_blindfix
```
**Gate: exit 0 AND a non-zero episode count.** Both matter — the audit now refuses to pass on an
empty run, which is how the first attempt fooled us.

**2 — Production (~$1,470, 1–2 days, 6 lanes)**
Per `PLAN.md` §2: full 450 + **G3 at 8 seeds** (not 3 — at 3 a modest attenuation makes the
headline reversal undetectable, p≈0.24). Then:
```bash
python scripts/audit_blinding.py <each run dir>   # gate: exit 0, before ANY analysis
```

**3 — Judging (~$25)** — blinded by default now, no extra step.
The process judge no longer sees the true cohort or the arm; `judge_blinded: true` is recorded on
every summary so it is auditable after the fact. 3-pass consensus + ≥1 cross-family pass.
`--unblinded-judge` reproduces the old behaviour, for pilot comparison only.

**4 — Analysis** — per `PREREGISTRATION.md`, in the registered order.

**Order matters financially:** the audit is FREE and reads the episode JSON, so it gates *before*
scoring and judging. A run that fails the gate is discarded without paying to analyse it.

## Decisions still open

1. **Full 450 vs G1–G3 only** — recommend full; G0 is ~$350 and buys arm comparability.
2. **Keep Gemini** — tier-confounded, but it is the interesting case. Recommend keep + disclose.

## Not done, deliberately

- **Human adjudication** of a stratified label sample — owned by the PI.
- **Blind-then-challenge** — stretch goal, off the critical path.
