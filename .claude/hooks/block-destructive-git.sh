#!/usr/bin/env bash
set -euo pipefail
input=$(cat)
event=$(printf '%s' "$input" | jq -r '.hook_event_name // empty')
case "$event" in
  PreToolUse) cmd=$(printf '%s' "$input" | jq -r '.tool_input.command // empty'); shape=claude ;;
  preToolUse) cmd=$(printf '%s' "$input" | jq -r '.tool_input.command // .command // empty'); shape=cursor ;;
  beforeShellExecution) cmd=$(printf '%s' "$input" | jq -r '.command // empty'); shape=cursor ;;
  *) echo "unknown hook_event_name: ${event:-missing}" >&2; exit 2 ;;
esac
if printf '%s' "$cmd" | grep -Eqi '(^|[;& ]+)git[[:space:]]+(reset[[:space:]]+--hard|push.*--force( |$))' && ! printf '%s' "$cmd" | grep -q -- '--force-with-lease'; then
  msg='Destructive git command blocked.'
  if [ "$shape" = claude ]; then jq -n --arg m "$msg" '{hookSpecificOutput:{hookEventName:"PreToolUse",permissionDecision:"deny",permissionDecisionReason:$m}}'; else jq -n --arg m "$msg" '{permission:"deny",user_message:$m,agent_message:$m}'; fi
fi
