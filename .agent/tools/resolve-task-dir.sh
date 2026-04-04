#!/usr/bin/env bash
set -euo pipefail

# resolve-task-dir.sh — resolve TASK_DIR for a repo+branch via .task-id reverse lookup.
#
# By default reads remote + branch from the current git context.
# Use --remote / --branch to override (e.g. crew-cleanup resolving a different worktree's tasks).
# Use --all to return every matching dir (one per line) instead of the single best match.
#
# Outputs the absolute TASK_DIR path to stdout, or empty string if no active task.
# Exits 1 if git state is unresolvable (no remote configured, not on a branch).
#
# Assumption: remote URL is stable after spec creation (SSH vs HTTPS not normalized).
#
# Usage (hard — abort caller if git state is broken):
#   TASK_DIR=$(~/.agent/tools/resolve-task-dir.sh) || exit 1
#
# Usage (soft — skip session capture / optional logging):
#   TASK_DIR=$(~/.agent/tools/resolve-task-dir.sh 2>/dev/null || echo "")
#
# Usage (crew-cleanup — all matches for a specific worktree's remote+branch):
#   mapfile -t DIRS < <(~/.agent/tools/resolve-task-dir.sh \
#     --remote "$WORKTREE_REMOTE" --branch "$WORKTREE_BRANCH" --all 2>/dev/null || true)

OVERRIDE_REMOTE=""
OVERRIDE_BRANCH=""
ALL_MATCHES=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    --remote) OVERRIDE_REMOTE="$2"; shift 2 ;;
    --branch) OVERRIDE_BRANCH="$2"; shift 2 ;;
    --all)    ALL_MATCHES=true; shift ;;
    *) echo "Unknown argument: $1" >&2; exit 1 ;;
  esac
done

if [[ -n "$OVERRIDE_REMOTE" ]]; then
  CURRENT_REMOTE="$OVERRIDE_REMOTE"
else
  CURRENT_REMOTE=$(git remote get-url origin 2>/dev/null || echo "")
  if [ -z "$CURRENT_REMOTE" ]; then
    echo "No git remote configured; cannot resolve task state." >&2
    exit 1
  fi
fi

if [[ -n "$OVERRIDE_BRANCH" ]]; then
  CURRENT_BRANCH="$OVERRIDE_BRANCH"
else
  CURRENT_BRANCH=$(git branch --show-current 2>/dev/null || echo "")
  if [ -z "$CURRENT_BRANCH" ]; then
    echo "Not on a branch; crew commands require an active branch." >&2
    exit 1
  fi
fi

MATCHES=()
for task_id_file in ~/.agent/tasks/*/.task-id; do
  [ -f "$task_id_file" ] || continue
  file_remote=$(python3 -c "import json; d=json.load(open('$task_id_file')); print(d.get('repo_remote_url',''))" 2>/dev/null || echo "PARSE_ERROR")
  file_branch=$(python3 -c "import json; d=json.load(open('$task_id_file')); print(d.get('branch',''))" 2>/dev/null || echo "PARSE_ERROR")
  if [ "$file_remote" = "PARSE_ERROR" ] || [ "$file_branch" = "PARSE_ERROR" ]; then
    echo "Warning: malformed .task-id at $task_id_file — skipping." >&2
    continue
  fi
  if [ "$file_remote" = "$CURRENT_REMOTE" ] && [ "$file_branch" = "$CURRENT_BRANCH" ]; then
    created_at=$(python3 -c "import json; d=json.load(open('$task_id_file')); print(d.get('created_at',''))" 2>/dev/null || echo "")
    MATCHES+=("$created_at $(dirname "$task_id_file")")
  fi
done

if [ "${#MATCHES[@]}" -eq 0 ]; then
  echo ""
  exit 0
fi

# --all: return every matching dir, one per line (no tie-breaking)
if [[ "$ALL_MATCHES" == true ]]; then
  for entry in "${MATCHES[@]}"; do
    echo "${entry#* }"
  done
  exit 0
fi

if [ "${#MATCHES[@]}" -eq 1 ]; then
  echo "${MATCHES[0]#* }"
  exit 0
fi

# Multiple matches: prefer non-DONE, then most recent created_at
BEST=""
BEST_DATE=""
for entry in "${MATCHES[@]}"; do
  dir="${entry#* }"
  date="${entry%% *}"
  spec_status=$(grep -A1 "^## Status" "$dir/SPEC.md" 2>/dev/null | tail -1 | tr -d ' ' || echo "")
  if [ "$spec_status" != "done" ]; then
    if [ -z "$BEST" ] || [[ "$date" > "$BEST_DATE" ]]; then
      BEST="$dir"; BEST_DATE="$date"
    fi
  fi
done
# If all are DONE, pick most recent
if [ -z "$BEST" ]; then
  BEST=$(printf '%s\n' "${MATCHES[@]}" | sort -r | head -1)
  BEST="${BEST#* }"
fi
echo "Multiple tasks found for this repo+branch. Using: $BEST (most recent non-DONE)." >&2
echo "$BEST"
