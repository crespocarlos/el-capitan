#!/usr/bin/env bash
set -euo pipefail
root=$(cd "$(dirname "$0")/../../.." && pwd)
for fixture in "$root"/.claude/hooks/fixtures/*-tool.json; do
  output=$(HOME=$(mktemp -d) bash "$root/.claude/hooks/log-tool-use.sh" < "$fixture")
  printf '%s\n' "$output" | jq -e . >/dev/null
  expected=$(jq -r '.session_id // .conversation_id' "$fixture")
  actual=$(printf '%s' "$output" | jq -r .session)
  test "$actual" = "$expected"
done
printf '%s' '{"hook_event_name":"beforeShellExecution","command":"git reset --hard"}' | bash "$root/.claude/hooks/block-destructive-git.sh" | jq -e '.permission == "deny"' >/dev/null
printf '%s' '{"hook_event_name":"PreToolUse","tool_input":{"command":"git reset --hard"}}' | bash "$root/.claude/hooks/block-destructive-git.sh" | jq -e '.hookSpecificOutput.permissionDecision == "deny"' >/dev/null
printf '%s' '{"hook_event_name":"preToolUse","file_path":"/outside/file"}' | bash "$root/.claude/hooks/check-write-boundary.sh" | jq -e '.permission == "deny"' >/dev/null
printf '%s' '{"hook_event_name":"PreToolUse","tool_input":{"file_path":"/outside/file"}}' | bash "$root/.claude/hooks/check-write-boundary.sh" | jq -e '.hookSpecificOutput.permissionDecision == "deny"' >/dev/null
