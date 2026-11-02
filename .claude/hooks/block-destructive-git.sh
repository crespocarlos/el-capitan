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
msg=''
if grep -Eqi '(^|[;& ]+)git[[:space:]]+(reset[[:space:]]+--hard|push.*--force( |$))' <<<"$cmd" && ! grep -q -- '--force-with-lease' <<<"$cmd"; then
  msg='Destructive git command blocked.'
elif grep -Eqi '(^|[;&| ]+)gh[[:space:]]+pr[[:space:]]+(checkout|co)([[:space:]]|$)|(^|[;&| ]+)git[[:space:]].*(fetch|pull)[[:space:]].*(refs/)?pull/[0-9]+' <<<"$cmd"; then
  msg='Pulling a PR into the local checkout is blocked. Read it with `gh pr diff <n>` and `gh api repos/<owner>/<repo>/contents/<path>?ref=<headSHA>`.'
elif grep -Eqi '(^|[;&| ]+)git[[:space:]].*(show|diff|log|cat-file|rev-parse|fetch|pull).*(refs/)?pull/' <<<"$cmd"; then
  msg='Reading a local PR ref is blocked. Read PR-head content with `gh pr diff <n>` or `gh api repos/<owner>/<repo>/contents/<path>?ref=<headSHA>`.'
elif grep -Eqi '(^|[;&| ]+)gh.*pr.*\\|(^|[;&| ]+)git.*(\\|\$).*(pull|refs)' <<<"$cmd"; then
  msg='Shell-expanded PR commands are blocked. Use literal `gh pr diff` or `gh api` PR-head reads.'
fi
if [ -n "$msg" ]; then
  if [ "$shape" = claude ]; then jq -n --arg m "$msg" '{hookSpecificOutput:{hookEventName:"PreToolUse",permissionDecision:"deny",permissionDecisionReason:$m}}'; else jq -n --arg m "$msg" '{permission:"deny",user_message:$m,agent_message:$m}'; fi
else
  jq -n '{permission:"allow"}'
fi
