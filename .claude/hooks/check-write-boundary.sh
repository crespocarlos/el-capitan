#!/bin/bash
# Warns when a Write/Edit targets a file outside the current git worktree.
# Prevents accidental edits to the main repo when working in a worktree.
# Receives JSON on stdin from PreToolUse hook.

exec 2>/dev/null

INPUT=$(cat) || exit 0

if ! command -v jq >/dev/null 2>&1; then exit 0; fi

FILE_PATH=$(echo "$INPUT" | jq -r '.tool_input.file_path // empty')
[ -z "$FILE_PATH" ] && exit 0

WORKTREE_ROOT=$(git rev-parse --show-toplevel 2>/dev/null)
if [ -z "$WORKTREE_ROOT" ]; then
  echo '{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":"Write blocked: cannot determine worktree root."}}'
  exit 0
fi

RESOLVED=$(cd "$(dirname "$FILE_PATH")" 2>/dev/null && pwd)/$(basename "$FILE_PATH") 2>/dev/null
if [ -z "$RESOLVED" ]; then
  echo "{\"hookSpecificOutput\":{\"hookEventName\":\"PreToolUse\",\"permissionDecision\":\"deny\",\"permissionDecisionReason\":\"Write blocked: cannot resolve file path for $FILE_PATH.\"}}"
  exit 0
fi

case "$RESOLVED" in
  "$WORKTREE_ROOT"/*) exit 0 ;;
  "$HOME/.agent/"*) exit 0 ;;
  "$HOME/.claude/"*) exit 0 ;;
  "$HOME/.cursor/"*) exit 0 ;;
  /tmp/*) exit 0 ;;
esac

echo "{\"hookSpecificOutput\":{\"hookEventName\":\"PreToolUse\",\"permissionDecision\":\"deny\",\"permissionDecisionReason\":\"Write blocked: $FILE_PATH is outside the current worktree ($WORKTREE_ROOT). Switch to the correct worktree first.\"}}"
