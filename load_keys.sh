#!/usr/bin/env bash
# load_keys.sh — read API keys from keys.txt and export them for the model ladder.
#
# This script holds NO secrets (safe to commit). Keys live in keys.txt (gitignored).
# keys.txt format — one "Provider:key" per line:
#     Anthropic:sk-ant-...
#     OpenAI:sk-proj-...
#     Gemini:AIza...
#
# Usage:  source load_keys.sh                 # reads ./keys.txt
#         source load_keys.sh /path/keys.txt  # or a custom path
# Must be `source`d (not executed) so the exports persist in your shell.

KEYS_FILE="${1:-keys.txt}"
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
        *) echo "load_keys: unknown provider '$provider' — skipped" >&2 ;;
    esac
done < "$KEYS_FILE"

echo "loaded from $KEYS_FILE -> ANTHROPIC=${ANTHROPIC_API_KEY:+set} OPENAI=${OPENAI_API_KEY:+set} GEMINI=${GEMINI_API_KEY:+set}"
