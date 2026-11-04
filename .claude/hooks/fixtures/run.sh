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
guard() { jq -n --arg c "$1" '{hook_event_name:"beforeShellExecution",command:$c}' | bash "$root/.claude/hooks/block-destructive-git.sh" | jq -r '.permission'; }
test "$(guard 'gh pr checkout 301097')" = deny
test "$(guard 'cd x && gh pr co 12')" = deny
test "$(guard 'gh pr chec\kout 12')" = deny
test "$(guard 'git fetch upstream pull/301097/head:pr301097')" = deny
test "$(guard 'git fetch origin refs/pull/5/head')" = deny
test "$(guard 'git fetch origin refs/pull/$PR/head')" = deny
test "$(guard 'git show refs/pull/42/head:path')" = deny
test "$(guard 'git diff refs/pull/42/head')" = deny
test "$(guard 'gh pr diff 301097')" = allow
test "$(guard 'git fetch upstream main')" = allow
test "$(guard 'gh pr view 1 --json headRefOid')" = allow
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
printf 'key=%s\n' "AKIA""ABCDEFGHIJKLMNOP" > "$repo/c.txt"; seq 1 40000 >> "$repo/c.txt"; git -C "$repo" add c.txt
test "$(publish 'git commit -m secret-on-line-1-of-large-diff')" = deny
git -C "$repo" rm -q --cached c.txt
test "$(publish 'gh pr create --draft')" = allow
git -C "$repo" remote add upstream https://github.com/example/upstream.git
test "$(publish 'gh pr create --draft')" = deny
test "$(publish 'git commit -m x && gh pr create --draft')" = deny
test "$(publish 'gh pr create --draft --repo example/upstream')" = allow
test "$(publish 'ls')" = allow
jq -n --arg d "$repo" '{hook_event_name:"PreToolUse",tool_input:{command:"gh pr create"},cwd:$d}' | bash "$root/.claude/hooks/check-publish.sh" | jq -e '.hookSpecificOutput.permissionDecision == "deny"' >/dev/null

tasks="$home/tasks"; mkdir -p "$tasks"
mkspec() { mkdir -p "$tasks/$1"; printf '%s' "$2" > "$tasks/$1/SPEC.md"; [ -z "${3:-}" ] || printf '%s\n' "$3" > "$tasks/$1/REVIEW.md"; [ -z "${4:-}" ] || touch -t "$4" "$tasks/$1"/*; return 0; }
status_of() { awk '/^## Status/{getline; print; exit}' "$tasks/$1/SPEC.md"; }
mkspec abandoned $'# T\n\n## Status\nABANDONED\n\n- [x] a\n' 'Verdict: pass'
mkspec onhold $'# T\n\n## Status\nON-HOLD (auto-hold: no activity 14d; was APPROVED)\n\n- [x] a\n' 'Verdict: pass'
mkspec drafting-old $'# T\n\n## Status\nDRAFTING\n\n- [x] a\n' 'Verdict: pass' 202610010000
mkspec suffixed-old $'# T\n\n## Status\nDRAFTING (updated by Task 9; needs approval)\n\n- [ ] a\n' '' 202610010000
mkspec drafting-new $'# T\n\n## Status\nDRAFTING\n\n- [ ] a\n'
mkspec implementing-pass $'# T\n\n## Status\nIMPLEMENTING\n\n- [x] a\n' 'Verdict: PASS. No findings.'
mkspec implementing-nits $'# T\n\n## Status\nIMPLEMENTING\n\n- [x] a\n' 'Verdict: pass-with-nits'
mkspec implementing-rerun $'# T\n\n## Status\nIMPLEMENTING\n\n- [x] a\n' $'Verdict: pass\n\nround 2\nVerdict: BLOCK'
mkspec empty-status $'# T\n\n## Status\n\n## Summary\n\n- [x] a\n' 'Verdict: pass'
python3 "$root/.agent/tools/crew-ls.py" --tasks-dir "$tasks" --reconcile --apply >/dev/null
test "$(status_of abandoned)" = ABANDONED
test "$(status_of onhold)" = 'ON-HOLD (auto-hold: no activity 14d; was APPROVED)'
test "$(status_of drafting-old)" = 'ON-HOLD (auto-hold: no activity 14d; was DRAFTING)'
test "$(status_of suffixed-old)" = 'ON-HOLD (auto-hold: no activity 14d; was DRAFTING)'
test "$(status_of drafting-new)" = DRAFTING
test "$(status_of implementing-pass)" = done
test "$(status_of implementing-nits)" = IMPLEMENTING
test "$(status_of implementing-rerun)" = IMPLEMENTING
grep -q '^## Summary$' "$tasks/empty-status/SPEC.md"
grep -q 'DRAFTING → ON-HOLD' "$tasks/drafting-old/PROGRESS.md"

hook_home="$home/hook-home"; mkdir -p "$hook_home/.agent/bin" "$hook_home/.agent/tasks"
ln -s "$root/.agent/tools/crew-ls.py" "$hook_home/.agent/bin/crew-ls.py"
mkdir -p "$hook_home/.agent/tasks/idle" "$hook_home/.agent/tasks/shipped"
printf '# T\n\n## Status\nDRAFTING\n\n- [ ] a\n' > "$hook_home/.agent/tasks/idle/SPEC.md"; touch -t 202610010000 "$hook_home/.agent/tasks/idle/SPEC.md"
printf '# T\n\n## Status\ndone\n\n- [x] a\n' > "$hook_home/.agent/tasks/shipped/SPEC.md"
hook_out=$(HOME="$hook_home" bash "$root/.claude/hooks/spec-status-reconcile.sh")
grep -q 'spec-status: idle -> ON-HOLD' <<<"$hook_out"
grep -q '1 done spec(s) lack a review pass' <<<"$hook_out"
missing_out=$(HOME="$home/no-tool" bash "$root/.claude/hooks/spec-status-reconcile.sh")
grep -q 'reconcile failed' <<<"$missing_out"
table_out=$(python3 "$root/.agent/tools/crew-ls.py" --tasks-dir "$tasks")
grep -q '^STATE  *TASK  *BRANCH  *REVIEW  *AGE$' <<<"$table_out"
python3 "$root/.agent/tools/crew-ls.py" --tasks-dir "$tasks" --tsv | awk -F'\t' 'NF!=5{bad=1} END{exit bad}'
md_out=$(python3 "$root/.agent/tools/crew-ls.py" --tasks-dir "$tasks" --md)
grep -q '^| STATE | TASK | BRANCH | REVIEW | AGE |$' <<<"$md_out"
grep -q '^|---|---|---|---|---|$' <<<"$md_out"
