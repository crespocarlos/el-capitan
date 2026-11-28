#!/usr/bin/env bash
# The file guard: one process per Write, Edit, MultiEdit (Claude `PreToolUse`) or Write and Delete (Cursor
# `preToolUse`), with its rules in `lib/spec_guard.py`, decided on the path first so a write outside the tasks root
# never loads the Status reader.
#   spec-owner  (kept) a task SPEC.md titled for another task, written over a spec past DRAFTING. A task directory
#               records its slug in `.task-id`; overwriting a finished task's spec there destroyed it once.
#   task-files  (kept) Cursor's Delete of a task record.
#   status      (demoted) a write that moves the `## Status`. Claude Code holds it with the `ask` rule on task SPEC.md
#               files (settings.template.json), so it runs only for Cursor.
# A rule that fails (no verdict) is skipped with one stderr line.
set -euo pipefail
HOOK_NAME=check-task-spec-owner
# shellcheck source=lib/hook.sh
. "$(dirname "$0")/lib/hook.sh"
hook_stand_down check-task-spec-owner.sh fail-closed
hook_input
hook_event
demoted=()
if [ "$HOOK_SHAPE" = cursor ] || [[ $HOOK_INPUT == *'"cursor_version"'* ]]; then demoted=(--demoted); fi
verdict=$(printf '%s' "$HOOK_INPUT" | python3 -I "$HOOK_LIB/spec_guard.py" "$HOME/.agent/tasks" ${demoted[@]+"${demoted[@]}"} 2>/dev/null) \
  || hook_fail "lib/spec_guard.py gave no verdict; skipped"
case "$verdict" in
  "deny "*)
    verdict=${verdict#deny }
    HOOK_NAME=${verdict%% *} HOOK_SUBJECT=$(hook_field file_path)
    hook_deny "${verdict#* }" ;;
esac
hook_allow
