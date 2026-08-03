# Production-run readiness

**Status 2026-08-03: everything code-side is ready. ONE BLOCKER, and it is environmental.**

## 🔴 Blocker — TLS interception

Every HTTPS request from this machine fails:

```
SSL: CERTIFICATE_VERIFY_FAILED — self-signed certificate in certificate chain
```

Not specific to Anthropic — `api.anthropic.com`, `api.openai.com` and `pypi.org` all fail, and
`openssl s_client` gets **0 certificates** back. So it is network-wide interception (corporate
proxy / VPN), not a per-provider issue.

`SSL_CERT_FILE=/Users/lpu/certs/combined-ca.pem` is set, but that bundle is dated **16 Apr** and
does not cover the current intercepting CA — verifying explicitly against it fails too.

**Likely fixes, in order of effort:** refresh the corporate CA bundle · run off the inspected
network (home / hotspot) · configure the proxy explicitly. **No API work can proceed until this
clears** — not the smoke, not the rerun, not judging.

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

## Run order, once TLS clears

**1 — Smoke (~$12, ~1h)**
```bash
source ./load_keys.sh "/Users/lpu/OneDrive - St. Jude Children's Research Hospital/keys.txt"
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

**3 — Judging (~$25)**
Requires one code change first: **`summarize_cot.build_input` currently prints the true cohort into
the judge's own prompt** (`summarize_cot.py:98`). The process judge must be blinded to true and
planted identity before it classifies provenance — this is Limitation 3 in the outline, and it is
not yet fixed. Then 3-pass consensus + ≥1 cross-family pass.

**4 — Analysis** — per `PREREGISTRATION.md`, in the registered order.

## Decisions still open

1. **Full 450 vs G1–G3 only** — recommend full; G0 is ~$350 and buys arm comparability.
2. **Keep Gemini** — tier-confounded, but it is the interesting case. Recommend keep + disclose.
3. **Blinded-judge edit** — needed before step 3; small change, no API.

## Not done, deliberately

- **Human adjudication** of a stratified label sample — owned by the PI.
- **Blind-then-challenge** — stretch goal, off the critical path.
