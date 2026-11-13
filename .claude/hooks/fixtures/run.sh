#!/usr/bin/env bash
set -euo pipefail
root=$(cd "$(dirname "$0")/../../.." && pwd)
home=$(mktemp -d)
trap 'rm -rf "$home"' EXIT
# Isolate from the caller's real memory store; otherwise a CREW_MEMORY_DIR in the
# environment redirects telemetry away from $home and every check below sees nothing.
unset CREW_MEMORY_DIR CREW_JOURNAL_DIR CREW_TASK_DIR
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
test "$(guard 'git -C /tmp/repo reset --hard')" = deny
test "$(guard 'git -c user.email=x reset --hard')" = deny
test "$(guard 'git push -f origin main')" = deny
test "$(guard 'git clean -fd')" = deny
test "$(guard 'git push --force-with-lease origin main')" = allow
# Global options before the subcommand must not open a hole.
test "$(guard 'git --git-dir=/tmp/a/.git reset --hard')" = deny
test "$(guard 'git --work-tree=/tmp/x reset --hard')" = deny
test "$(guard 'git --no-pager reset --hard')" = deny
test "$(guard 'git -C /tmp/a -C /tmp/b reset --hard')" = deny
test "$(guard 'git push origin +main')" = deny
test "$(guard 'git push --force-if-includes origin x')" = deny
# Read-only variants stay allowed.
test "$(guard 'git clean -n')" = allow
test "$(guard 'git reset --soft HEAD~1')" = allow
test "$(guard 'git status')" = allow
# A quoted message is data, not a command.
test "$(guard 'git commit -m "please do not git reset --hard here"')" = allow
large_command="git reset --hard; # $(head -c 70000 < /dev/zero | tr '\0' x)"
jq -n --arg c "$large_command" '{hook_event_name:"beforeShellExecution",command:$c}' \
  | bash "$root/.claude/hooks/block-destructive-git.sh" | jq -e '.permission == "deny"' >/dev/null
printf '%s' '{"hook_event_name":"preToolUse","file_path":"/outside/file"}' | bash "$root/.claude/hooks/check-write-boundary.sh" | jq -e '.permission == "deny"' >/dev/null
printf '%s' '{"hook_event_name":"PreToolUse","tool_input":{"file_path":"/outside/file"}}' | bash "$root/.claude/hooks/check-write-boundary.sh" | jq -e '.hookSpecificOutput.permissionDecision == "deny"' >/dev/null
# `..` must be normalized before the containment check, and a new directory must not be
# mistaken for an escape.
boundary() { jq -n --arg p "$1" --arg c "$repo" '{hook_event_name:"PreToolUse",tool_input:{file_path:$p},cwd:$c}' | bash "$root/.claude/hooks/check-write-boundary.sh" | jq -r '.hookSpecificOutput.permissionDecision // "allow"'; }
repo="$home/brepo"; git init -q "$repo"
test "$(boundary "$repo/new.md")" = allow
test "$(boundary "$repo/deep/a/b/c.ts")" = allow
test "$(boundary "$repo/../outside.md")" = deny
test "$(boundary "$repo/sub/../../outside.md")" = deny
test "$(boundary "$home/outside.md")" = deny

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
# `cd`/paths inside a quoted commit message are data, not commands: they must neither
# block a clean commit nor redirect the secret scan away from the real index.
printf 'clean\n' > "$repo/d.txt"; git -C "$repo" add d.txt
test "$(publish 'git commit -m "fix cd back behavior"')" = allow
test "$(publish "git commit -m \"restore cd $home behavior\"")" = allow
git -C "$repo" rm -q --cached d.txt
printf 'key=%s\n' "AKIA""ABCDEFGHIJKLMNOP" > "$repo/e.txt"; git -C "$repo" add e.txt
test "$(publish 'git commit -m "restore cd /tmp behavior"')" = deny
# A quoted directory must still be read, or the secret scan runs in the wrong repo.
other="$home/other-repo"; git init -q "$other"
printf 'ok\n' > "$other/a.txt"; git -C "$other" add a.txt
git -C "$other" -c user.name=x -c user.email=x@y commit -qm ok
test "$(publish "cd '$other' && git commit -m clean", "$repo")" = allow
test "$(publish "git -C \"$other\" commit -m clean", "$repo")" = allow
git -C "$repo" rm -q --cached e.txt
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
test "$(status_of implementing-pass)" = IMPLEMENTING
test "$(status_of implementing-nits)" = IMPLEMENTING
test "$(status_of implementing-rerun)" = IMPLEMENTING
grep -q '^## Summary$' "$tasks/empty-status/SPEC.md"
grep -q 'DRAFTING → ON-HOLD' "$tasks/drafting-old/PROGRESS.md"

