#!/usr/bin/env bash
# Session lifecycle telemetry: one JSON line per event.
#
# Usage: session-event.sh <start|end|session>
#
# Three scripts (`session-start.sh`, `session-end.sh`, `session-logger.sh`) differed only in that
# word — 24 of their 30 non-blank lines were identical. This is the one implementation, registered
# three times with a different argument. Telemetry only: it never blocks a session, and the hook
# registrations append `; exit 0` for the same reason.
set -euo pipefail

kind="${1:-session}"
INPUT=$(cat)
if command -v jq >/dev/null 2>&1; then
  SESSION=$(printf '%s' "$INPUT" | jq -r '.session_id // .conversation_id // "unknown"')
  TARGET=$(printf '%s' "$INPUT" | jq -r '.tool_input.file_path // .tool_input.command // .command // "n/a"' | cut -c1-200)
  jq -n --arg session "$SESSION" --arg event "$kind" --arg target "$TARGET" \
    '{session:$session,event:$event,target:$target}'
else
  INPUT="$INPUT" KIND="$kind" python3 -c 'import json,os; d=json.loads(os.environ["INPUT"]); print(json.dumps({"session":d.get("session_id",d.get("conversation_id","unknown")),"event":os.environ["KIND"],"target":str(d.get("command",d.get("tool_input",{}).get("file_path",d.get("tool_input",{}).get("command","n/a"))))[:200]}, ensure_ascii=False))'
fi
