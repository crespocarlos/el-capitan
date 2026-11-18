#!/usr/bin/env bash
# Deny Python snippets that rewrite a tracked repository file; use Edit or Write instead.
set -euo pipefail

if ! command -v jq >/dev/null 2>&1; then
  echo "block-shell-source-edits: jq is required; denying so the guard cannot be bypassed." >&2
  exit 2
fi

input=$(cat)
if ! jq -e . >/dev/null 2>&1 <<<"$input"; then
  echo "block-shell-source-edits: hook input is not valid JSON; denying." >&2
  exit 2
fi

event=$(jq -r '.hook_event_name // empty' <<<"$input")
case "$event" in
  PreToolUse) command=$(jq -r '.tool_input.command // empty' <<<"$input"); shape=claude ;;
  preToolUse) command=$(jq -r '.tool_input.command // .command // empty' <<<"$input"); shape=cursor ;;
  beforeShellExecution) command=$(jq -r '.command // empty' <<<"$input"); shape=cursor ;;
  *) echo "block-shell-source-edits: unknown hook event: ${event:-missing}" >&2; exit 2 ;;
esac
cwd=$(jq -r '.cwd // empty' <<<"$input")
[ -d "$cwd" ] || cwd=$PWD

allow() { jq -n '{permission:"allow"}'; exit 0; }
deny() {
  local message=$1
  if [ "$shape" = claude ]; then
    jq -n --arg m "$message" \
      '{hookSpecificOutput:{hookEventName:"PreToolUse",permissionDecision:"deny",permissionDecisionReason:$m}}'
  else
    jq -n --arg m "$message" '{permission:"deny",user_message:$m,agent_message:$m}'
  fi
  exit 0
}

# This guard intentionally targets Python snippets, not normal Python tools. A snippet that writes a
# task artifact is permitted unless it names a tracked file; a snippet that rewrites tracked source
# loses the edit log and must use the native Edit or Write tool instead.
# The `/?` before `python` also matches an absolute or venv-relative interpreter
# (`/usr/bin/python3`, `.venv/bin/python3`), which has no word boundary this guard can rely on
# otherwise; `([[:space:]]|$)` lets a bare `python3<<PY` (no space before the heredoc) still match.
grep -Eq '(^|[;&|[:space:]]|/)python([0-9.]*)?([[:space:]]|$).*(<<|-[[:space:]]*c)' <<<"$command" || allow
# `r+` opens for read-and-write without truncation, a real in-place-rewrite mode `[wax+]` alone
# does not cover.
grep -Eq 'write_(text|bytes)[[:space:]]*\(|open[[:space:]]*\(.*["'\'']([wax+]+|r\+)["'\'']|os\.replace[[:space:]]*\(|shutil\.(copy|move)' \
  <<<"$command" || allow

root=$(git -C "$cwd" rev-parse --show-toplevel 2>/dev/null) || allow

# Check candidate path literals individually against the index instead of enumerating every
# tracked file: avoids a full `git ls-files` scan per matching command on a large monorepo
# checkout, and resolving each candidate against `$cwd` (rather than a raw substring match against
# the repo-root-relative form) catches a write issued after `cd`-ing into a subdirectory.
while IFS= read -r candidate; do
  [ -n "$candidate" ] || continue
  resolved=$(cd "$cwd" 2>/dev/null && realpath "$candidate" 2>/dev/null) || continue
  case "$resolved" in
    "$root"/*) rel=${resolved#"$root"/} ;;
    *) continue ;;
  esac
  if git -C "$root" ls-files --error-unmatch -- "$rel" >/dev/null 2>&1; then
    deny "Shell rewrite blocked: Python snippets must not rewrite tracked file '$rel'. Use the Edit or Write tool."
  fi
done < <(grep -oE '"[^"]+"|'"'"'[^'"'"']+'"'"'' <<<"$command" | sed -e 's/^.//' -e 's/.$//')

allow
