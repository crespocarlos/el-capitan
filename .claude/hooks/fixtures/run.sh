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
large_command="git reset --hard; # $(head -c 70000 < /dev/zero | tr '\0' x)"
jq -n --arg c "$large_command" '{hook_event_name:"beforeShellExecution",command:$c}' \
  | bash "$root/.claude/hooks/block-destructive-git.sh" | jq -e '.permission == "deny"' >/dev/null
printf '%s' '{"hook_event_name":"preToolUse","file_path":"/outside/file"}' | bash "$root/.claude/hooks/check-write-boundary.sh" | jq -e '.permission == "deny"' >/dev/null
printf '%s' '{"hook_event_name":"PreToolUse","tool_input":{"file_path":"/outside/file"}}' | bash "$root/.claude/hooks/check-write-boundary.sh" | jq -e '.hookSpecificOutput.permissionDecision == "deny"' >/dev/null

publish() { jq -n --arg c "$1" --arg d "${2:-$repo}" '{hook_event_name:"beforeShellExecution",command:$c,cwd:$d}' | bash "$root/.claude/hooks/check-publish.sh" | jq -r '.permission'; }
repo="$home/repo"
git init -q "$repo"
printf 'clean\n' > "$repo/a.txt"; git -C "$repo" add a.txt
test "$(publish 'git commit -m ok')" = allow
printf 'key=%s\n' "AKIA""ABCDEFGHIJKLMNOP" > "$repo/b.txt"; git -C "$repo" add b.txt
test "$(publish 'git commit -m leak')" = deny
test "$(publish "git -C $repo commit -m leak" "$home")" = deny
seq 1 40000 > "$repo/big.txt"; git -C "$repo" add big.txt
test "$(publish 'git commit -m large')" = deny
git -C "$repo" rm -q --cached b.txt big.txt
test "$(publish 'gh pr create --draft')" = allow
git -C "$repo" remote add upstream https://github.com/example/upstream.git
test "$(publish 'gh pr create --draft')" = deny
test "$(publish 'git commit -m x && gh pr create --draft')" = deny
test "$(publish 'gh pr create --draft --repo example/upstream')" = allow
test "$(publish 'ls')" = allow
jq -n --arg d "$repo" '{hook_event_name:"PreToolUse",tool_input:{command:"gh pr create"},cwd:$d}' | bash "$root/.claude/hooks/check-publish.sh" | jq -e '.hookSpecificOutput.permissionDecision == "deny"' >/dev/null
