#!/usr/bin/env bash
# load_keys.sh — read API keys from keys.txt and export them for the model ladder.
#
# This script holds NO secrets (safe to commit). Keys live in keys.txt (gitignored).
# keys.txt format — one "Provider:key" per line:
#     Anthropic:sk-ant-...
#     OpenAI:sk-proj-...
#     Gemini:AIza...
#
# Usage:  source load_keys.sh                    # reads ./keys.txt
#         source load_keys.sh "/path with spaces/keys.txt"   # explicit path (quote it)
#         KEYS_FILE="/path/keys.txt" source load_keys.sh     # or set once via env
# Must be `source`d (not executed) so the exports persist in your shell.

KEYS_FILE="${1:-${KEYS_FILE:-keys.txt}}"
if [[ ! -f "$KEYS_FILE" ]]; then
    echo "load_keys: '$KEYS_FILE' not found — create it with lines like 'Anthropic:sk-ant-...'" >&2
    return 1 2>/dev/null || exit 1
fi

while IFS= read -r line || [[ -n "$line" ]]; do
    line="${line%$'\r'}"                                  # strip trailing CR (Windows files)
    [[ -z "${line// /}" || "${line#\#}" != "$line" ]] && continue   # skip blank / comment
    provider="${line%%:*}"                                # text before the first colon
    key="${line#*:}"                                      # everything after the first colon
    provider="$(echo "$provider" | tr '[:upper:]' '[:lower:]' | tr -d '[:space:]')"
    key="$(echo "$key" | xargs)"                          # trim surrounding whitespace
    [[ -z "$key" ]] && continue
    case "$provider" in
        anthropic|claude) export ANTHROPIC_API_KEY="$key" ;;
        openai|gpt)       export OPENAI_API_KEY="$key" ;;
        gemini|google)    export GEMINI_API_KEY="$key"; export GOOGLE_API_KEY="$key" ;;
        deepseek)         export DEEPSEEK_API_KEY="$key" ;;
        # Institutional OpenAI-compatible gateway (bifrost). Serves nemotron-3-super and
        # laguna — neither is a benchmarked agent family, so it is a genuinely NEUTRAL judge,
        # and unlike DeepSeek it is inside the network perimeter and cannot be firewalled off
        # mid-run. Accepts several spellings because keys.txt is hand-edited.
        nemo|nemotron|bifrost|stjude) export BIFROST_API_KEY="$key" ;;
        # Qwen — a SECOND neutral judge family, on the institutional serving platform. This is
        # NOT bifrost: different host, different key, and a different TLS root. Keep the two
        # separate; exporting one as the other silently sends the wrong credential.
        qwen) export QWEN_API_KEY="$key" ;;
        *) echo "load_keys: unknown provider '$provider' — skipped" >&2 ;;
    esac
done < "$KEYS_FILE"

# Report EVERY provider this script can export, including the ones that are absent. A summary
# that lists only what loaded cannot distinguish "the key is missing" from "this script has no
# mapping for that label" — which is exactly how the Nemo key read as unloaded when it was fine.
# NEVER interpolate a key variable directly. `${VAR:-x}` expands to the VALUE when VAR is set —
# it is a default-if-empty operator, not a mask — so using it here printed all five keys in
# plaintext. Only `${VAR:+literal}` is safe, and this helper avoids the trap entirely.
_lk_status() { [ -n "${1:-}" ] && printf 'set' || printf '-'; }
echo "loaded from $KEYS_FILE -> ANTHROPIC=$(_lk_status "${ANTHROPIC_API_KEY:-}") OPENAI=$(_lk_status "${OPENAI_API_KEY:-}") GEMINI=$(_lk_status "${GEMINI_API_KEY:-}") DEEPSEEK=$(_lk_status "${DEEPSEEK_API_KEY:-}") BIFROST=$(_lk_status "${BIFROST_API_KEY:-}") QWEN=$(_lk_status "${QWEN_API_KEY:-}")"
unset -f _lk_status
