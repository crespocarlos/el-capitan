#!/usr/bin/env bash
# Session lifecycle telemetry: one JSON line per event.
#
# Usage: session-event.sh <start|end|session>
#
# Three scripts (`session-start.sh`, `session-end.sh`, `session-logger.sh`) differed only in that
# word — 24 of their 30 non-blank lines were identical. This is the one implementation, registered
# three times with a different argument. Telemetry only: it never blocks a session, so it shares the
# preamble's fail-open path and prints nothing when the input is unreadable.
set -euo pipefail
HOOK_NAME=session-event
# shellcheck source=lib/hook.sh
. "$(dirname "$0")/lib/hook.sh"

kind="${1:-session}"
hook_input
session=$(printf '%s' "$HOOK_INPUT" | jq -r '.session_id // .conversation_id // "unknown"' 2>/dev/null) \
  || hook_fail "cannot read the session id"
target=$(hook_field target)
[ -n "$target" ] || target=$(hook_field command)
[ -n "$target" ] || target=$(hook_field file_path)
[ -n "$target" ] || target="n/a"
jq -n --arg session "$session" --arg event "$kind" --arg target "${target:0:200}" \
  '{session:$session,event:$event,target:$target}'
