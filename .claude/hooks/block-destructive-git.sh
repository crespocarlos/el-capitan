#!/usr/bin/env bash
# Deny destructive git operations and local PR-ref reads.
# Fails closed: unparsable input or a missing parser denies the command.
set -euo pipefail

if ! command -v jq >/dev/null 2>&1; then
  echo "block-destructive-git: jq is required; denying so the guard cannot be bypassed." >&2
  exit 2
fi

input=$(cat)
if ! jq -e . >/dev/null 2>&1 <<<"$input"; then
  echo "block-destructive-git: hook input is not valid JSON; denying." >&2
  exit 2
fi

event=$(printf '%s' "$input" | jq -r '.hook_event_name // empty')
case "$event" in
  PreToolUse) cmd=$(printf '%s' "$input" | jq -r '.tool_input.command // empty'); shape=claude ;;
  preToolUse) cmd=$(printf '%s' "$input" | jq -r '.tool_input.command // .command // empty'); shape=cursor ;;
  beforeShellExecution) cmd=$(printf '%s' "$input" | jq -r '.command // empty'); shape=cursor ;;
  *) echo "unknown hook_event_name: ${event:-missing}" >&2; exit 2 ;;
esac

msg=''
# `git` prefix: any run of global options (`-C dir`, `-c k=v`, `--git-dir=`,
# `--work-tree`, `--no-pager`) before the subcommand. Destructive subcommands are just as
# destructive through them, and these are the forms an agent reaches for in a worktree.
GIT='git(([[:space:]]+-{1,2}[^[:space:];&|]+([[:space:]]+[^[:space:];&|]+)?)*)[[:space:]]+'
RESET_OR_CLEAN="${GIT}(reset[[:space:]]+--hard|clean[[:space:]]+-[A-Za-z]*f)"
# `push` is destructive with -f/--force, and with a `+refspec`.
FORCE_PUSH="${GIT}push([[:space:]][^;&|]*)?([[:space:]](-[A-Za-z]*f[A-Za-z]*|--force(-if-includes)?)([[:space:]]|$)|[[:space:]]\+[^[:space:]]+)"

# Quoted text is data: `git commit -m "do not git reset --hard"` must not be denied, and a
# wrapper (`bash -c "git reset --hard"`) is already covered by the escape rule below.
INSPECT=$(printf '%s' "$cmd" | sed -E "s/'[^']*'/''/g; s/\"[^\"]*\"/\"\"/g")

if grep -Eqi -- "$RESET_OR_CLEAN" <<<"$INSPECT"; then
  msg='Destructive git command blocked.'
elif grep -Eqi -- "$FORCE_PUSH" <<<"$INSPECT" && ! grep -q -- '--force-with-lease' <<<"$INSPECT"; then
  msg='Force push blocked. Use --force-with-lease, or ask the user to confirm.'
elif grep -Eqi '(^|[;&| ]+)gh[[:space:]]+pr[[:space:]]+(checkout|co)([[:space:]]|$)|(^|[;&| ]+)git[[:space:]].*(fetch|pull)[[:space:]].*(refs/)?pull/[0-9]+' <<<"$cmd"; then
  msg='Pulling a PR into the local checkout is blocked. Read it with `gh pr diff <n>` and `gh api repos/<owner>/<repo>/contents/<path>?ref=<headSHA>`.'
elif grep -Eqi '(^|[;&| ]+)git[[:space:]].*(show|diff|log|cat-file|rev-parse|fetch|pull).*(refs/)?pull/' <<<"$cmd"; then
  msg='Reading a local PR ref is blocked. Read PR-head content with `gh pr diff <n>` or `gh api repos/<owner>/<repo>/contents/<path>?ref=<headSHA>`.'
elif grep -Eq '(^|[;&| ]+)(gh|git)[^;&|]*[\\$]' <<<"$cmd"; then
  msg='Shell-expanded or escaped gh/git commands are blocked. Use the literal form so the guard can read it.'
fi

if [ -n "$msg" ]; then
  if [ "$shape" = claude ]; then
    jq -n --arg m "$msg" '{hookSpecificOutput:{hookEventName:"PreToolUse",permissionDecision:"deny",permissionDecisionReason:$m}}'
  else
    jq -n --arg m "$msg" '{permission:"deny",user_message:$m,agent_message:$m}'
  fi
else
  jq -n '{permission:"allow"}'
fi
