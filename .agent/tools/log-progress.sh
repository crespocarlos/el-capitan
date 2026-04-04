#!/bin/bash
# log-progress.sh — append a pipeline transition to PROGRESS.md
# Usage: log-progress.sh <TASK_DIR> "<FROM> → <TO>"
# Example: log-progress.sh ~/.agent/tasks/repo/branch/slug "APPROVED → IMPLEMENTING"

set -e

TASK_DIR="$1"
TRANSITION="$2"

if [ -z "$TASK_DIR" ] || [ -z "$TRANSITION" ]; then
  echo "Usage: log-progress.sh <TASK_DIR> \"FROM → TO\"" >&2
  exit 1
fi

mkdir -p "$TASK_DIR"
STEP=$(echo "$TRANSITION" | sed 's/.*→ *//' | sed 's/^[[:space:]]*//' | sed 's/[[:space:]]*$//')
SUFFIX=""
if [ -n "${CREW_WORKFLOW:-}" ] || [ -n "${CREW_MEMBER:-}" ]; then
  if command -v jq >/dev/null 2>&1; then
    SUFFIX=" $(jq -cn --arg step "$STEP" --arg wf "${CREW_WORKFLOW:-}" --arg crew "${CREW_MEMBER:-}" '{step: $step, workflow: (if $wf == "" then null else $wf end), crew: (if $crew == "" then null else $crew end)}')"
  else
    STEP_ESC="${STEP//"/\\"}"
    WF="${CREW_WORKFLOW:-}"; [ -z "$WF" ] && WF_JSON="null" || WF_JSON="\"${WF//"/\\"}\""
    CREW="${CREW_MEMBER:-}"; [ -z "$CREW" ] && CREW_JSON="null" || CREW_JSON="\"${CREW//"/\\"}\""
    SUFFIX=" {\"step\":\"${STEP_ESC}\",\"workflow\":${WF_JSON},\"crew\":${CREW_JSON}}"
  fi
fi
echo "[$(date '+%Y-%m-%d %H:%M:%S')] TRANSITION: $TRANSITION$SUFFIX" >> "$TASK_DIR/PROGRESS.md"
