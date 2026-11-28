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
# only when that directory already has a `.task-id` naming a different slug, and only when a SPEC.md
# is already there to destroy. The last condition is what keeps the rule honest: the specwriter
# protocol writes `.task-id` in Step 1 and the SPEC.md in Step 3, so a first write always reaches this
# hook with metadata present. Denying on the slug alone refused the ordinary case — a fresh directory
# whose title differed by one word from the slug its creator derived — while no file existed to lose.
#
# It also guards the approval gate. Install allows every Edit under `~/.agent/tasks` without a prompt,
# so `lib/spec_guard.py` refuses an Edit, MultiEdit or Write that changes the `## Status` value of an
# existing task SPEC.md (read with the one reader, `task_status`), creates one with a Status other
# than DRAFTING, leaves a second Status heading, carries another tool's fields, or cannot be applied
# exactly; and any write to `.task-id` or a review's `*.expect`, `*.provenance.json` and `*.out.md`.
# It decides on the path first and fails closed: no verdict is a denial. A Bash command never reaches
# this hook: `guard/task-files.sh` refuses its literal writes, and crew-task's Status integrity check
# (TAMPERED) catches the rest.
set -euo pipefail
HOOK_NAME=check-task-spec-owner
# shellcheck source=lib/hook.sh
. "$(dirname "$0")/lib/hook.sh"
hook_stand_down check-task-spec-owner.sh fail-closed
hook_input
hook_event
verdict=$(printf '%s' "$HOOK_INPUT" | python3 -I "$HOOK_LIB/spec_guard.py" "$HOME/.agent/tasks" 2>/dev/null) || verdict=""
case "$verdict" in
  skip) hook_allow ;;
  "ok "*) path=${verdict#ok } ;;
  "deny "*) hook_deny "${verdict#deny }" ;;
  *) hook_deny "Task spec guard: cannot check this write (lib/spec_guard.py gave no verdict), so it is refused." ;;
esac
task_dir=$(dirname "$path")

# Nothing to protect: a directory with no SPEC.md cannot lose one, and this is where every new task
# starts. Refusing here turned the ordinary first write into a denial whenever the spec's title and the
# slug its creator derived disagreed by a word.
[ -f "$task_dir/SPEC.md" ] || hook_allow

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
