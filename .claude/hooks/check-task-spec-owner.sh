#!/usr/bin/env bash
# The file guard: the `pre_write` rule (contract.json), one process per Write, Edit, MultiEdit or Delete, with its
# rules in `lib/spec_guard.py`, decided on the path first so a write outside the tasks root never loads the Status
# reader.
#   spec-owner  (kept) a task SPEC.md titled for another task, written over a spec past DRAFTING. A task directory
#               records its slug in `.task-id`; overwriting a finished task's spec there destroyed it once.
#   task-files  (kept) a Delete of a task record.
#   status      (demoted) a write that moves the `## Status`; it runs only where the harness holds no `ask` rule on
#               task SPEC.md files (`deny_rules` false in the event).
# A rule that fails (no verdict) is skipped with one stderr line.
set -euo pipefail
HOOK_NAME=check-task-spec-owner
# shellcheck source=lib/hook.sh
. "$(dirname "$0")/lib/hook.sh"
hook_input
verdict=$(printf '%s' "$HOOK_INPUT" | python3 -I "$HOOK_LIB/spec_guard.py" "$HOME/.agent/tasks" 2>/dev/null) \
  || hook_fail "lib/spec_guard.py gave no verdict; skipped"
case "$verdict" in
  "deny "*)
    verdict=${verdict#deny }
    HOOK_NAME=${verdict%% *} HOOK_SUBJECT=$(hook_field file_path)
    hook_deny "${verdict#* }" ;;
esac
hook_allow
