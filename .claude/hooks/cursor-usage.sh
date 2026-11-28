#!/usr/bin/env bash
# Cursor `stop` hook: record the session's token counts (`input_tokens`, `output_tokens`, `cache_read_tokens`,
# `cache_write_tokens`) as one raw `cursor_stop` METRIC on its conversation's task: the one its first recorded stop
# resolved to, offline (`crew-task.py usage stop`). Whether a `stop` carries per-loop counts or running totals is not
# established, so the line keeps the raw counts with `conversation_id` and `generation_id` and the readers take each
# rise once, shown approximate (task_cost.cursor_session_usage). Observes only: every outcome but "no task" is one
# line in ~/.agent/state/cursor-usage.log, stdout is always `{}`, and every path exits 0.
set -uo pipefail
HOOK_NAME=cursor-usage
# shellcheck source=lib/hook.sh
. "$(dirname "$0")/lib/hook.sh"
hook_input
log="$HOME/.agent/state/cursor-usage.log"
tool="$HOME/.agent/bin/crew-task.py"
if [ "$HOOK_EVENT" = stop ] && [ -x "$tool" ]; then
  line=$(printf '%s' "$HOOK_INPUT" | "$tool" usage stop 2>/dev/null) || line="usage: failed (exit $?)"
  case "$line" in
    'usage: no task for this workspace'*) ;;
    *) { mkdir -p "${log%/*}" && printf '%s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$line" >>"$log"; } 2>/dev/null ;;
  esac
fi
printf '{}\n'
exit 0
