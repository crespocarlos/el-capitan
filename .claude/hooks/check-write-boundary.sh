#!/usr/bin/env bash
set -euo pipefail
input=$(cat)
event=$(printf '%s' "$input" | jq -r '.hook_event_name // empty')
case "$event" in
  PreToolUse) path=$(printf '%s' "$input" | jq -r '.tool_input.file_path // empty'); shape=claude ;;
  preToolUse) path=$(printf '%s' "$input" | jq -r '.tool_input.file_path // .file_path // empty'); shape=cursor ;;
  *) echo "unknown hook_event_name: ${event:-missing}" >&2; exit 2 ;;
esac
repo=$(git -C "$(dirname "$path")" rev-parse --show-toplevel 2>/dev/null || true)
case "$path" in "$HOME/.agent/"*|"$HOME/.claude/"*|"$HOME/.cursor/"*|/tmp/*)
  jq -n '{permission:"allow"}'; exit 0 ;;
esac
case "$repo" in
  "")
    msg="Write blocked: $path is outside permitted worktrees." ;;
  *)
    case "$path" in
      "$repo"/*) jq -n '{permission:"allow"}'; exit 0 ;;
      *) msg="Write blocked: $path is outside permitted worktrees." ;;
    esac ;;
esac
if [ "$shape" = claude ]; then jq -n --arg m "$msg" '{hookSpecificOutput:{hookEventName:"PreToolUse",permissionDecision:"deny",permissionDecisionReason:$m}}'; else jq -n --arg m "$msg" '{permission:"deny",user_message:$m,agent_message:$m}'; fi