hook_home="$home/hook-home"; mkdir -p "$hook_home/.agent/bin" "$hook_home/.agent/tasks"
ln -s "$root/.agent/tools/crew-ls.py" "$hook_home/.agent/bin/crew-ls.py"
mkdir -p "$hook_home/.agent/tasks/idle" "$hook_home/.agent/tasks/shipped"
printf '# T\n\n## Status\nDRAFTING\n\n- [ ] a\n' > "$hook_home/.agent/tasks/idle/SPEC.md"; touch -t 202610010000 "$hook_home/.agent/tasks/idle/SPEC.md"
printf '# T\n\n## Status\ndone\n\n- [x] a\n' > "$hook_home/.agent/tasks/shipped/SPEC.md"
mkdir -p "$hook_home/.agent/tasks/ready" "$hook_home/.agent/tasks/stuck"
printf '# T\n\n## Status\nIMPLEMENTING\n\n- [x] a\n' > "$hook_home/.agent/tasks/ready/SPEC.md"
printf 'Verdict: pass\n' > "$hook_home/.agent/tasks/ready/REVIEW.md"
printf '# T\n\n## Status\nIMPLEMENTING\n\n- [ ] a\n' > "$hook_home/.agent/tasks/stuck/SPEC.md"; touch -t 202610010000 "$hook_home/.agent/tasks/stuck/SPEC.md"
hook_out=$(HOME="$hook_home" bash "$root/.claude/hooks/spec-status-reconcile.sh")
grep -q 'spec-status: idle -> ON-HOLD' <<<"$hook_out"
grep -q '1 done spec(s) lack a review pass' <<<"$hook_out"
grep -q 'spec-status: 1 ready to open PR: ready' <<<"$hook_out"
grep -q 'spec-status: 1 stalled IMPLEMENTING: stuck' <<<"$hook_out"
missing_out=$(HOME="$home/no-tool" bash "$root/.claude/hooks/spec-status-reconcile.sh")
grep -q 'reconcile failed' <<<"$missing_out"
table_out=$(python3 "$root/.agent/tools/crew-ls.py" --tasks-dir "$tasks")
grep -q '^STATE  *TASK  *BRANCH  *REVIEW  *AGE$' <<<"$table_out"
python3 "$root/.agent/tools/crew-ls.py" --tasks-dir "$tasks" --tsv | awk -F'\t' 'NF!=5{bad=1} END{exit bad}'
md_out=$(python3 "$root/.agent/tools/crew-ls.py" --tasks-dir "$tasks" --md)
grep -q '^| STATE | TASK | BRANCH | REVIEW | AGE |$' <<<"$md_out"
grep -q '^|---|---|---|---|---|$' <<<"$md_out"
ls_tool="$root/.agent/tools/crew-ls.py"
mkspec approved-old $'# T\n\n## Status\nAPPROVED\n\n- [ ] a\n' '' 202610010000
mkspec implementing-old-open $'# T\n\n## Status\nIMPLEMENTING\n\n- [ ] a\n' 'Verdict: pass' 202610010000
mkspec approved-done-old $'# T\n\n## Status\nAPPROVED\n\n- [x] a\n' 'Verdict: pass' 202610010000
mkspec implementing-nobox $'# T\n\n## Status\nIMPLEMENTING\n\nno boxes\n' 'Verdict: pass'
mkspec implementing-warn $'# T\n\n## Status\nIMPLEMENTING\n\n- [x] a\n' 'Verdict: warn'
python3 "$ls_tool" --tasks-dir "$tasks" --reconcile --apply >/dev/null
test "$(status_of approved-old)" = 'ON-HOLD (auto-hold: no activity 14d; was APPROVED)'
test "$(status_of implementing-old-open)" = IMPLEMENTING
test "$(status_of approved-done-old)" = 'ON-HOLD (auto-hold: no activity 14d; was APPROVED)'
reconcile_out=$(python3 "$ls_tool" --tasks-dir "$tasks" --reconcile)
section() { awk -v h="$1" 'index($0,h)==1{f=1;next} /^[a-z]/{f=0} f' <<<"$reconcile_out"; }
ready=$(section 'ready to open PR')
grep -q 'implementing-pass' <<<"$ready"
grep -q 'implementing-warn' <<<"$ready"
for name in implementing-nits implementing-rerun implementing-old-open implementing-nobox; do
  if grep -q "$name" <<<"$ready"; then exit 1; fi
