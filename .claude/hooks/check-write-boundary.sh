#!/usr/bin/env bash
# Deny writes outside the active worktree. Fails closed on unparsable input.
set -euo pipefail

if ! command -v jq >/dev/null 2>&1; then
  echo "check-write-boundary: jq is required; denying so the guard cannot be bypassed." >&2
  exit 2
fi

input=$(cat)
if ! jq -e . >/dev/null 2>&1 <<<"$input"; then
  echo "Write blocked: hook input is not valid JSON." >&2
  exit 2
fi

event=$(printf '%s' "$input" | jq -r '.hook_event_name // empty')
cwd=$(printf '%s' "$input" | jq -r '.cwd // empty')
case "$event" in
  PreToolUse) path=$(printf '%s' "$input" | jq -r '.tool_input.file_path // empty'); shape=claude ;;
  preToolUse) path=$(printf '%s' "$input" | jq -r '.tool_input.file_path // .file_path // empty'); shape=cursor ;;
  *) echo "unknown hook_event_name: ${event:-missing}" >&2; exit 2 ;;
esac

# Tool paths may be relative to the session cwd, which is not the hook's own cwd.
case "$path" in
  /*) ;;
  *) [ -n "$cwd" ] && [ -d "$cwd" ] && path="$cwd/$path" ;;
esac

# Resolve the path before any containment check: `repo/x/../../outside.md` starts with the
# repo prefix but escapes it, and a symlinked directory inside the repo can reach outside.
# realpath normalizes `..` and follows symlinks even when the parent does not exist yet;
# the shell cannot do this reliably, so use the interpreter the hooks already require.
normalized=$(python3 -c 'import os,sys; print(os.path.realpath(sys.argv[1]))' "$path" 2>/dev/null) \
  || normalized=""
[ -n "$normalized" ] && path="$normalized"

case "$path" in "$HOME/.agent/"*|"$HOME/.claude/"*|"$HOME/.cursor/"*|/tmp/*)
  jq -n '{permission:"allow"}'; exit 0 ;;
esac

# Probe the nearest existing ancestor; a missing directory is not evidence of an escape.
probe=$(dirname "$path")
while [ ! -d "$probe" ] && [ "$probe" != "/" ] && [ "$probe" != "." ]; do
  probe=$(dirname "$probe")
done
repo=$(git -C "$probe" rev-parse --show-toplevel 2>/dev/null || true)
[ -n "$repo" ] && repo=$(cd "$repo" && pwd -P)

msg=""
if [ -z "$repo" ]; then
  msg="Write blocked: $path is outside permitted worktrees."
else
  case "$path" in
    "$repo"/*) jq -n '{permission:"allow"}'; exit 0 ;;
    *) msg="Write blocked: $path is outside $repo." ;;
  esac
fi

if [ "$shape" = claude ]; then
  jq -n --arg m "$msg" '{hookSpecificOutput:{hookEventName:"PreToolUse",permissionDecision:"deny",permissionDecisionReason:$m}}'
else
  jq -n --arg m "$msg" '{permission:"deny",user_message:$m,agent_message:$m}'
fi
