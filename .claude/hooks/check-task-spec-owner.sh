#!/usr/bin/env bash
# Refuse to write a SPEC.md whose slug disagrees with the task directory it lands in.
#
# A task directory records the spec it owns in `.task-id`, and the pipeline resolves "the current
# task" with `resolve-task-dir.py`, which answers with the newest non-DONE task for the branch. On a
# repository where every task lives on one branch, that is unrelated, already-finished work. Writing a
# new spec into that directory destroys the completed task's spec, and task directories sit outside
# the repository, so no version control recovers it. That happened once; this is the structural fix.
#
# The rule is narrow on purpose: only a write to a `SPEC.md` directly inside `~/.agent/tasks/<uuid>/`
# is checked, and only when that directory already has a `.task-id` naming a different slug. Creating
# a spec in a fresh directory has no `.task-id` yet, so it passes. Editing an approved spec in its own
# directory passes.
#
# Fails closed: unparsable input or a missing parser denies, because a guard that silently stops
# guarding is how the original loss went unnoticed.
set -euo pipefail

if ! command -v jq >/dev/null 2>&1; then
  echo "check-task-spec-owner: jq is required; denying so the guard cannot be bypassed." >&2
  exit 2
fi

input=$(cat)
if ! jq -e . >/dev/null 2>&1 <<<"$input"; then
  echo "check-task-spec-owner: hook input is not valid JSON; denying." >&2
  exit 2
fi

event=$(jq -r '.hook_event_name // empty' <<<"$input")
case "$event" in
  PreToolUse|preToolUse) ;;
  *) echo "check-task-spec-owner: unknown hook event: ${event:-missing}" >&2; exit 2 ;;
esac

path=$(jq -r '.tool_input.file_path // .file_path // empty' <<<"$input")
[ -n "$path" ] || jq -n '{permission:"allow"}'

allow() { jq -n '{permission:"allow"}'; exit 0; }
deny() {
  local message=$1
  if [ "$event" = "PreToolUse" ]; then
    jq -n --arg m "$message" \
      '{hookSpecificOutput:{hookEventName:"PreToolUse",permissionDecision:"deny",permissionDecisionReason:$m}}'
  else
    jq -n --arg m "$message" '{permission:"deny",user_message:$m,agent_message:$m}'
  fi
  exit 0
}

# Only a SPEC.md written directly into a task directory, at any depth from the tasks root. Both the
# path the tool was given and the file's real name are considered, because a symlinked home is common.
tasks_root="$HOME/.agent/tasks"
case "$path" in
  */SPEC.md) ;;
  *) allow ;;
esac
task_dir=$(dirname "$path")
case "$task_dir" in
  "$tasks_root"/*) ;;
  *) allow ;;
esac
# `<tasks>/<uuid>/SPEC.md` only: a nested path such as `<uuid>/review/…/SPEC.md` is not a task spec.
[ "$(dirname "$task_dir")" = "$tasks_root" ] || allow

metadata="$task_dir/.task-id"
[ -f "$metadata" ] || allow

owner=$(jq -r '.slug // empty' "$metadata" 2>/dev/null) || allow
[ -n "$owner" ] || allow

# The incoming content's H1 carries the spec title. Compare it to the recorded slug, normalized the
# same way the slug is built: lowercase, non-alphanumerics to hyphens.
content=$(jq -r '.tool_input.content // .tool_input.new_string // empty' <<<"$input")
[ -n "$content" ] || allow
title=$(printf '%s\n' "$content" | awk 'NR==1 && /^# /{sub(/^# +Spec: */,""); print; exit}')
[ -n "$title" ] || allow

claim=$(printf '%s' "$title" | tr '[:upper:]' '[:lower:]' \
  | sed -e 's/[^a-z0-9]\{1,\}/-/g' -e 's/^-//' -e 's/-$//' | cut -c1-50)

norm_owner=$(printf '%s' "$owner" | tr '[:upper:]' '[:lower:]' \
  | sed -e 's/[^a-z0-9]\{1,\}/-/g' -e 's/^-//' -e 's/-$//')

# A rewrite of the task's own spec keeps the same title, so the prefixes agree either way.
case "$norm_owner" in
  "$claim"*|"${claim:0:18}"*) allow ;;
esac

deny "Task spec guard: $task_dir belongs to '${norm_owner}', and the spec being written is titled '${claim}'. Writing it here overwrites a finished task's spec, and task directories are outside version control. Generate a new task directory (Step 1 of the specwriter protocol) instead of reusing this one."