done
grep -q 'implementing-old-open' <<<"$(section 'stalled IMPLEMENTING')"
if grep -q 'implementing-pass' <<<"$(section 'stalled IMPLEMENTING')"; then exit 1; fi

fails() { local expect=$1; shift; local rc=0 err; err=$("$@" 2>&1 >/dev/null) || rc=$?; test "$rc" -ne 0; grep -q -- "$expect" <<<"$err"; }
mkspec approved-new $'# T\n\n## Status\nAPPROVED\n\n- [x] a\n' 'Verdict: warn'
fails 'not APPROVED' python3 "$ls_tool" --mark-implementing "$tasks/drafting-new"
fails 'no SPEC.md' python3 "$ls_tool" --mark-implementing "$tasks/missing"
python3 "$ls_tool" --mark-implementing "$tasks/approved-new" >/dev/null
test "$(status_of approved-new)" = IMPLEMENTING
grep -q 'APPROVED → IMPLEMENTING' "$tasks/approved-new/PROGRESS.md"
python3 "$ls_tool" --mark-implementing "$tasks/approved-new" | grep -q 'already implementing'
python3 "$ls_tool" --mark-done "$tasks/approved-new" --pr-url https://example.test/pr/2 >/dev/null
test "$(status_of approved-new)" = DONE

printf '{"slug":"implementing-pass","branch":"feature/x"}' > "$tasks/implementing-pass/.task-id"
fails 'current branch is feature/y' python3 "$ls_tool" --mark-done "$tasks/implementing-pass" --pr-url x --branch feature/y
test "$(status_of implementing-pass)" = IMPLEMENTING
python3 "$ls_tool" --mark-done "$tasks/implementing-pass" --pr-url https://example.test/pr/1 --branch feature/x >/dev/null
test "$(status_of implementing-pass)" = DONE
grep -q 'IMPLEMENTING → DONE (PR opened: https://example.test/pr/1)' "$tasks/implementing-pass/PROGRESS.md"
python3 "$ls_tool" --mark-done "$tasks/implementing-pass" --pr-url x | grep -q 'already done'
fails 'unchecked' python3 "$ls_tool" --mark-done "$tasks/implementing-old-open" --pr-url x
fails 'need pass or warn' python3 "$ls_tool" --mark-done "$tasks/implementing-rerun" --pr-url x
fails 'not IMPLEMENTING' python3 "$ls_tool" --mark-done "$tasks/drafting-new" --pr-url x
fails 'no SPEC.md' python3 "$ls_tool" --mark-done "$tasks/missing" --pr-url x
fails '--pr-url' python3 "$ls_tool" --mark-done "$tasks/drafting-new"
test "$(status_of drafting-new)" = DRAFTING
python3 "$ls_tool" --mark-done "$tasks/implementing-old-open" --pr-url x --force >/dev/null
test "$(status_of implementing-old-open)" = DONE

# Gate 1: APPROVED is written by --mark-approved, never hand-edited.
mkspec gate1 $'# T\n\n## Status\nDRAFTING\n\n- [ ] a\n'
python3 "$ls_tool" --mark-approved "$tasks/gate1" >/dev/null
test "$(status_of gate1)" = APPROVED
python3 "$ls_tool" --mark-approved "$tasks/gate1" | grep -q 'already approved'
fails 'not DRAFTING' python3 "$ls_tool" --mark-approved "$tasks/implementing-pass"
mkspec gate1-open $'# T\n\n## Status\nDRAFTING\n\n## Open questions\n- [NEEDS CLARIFICATION: which API?]\n\n- [ ] a\n'
fails 'NEEDS CLARIFICATION' python3 "$ls_tool" --mark-approved "$tasks/gate1-open"
test "$(status_of gate1-open)" = DRAFTING

