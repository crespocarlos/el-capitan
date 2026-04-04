#!/bin/bash
# Blocks destructive git commands: force-push and hard-reset.
# Receives JSON on stdin from PreToolUse hook.
# Exit 0 = allow, stdout JSON with deny = block.

exec 2>/dev/null

INPUT=$(cat) || exit 0

if command -v jq >/dev/null 2>&1; then
  CMD=$(echo "$INPUT" | jq -r '.tool_input.command // empty')
else
  CMD=$(echo "$INPUT" | grep -o '"command":"[^"]*"' | head -1 | sed 's/"command":"//;s/"//')
fi
[ -z "$CMD" ] && exit 0

NORMALIZED=$(echo "$CMD" | tr '[:upper:]' '[:lower:]' | tr -s ' ')

if echo "$NORMALIZED" | grep -qE '^\s*git\s+push\s+.*--force\b' && ! echo "$NORMALIZED" | grep -q '\-\-force-with-lease'; then
  echo '{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":"Force push blocked. Use --force-with-lease instead."}}'
  exit 0
fi

if echo "$NORMALIZED" | grep -qE '^\s*git\s+reset\s+--hard'; then
  echo '{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":"Hard reset blocked. Use git stash or a soft reset."}}'
  exit 0
fi

exit 0
