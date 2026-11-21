#!/usr/bin/env bash
# Refuse to write a SPEC.md whose slug disagrees with the task directory it lands in.
#
# A task directory records the spec it owns in `.task-id`, and the pipeline resolves "the current
# task" with `crew-resolve-task-dir.py`, which answers with the newest non-DONE task for the branch.
# On a repository where every task lives on one branch that is unrelated, already-finished work, and
# task directories sit outside the repository, so overwriting one destroys it with no recovery. That
# happened once; this is the structural fix.
#
# Narrow on purpose: only a write to a `SPEC.md` directly inside `~/.agent/tasks/<uuid>/` is checked,
# and only when that directory already has a `.task-id` naming a different slug. Creating a spec in a
# fresh directory has no `.task-id` yet, so it passes, and so does editing a spec in its own directory.
set -euo pipefail
HOOK_NAME=check-task-spec-owner
# shellcheck source=lib/hook.sh
. "$(dirname "$0")/lib/hook.sh"
hook_input
hook_event
path=$(hook_field file_path)
[ -n "$path" ] || hook_allow

tasks_root="$HOME/.agent/tasks"
case "$path" in */SPEC.md) ;; *) hook_allow ;; esac
task_dir=$(dirname "$path")
case "$task_dir" in "$tasks_root"/*) ;; *) hook_allow ;; esac
# `<tasks>/<uuid>/SPEC.md` only: a nested path such as `<uuid>/review/…/SPEC.md` is not a task spec.
[ "$(dirname "$task_dir")" = "$tasks_root" ] || hook_allow

metadata="$task_dir/.task-id"
[ -f "$metadata" ] || hook_allow
owner=$(jq -r '.slug // empty' "$metadata" 2>/dev/null) || hook_allow
[ -n "$owner" ] || hook_allow

# The spec's H1 carries its title, normalized as the slug is built (lowercase, non-alphanumerics to
# hyphens). A slug is capped at 50 characters, so the comparison below accepts the whole recorded slug
# and, for a title past the cap, the recorded slug being exactly the truncated title.
content=$(hook_field content)
[ -n "$content" ] || content=$(hook_field new_string)
[ -n "$content" ] || hook_allow
title=$(printf '%s\n' "$content" | awk 'NR==1 && /^# /{sub(/^# +Spec: */,""); print; exit}')
[ -n "$title" ] || hook_allow

normalize() { tr '[:upper:]' '[:lower:]' | sed -e 's/[^a-z0-9]\{1,\}/-/g' -e 's/^-//' -e 's/-$//'; }
claim=$(printf '%s' "$title" | normalize | cut -c1-50)
norm_owner=$(printf '%s' "$owner" | normalize)
# Agreement is on the whole normalized slug, and only in the direction the pipeline can produce it:
# the recorded slug was built from a title, so an edited title may *extend* it (`align-agent-tool-
# frontmatter` → `align-agent-tool-frontmatter-with-the-harness`), never shorten it. A shorter title
# that merely begins with the same words is a different task, which is why the 18-character prefix and
# the reverse-prefix case both let one through. The trailing-hyphen case covers a slug cut mid-word at
# the 50-character cap.
claim_matches() {
  [ "$claim" = "$norm_owner" ] && return 0
  case "$claim" in "$norm_owner"-*) return 0 ;; esac
  [ "${norm_owner%-}" = "$claim" ]
}
claim_matches && hook_allow

hook_deny "Task spec guard: $task_dir belongs to '$norm_owner', and the spec being written is titled '$claim'. Writing it here overwrites a finished task's spec, and task directories are outside version control. Generate a new task directory (Step 1 of the specwriter protocol) instead of reusing this one."
