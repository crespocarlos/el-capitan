#!/usr/bin/env bash
# Guards outbound actions: secrets in commits, implicit PR targets.
set -euo pipefail
input=$(cat)
event=$(jq -r '.hook_event_name // empty' <<<"$input")
case "$event" in
  PreToolUse) cmd=$(jq -r '.tool_input.command // empty' <<<"$input"); shape=claude ;;
  preToolUse) cmd=$(jq -r '.tool_input.command // .command // empty' <<<"$input"); shape=cursor ;;
  beforeShellExecution) cmd=$(jq -r '.command // empty' <<<"$input"); shape=cursor ;;
  *) echo "unknown hook_event_name: ${event:-missing}" >&2; exit 2 ;;
esac
cwd=$(jq -r '.cwd // empty' <<<"$input")
[ -d "$cwd" ] || cwd=$PWD

allow() { jq -n '{permission:"allow"}'; exit 0; }
deny() {
  if [ "$shape" = claude ]; then
    jq -n --arg m "$1" '{hookSpecificOutput:{hookEventName:"PreToolUse",permissionDecision:"deny",permissionDecisionReason:$m}}'
  else
    jq -n --arg m "$1" '{permission:"deny",user_message:$m,agent_message:$m}'
  fi
  exit 0
}
# Here-strings, not pipes: under pipefail, grep -q closing early fails the writer and hides a match.
matches() { grep -Eq -- "$1" <<<"$cmd"; }
added_lines() { grep -E '^\+' <<<"$1" | grep -Ev '^\+\+\+ (a/|b/|/dev/null)' || true; }

GIT_COMMIT='(^|[;&|(/[:space:]])git([[:space:]]+-[Cc][[:space:]]+[^[:space:]]+)*[[:space:]]+commit([[:space:]]|$)'
GH_PR_CREATE='(^|[;&|(/[:space:]])gh[[:space:]]+pr[[:space:]]+create([[:space:]]|$)'
DIR_FROM_C='git[[:space:]]+-C[[:space:]]+([^[:space:];&|]+)'
DIR_FROM_CD='(^|[;&|[:space:]])cd[[:space:]]+([^[:space:];&|]+)'
# High-precision formats only: a false positive blocks the commit.
SECRET_PATTERN='-----BEGIN [A-Z ]*PRIVATE KEY-----|AKIA[0-9A-Z]{16}|gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{22,}|xox[abprs]-[A-Za-z0-9-]{10,}|sk-ant-[A-Za-z0-9_-]{20,}|AIza[0-9A-Za-z_-]{35}'

repo=$cwd
dir=""
if [[ $cmd =~ $DIR_FROM_C ]]; then dir=${BASH_REMATCH[1]}
elif [[ $cmd =~ $DIR_FROM_CD ]]; then dir=${BASH_REMATCH[2]}
fi
if [ -n "$dir" ]; then
  dir=${dir//\"/}; dir=${dir//\'/}; dir=${dir/#\~/$HOME}
  [[ $dir = /* ]] || dir=$cwd/$dir
  repo=$dir
fi

if matches "$GIT_COMMIT"; then
  staged=$(git -C "$repo" diff --cached -U0 2>/dev/null) \
    || deny "Commit check failed: cannot read the git index in $repo."
  added=$(added_lines "$staged")
  if matches '[[:space:]](-a|--all|-[A-Za-z]*a[A-Za-z]*)([[:space:]]|$)'; then
    unstaged=$(git -C "$repo" diff -U0 2>/dev/null) \
      || deny "Commit check failed: cannot read the working tree in $repo."
    added+=$'\n'$(added_lines "$unstaged")
  fi
  if grep -Eq -- "$SECRET_PATTERN" <<<"$added"; then
    deny 'Commit blocked: changes being committed contain a credential-like token or private key. Remove it; rotate it if it was real.'
  fi
fi

if matches "$GH_PR_CREATE" \
  && git -C "$repo" remote get-url upstream >/dev/null 2>&1 \
  && ! matches '[[:space:]](--repo|-R)([[:space:]=]|$)'; then
  deny 'PR blocked: an upstream remote exists, so pass --repo explicitly. Target upstream unless the user chose origin.'
fi

allow