# A typed ## Tests block with no runnable Command is not approvable: crew test would WARN on it.
mkspec gate1-notests $'# T\n\n## Status\nDRAFTING\n\n## Tests\n### Unit\n- **Command**: none\n\n- [ ] a\n'
fails 'spec-typed-tests' python3 "$ls_tool" --mark-approved "$tasks/gate1-notests"
test "$(status_of gate1-notests)" = DRAFTING
mkspec gate1-tests $'# T\n\n## Status\nDRAFTING\n\n## Tests\n### Unit\n- **Command**: `pytest`\n\n- [ ] a\n'
python3 "$ls_tool" --mark-approved "$tasks/gate1-tests" >/dev/null
test "$(status_of gate1-tests)" = APPROVED

# .task-id records the implementing branch so a worktree still resolves the task.
mkspec gate1-branch $'# T\n\n## Status\nDRAFTING\n\n- [ ] a\n'
printf '{"slug":"gate1-branch","branch":"main"}' > "$tasks/gate1-branch/.task-id"
python3 "$ls_tool" --mark-approved "$tasks/gate1-branch" >/dev/null
python3 "$ls_tool" --mark-implementing "$tasks/gate1-branch" --branch feat/worktree >/dev/null
grep -q '"branch": "feat/worktree"' "$tasks/gate1-branch/.task-id"
# A hand-edited APPROVED spec with an open clarification still cannot be implemented.
mkspec gate1-blocked $'# T\n\n## Status\nAPPROVED\n\n## Open questions\n- [NEEDS CLARIFICATION: which API?]\n\n- [ ] a\n'
fails 'NEEDS CLARIFICATION' python3 "$ls_tool" --mark-implementing "$tasks/gate1-blocked"
test "$(status_of gate1-blocked)" = APPROVED

# --apply must report write failures in its exit code.
mkspec apply-ro $'# T\n\n## Status\nDRAFTING\n\n- [ ] a\n'
touch -t 202610010000 "$tasks/apply-ro"/*
chmod 555 "$tasks/apply-ro"
if python3 "$ls_tool" --tasks-dir "$tasks" --reconcile --apply >/dev/null 2>&1; then exit 1; fi
chmod 755 "$tasks/apply-ro"
test "$(status_of apply-ro)" = DRAFTING

# A review records the commit it approved; a review of a different tree must block close-out.
mkspec reviewed $'# T\n\n## Status\nIMPLEMENTING\n\n- [x] a\n' $'Verdict: pass\n\nReviewed at: 0123456789abcdef0123456789abcdef01234567\n'
fails 'cannot verify that review' python3 "$ls_tool" --mark-done "$tasks/reviewed" --pr-url x --branch main
test "$(status_of reviewed)" = IMPLEMENTING

# A reviewed ancestor of HEAD passes, because crew commit runs after crew review.
git_sha=$(git -C "$root" rev-parse HEAD)
mkspec reviewed-ancestor $'# T\n\n## Status\nIMPLEMENTING\n\n- [x] a\n' "Verdict: pass

Reviewed at: $git_sha
"
python3 "$ls_tool" --mark-done "$tasks/reviewed-ancestor" --pr-url x --branch main >/dev/null
test "$(status_of reviewed-ancestor)" = DONE

bad_tools="$home/bad-tools"; mkdir -p "$bad_tools"
cp "$ls_tool" "$root/.agent/tools/log-progress.py" "$root/.agent/scripts/task_status.py" "$bad_tools/"
printf '{bad' > "$bad_tools/transitions.json"
python3 "$bad_tools/crew-ls.py" --tasks-dir "$tasks" >/dev/null
fails 'error: transitions.json' python3 "$bad_tools/crew-ls.py" --tasks-dir "$tasks" --reconcile
printf '{"idle_days":14,"auto":[{"from":["DRAFTING"],"kind":"hold","when":["bogus"],"status":"x","log":"y"}]}' > "$bad_tools/transitions.json"
fails 'unknown predicate' python3 "$bad_tools/crew-ls.py" --tasks-dir "$tasks" --reconcile --apply
printf '{"idle_days":14,"auto":[{"from":["DRAFTING"],"kind":"hold","when":["idle"],"status":"{typo}","log":"y"}]}' > "$bad_tools/transitions.json"
fails 'error: transitions.json' python3 "$bad_tools/crew-ls.py" --tasks-dir "$tasks" --reconcile --apply
