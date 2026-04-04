#!/bin/bash
# Warns when a Write/Edit targets a file outside any known worktree of the repo.
# Prevents accidental edits to unrelated directories.
# Receives JSON on stdin from PreToolUse hook.

exec 2>/dev/null

INPUT=$(cat) || exit 0

if ! command -v jq >/dev/null 2>&1; then exit 0; fi

FILE_PATH=$(echo "$INPUT" | jq -r '.tool_input.file_path // empty')
[ -z "$FILE_PATH" ] && exit 0

RESOLVED=$(cd "$(dirname "$FILE_PATH")" 2>/dev/null && pwd)/$(basename "$FILE_PATH") 2>/dev/null
[ -z "$RESOLVED" ] && exit 0

# Always allow writes to agent/config directories and temp
case "$RESOLVED" in
  "$HOME/.agent/"*) exit 0 ;;
  "$HOME/.claude/"*) exit 0 ;;
  "$HOME/.cursor/"*) exit 0 ;;
  /tmp/*) exit 0 ;;
esac

# Allow writes to the current worktree
WORKTREE_ROOT=$(git rev-parse --show-toplevel 2>/dev/null)
[ -n "$WORKTREE_ROOT" ] && case "$RESOLVED" in "$WORKTREE_ROOT"/*) exit 0 ;; esac

# Allow writes to any worktree of this repo
if [ -n "$WORKTREE_ROOT" ]; then
  while IFS= read -r wt_path; do
    case "$RESOLVED" in "$wt_path"/*) exit 0 ;; esac
  done < <(git worktree list --porcelain 2>/dev/null | grep '^worktree ' | sed 's/^worktree //')
fi

# Allow writes to the common worktrees directory
case "$RESOLVED" in
  "$HOME/worktrees/"*) exit 0 ;;
esac

echo "{\"hookSpecificOutput\":{\"hookEventName\":\"PreToolUse\",\"permissionDecision\":\"deny\",\"permissionDecisionReason\":\"Write blocked: $FILE_PATH is outside all known worktrees. Switch to the correct worktree first.\"}}"
