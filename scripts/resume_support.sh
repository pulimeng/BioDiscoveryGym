#!/usr/bin/env bash
# resume_support.sh — finish a support-scoring run WITHOUT re-billing episodes already
# freshly judged this session. score_support skips episodes that already have a
# _supportscores.json — but stale (pre-migration) files also count as "already scored",
# so a plain resume would wrongly SKIP them. This deletes only the STALE support files
# (mtime older than the cutoff), then runs score_support WITHOUT --rescore so it fills
# exactly the gaps with the neutral judge.
#
# RUN ONLY AFTER the live scorer has stopped (don't delete files out from under it).
#
#   bash scripts/resume_support.sh results/tcga/run1+2              # dry-run, cutoff 180 min
#   bash scripts/resume_support.sh results/tcga/run1+2 240          # stale = older than 240 min
#   bash scripts/resume_support.sh results/tcga/run1+2 180 --apply  # actually delete stale + resume
set -uo pipefail

DIR="${1:?usage: resume_support.sh <dir> [stale_minutes] [--apply]}"
CUTOFF="${2:-180}"; [[ "$CUTOFF" == "--apply" ]] && CUTOFF=180
APPLY=0; for a in "$@"; do [[ "$a" == "--apply" ]] && APPLY=1; done

echo "=== resume_support: $DIR  (stale = mtime > ${CUTOFF} min) ==="
if ps aux | grep -E 'score_support\.py' | grep -v grep | grep -q .; then
    echo "WARNING: a score_support.py process is still running — let it finish or kill it first." >&2
fi

STALE=$(find "$DIR" -iname '*_supportscores.json' -mmin +"$CUTOFF")
N=$(printf '%s' "$STALE" | grep -c . || true)
echo "stale support files to re-score: $N"
printf '%s\n' "$STALE" | sed 's/^/  /'

if [[ $APPLY -eq 0 ]]; then
    echo "(dry-run — add --apply to delete these and resume the missing ones)"
    exit 0
fi

printf '%s\n' "$STALE" | while IFS= read -r f; do [[ -n "$f" ]] && rm -f "$f"; done
echo "deleted $N stale files; resuming (no --rescore → fills only the now-missing)..."
python scripts/score_support.py "$DIR" --save
