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
echo "[$(date '+%Y-%m-%d %H:%M')] TRANSITION: $TRANSITION" >> "$TASK_DIR/PROGRESS.md"
