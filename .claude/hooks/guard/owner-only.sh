#!/usr/bin/env bash
# Commands only the owner runs, in their own terminal: `crew-task.py restore-status <TASK_DIR> --accept <note>`, which
# records a Status written outside the gates as the task's recorded status. From an agent it would launder a skipped
# approval through the command meant to catch it, so every agent shell call to it is refused. `restore-status`
# without `--accept`, and `mark-done --force`, keep the harness's own prompt. `crew-task.py` is found the way the
# normaliser finds any command (behind `python3`, a wrapper, `sh -c` or `$(...)`), by its file name.
set -euo pipefail
HOOK_NAME=owner-only
# shellcheck source=lib/hook.sh
. "$(dirname "$0")/../lib/hook.sh"
hook_stand_down guard/owner-only.sh fail-closed
hook_input
hook_event
cmd=$(hook_field command)
# Any `--acc*` word: crew-task.py's parser refuses abbreviations too, but the guard does not rely on it.
case "$cmd" in *--acc*) ;; *) hook_allow ;; esac
hook_segments "$cmd"
i=0
while [ "$i" -lt "${#HOOK_SEGS[@]}" ]; do
  hook_seg "$i"
  i=$((i + 1))
  tool=0 sub="" accept=0
  for word in "${SEG_WORDS[@]}"; do
    if [ "$tool" = 0 ]; then
      [ "${word##*/}" != crew-task.py ] || tool=1
      continue
    fi
    case "$word" in
      --acc*) accept=1 ;;
      -*) ;;
      *) [ -n "$sub" ] || sub=$word ;;
    esac
  done
  if [ "$tool" = 1 ] && [ "$sub" = restore-status ] && [ "$accept" = 1 ]; then
    hook_deny "Owner only: crew-task.py restore-status --accept records a Status written outside the gates as the task's own; the owner runs it in their own terminal. Run restore-status without --accept to write the recorded status back."
  fi
done
hook_allow
