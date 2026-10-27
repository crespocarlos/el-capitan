#!/usr/bin/env bash
set -euo pipefail
root=$(cd "$(dirname "$0")/../../.." && pwd)
home=$(mktemp -d)
trap 'rm -rf "$home"' EXIT
for fixture in "$root"/.claude/hooks/fixtures/*-tool.json; do
  output=$(HOME="$home" bash "$root/.claude/hooks/log-tool-use.sh" < "$fixture")
  printf '%s\n' "$output" | jq -e . >/dev/null
done
telemetry=$(find "$home/.agent/memory/.sessions" -name '*.jsonl' -print -quit)
test -n "$telemetry"
jq -e '.event and .action and .target' "$telemetry" >/dev/null
printf '%s' '{"conversation_id":"repeat","hook_event_name":"postToolUseFailure","tool_name":"Shell"}' \
  | HOME="$home" bash "$root/.claude/hooks/log-tool-use.sh" >/dev/null
printf '%s' '{"conversation_id":"repeat","hook_event_name":"postToolUseFailure","tool_name":"Shell"}' \
  | HOME="$home" bash "$root/.claude/hooks/log-tool-use.sh" >/dev/null
prompt=$(printf '%s' '{"conversation_id":"repeat"}' \
  | HOME="$home" bash "$root/.claude/hooks/memory-capture-prompt.sh")
printf '%s\n' "$prompt" | jq -e '.followup_message' >/dev/null
again=$(printf '%s' '{"conversation_id":"repeat"}' \
  | HOME="$home" bash "$root/.claude/hooks/memory-capture-prompt.sh")
test "$(printf '%s' "$again" | jq -r 'keys | length')" -eq 0
printf '%s' '{"hook_event_name":"beforeShellExecution","command":"git reset --hard"}' | bash "$root/.claude/hooks/block-destructive-git.sh" | jq -e '.permission == "deny"' >/dev/null
printf '%s' '{"hook_event_name":"PreToolUse","tool_input":{"command":"git reset --hard"}}' | bash "$root/.claude/hooks/block-destructive-git.sh" | jq -e '.hookSpecificOutput.permissionDecision == "deny"' >/dev/null
printf '%s' '{"hook_event_name":"preToolUse","file_path":"/outside/file"}' | bash "$root/.claude/hooks/check-write-boundary.sh" | jq -e '.permission == "deny"' >/dev/null
printf '%s' '{"hook_event_name":"PreToolUse","tool_input":{"file_path":"/outside/file"}}' | bash "$root/.claude/hooks/check-write-boundary.sh" | jq -e '.hookSpecificOutput.permissionDecision == "deny"' >/dev/null
