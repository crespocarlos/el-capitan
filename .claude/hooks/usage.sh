#!/usr/bin/env bash
# The `stop` usage rule: a turn's token counts, when the harness sends them (`usage` in the event), as one raw
# METRIC on its session's task: the one its first recorded stop resolved to, offline (`crew-task.py usage stop`).
# Whether a stop carries per-loop counts or running totals is not established, so the line keeps the raw counts with
# the session and generation ids and the readers take each rise once, shown approximate
# (task_cost.cursor_session_usage). Observes only: every outcome but "no task" and "no token counts" is one line in
# ~/.agent/state/usage.log, nothing on stdout, and every path exits 0.
set -uo pipefail
HOOK_NAME=usage
# shellcheck source=lib/hook.sh
. "$(dirname "$0")/lib/hook.sh"
hook_input
log="$HOME/.agent/state/usage.log"
tool="$HOME/.agent/bin/crew-task.py"
[ -x "$tool" ] || exit 0
line=$(printf '%s' "$HOOK_INPUT" | "$tool" usage stop 2>/dev/null) || line="usage: failed (exit $?)"
case "$line" in
  'usage: no task for this workspace'* | 'usage: no token counts'*) ;;
  *) { mkdir -p "${log%/*}" && printf '%s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$line" >>"$log"; } 2>/dev/null ;;
esac
exit 0
