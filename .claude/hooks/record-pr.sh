#!/usr/bin/env bash
# Records the PR a successful `gh pr create` printed on the task it belongs to (`crew-task.py record-pr`):
# mark-done for its IMPLEMENTING task, the PR line for a DONE one. Never blocks: every path exits 0. Only a command
# with a real `gh ... pr create` segment (lib/hook.sh's normaliser, never text in an echo or a string) whose output
# holds a PR URL reaches Python. Claude gets the outcome as additional context.
set -uo pipefail
HOOK_NAME=record-pr
# shellcheck source=lib/hook.sh
. "$(dirname "$0")/lib/hook.sh"
hook_stand_down record-pr.sh
hook_input
case "$HOOK_INPUT" in *'pr create'*) ;; *) exit 0 ;; esac
case "$HOOK_INPUT" in *'github.com/'*'/pull/'*) ;; *) exit 0 ;; esac
command=$(printf '%s' "$HOOK_INPUT" | jq -r '.tool_input.command // .command // ""' 2>/dev/null) || exit 0
# In a subshell, so the normaliser state stays there.
created=$(
  if [ -z "$HOOK_CWD" ] || [ ! -d "$HOOK_CWD" ]; then HOOK_CWD=$PWD; fi
  hook_segments "$command"
  i=0
  while [ "$i" -lt "${#HOOK_SEGS[@]}" ]; do
    hook_seg "$i"
    # gh must be the segment's command: `echo gh pr create` names gh as text.
    if [ "${SEG_WORDS[0]:-}" != "" ] && [ "${SEG_WORDS[0]##*/}" = gh ] && hook_gh \
      && [ "$GH_CMD" = pr ] && [ "$GH_SUB" = create ]; then echo create; exit 0; fi
    i=$((i + 1))
  done
) 2>/dev/null
[ "$created" = create ] || exit 0
tool="$HOME/.agent/bin/crew-task.py"
if [ ! -x "$tool" ]; then
  printf 'record-pr: %s missing; re-run install.sh\n' "$tool" >&2
  exit 0
fi
out=$(printf '%s' "$HOOK_INPUT" | "$tool" record-pr 2>&1) || true
[ -n "$out" ] || exit 0
if [ "$HOOK_EVENT" = PostToolUse ]; then
  jq -n --arg text "$out" '{hookSpecificOutput: {hookEventName: "PostToolUse", additionalContext: $text}}'
else
  printf '%s\n' "$out"
fi
exit 0
