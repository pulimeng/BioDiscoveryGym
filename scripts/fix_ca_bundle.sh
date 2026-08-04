#!/usr/bin/env bash
# fix_ca_bundle.sh — rebuild a CA bundle that trusts the corporate TLS interceptor.
#
# WHY: the network runs Cloudflare Gateway TLS inspection. Python's httpx (used by the Anthropic
# and OpenAI SDKs) verifies against certifi's bundle, which does not contain the interceptor's CA,
# so every API call dies with CERTIFICATE_VERIFY_FAILED. The corporate bundle at
# ~/certs/combined-ca.pem goes stale whenever Cloudflare rotates that CA.
#
# WHAT: certifi + the existing corporate bundle + whatever the live connection presents, written to
# a single file. Then export SSL_CERT_FILE at it — that is the variable httpx honours
# (REQUESTS_CA_BUNDLE does nothing here; tested).
#
# Usage:   source scripts/fix_ca_bundle.sh      # must be sourced, so the export persists
set -uo pipefail
OUT="${CA_BUNDLE_OUT:-$HOME/certs/ca-bundle-current.pem}"
PROBE="${CA_PROBE_HOST:-api.anthropic.com}"
mkdir -p "$(dirname "$OUT")"

python -c "import certifi,shutil,sys;shutil.copy(certifi.where(),sys.argv[1])" "$OUT" || return 1 2>/dev/null || exit 1
[ -f "$HOME/certs/combined-ca.pem" ] && cat "$HOME/certs/combined-ca.pem" >> "$OUT"
perl -e 'alarm 15; exec @ARGV' openssl s_client -showcerts -connect "$PROBE:443" -servername "$PROBE" \
  </dev/null 2>/dev/null | awk '/BEGIN CERT/,/END CERT/' >> "$OUT"

export SSL_CERT_FILE="$OUT"
echo "  bundle: $OUT  ($(grep -c 'BEGIN CERT' "$OUT") certs)"
python - <<'PY'
import httpx, os
try:
    r = httpx.get("https://api.anthropic.com", timeout=10)
    print(f"  TLS verify: OK (HTTP {r.status_code})   SSL_CERT_FILE={os.environ['SSL_CERT_FILE']}")
except Exception as e:
    print(f"  TLS verify: STILL FAILING — {type(e).__name__}")
    print("  The interceptor may present a different CA for other hosts; try")
    print("  CA_PROBE_HOST=api.openai.com source scripts/fix_ca_bundle.sh")
PY
echo "  add to your shell profile to make it permanent:"
echo "      export SSL_CERT_FILE=$OUT"
