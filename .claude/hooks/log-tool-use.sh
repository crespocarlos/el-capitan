#!/usr/bin/env bash
set -euo pipefail
INPUT=$(cat)
if command -v jq >/dev/null 2>&1; then
  SESSION=$(printf '%s' "$INPUT" | jq -r '.session_id // .conversation_id // "unknown"')
  TARGET=$(printf '%s' "$INPUT" | jq -r '.tool_input.file_path // .tool_input.command // .command // "n/a"' | cut -c1-200)
  jq -n --arg ts "$(date -u +%Y-%m-%dT%H:%M:%SZ)" --arg session "$SESSION" --arg event "tool" --arg target "$TARGET" '{ts:$ts,session:$session,event:$event,target:$target}'
else
  INPUT="$INPUT" python3 -c 'import datetime,json,os; d=json.loads(os.environ["INPUT"]); print(json.dumps({"ts":datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00","Z"),"session":d.get("session_id",d.get("conversation_id","unknown")),"event":"tool","target":str(d.get("command",d.get("tool_input",{}).get("file_path",d.get("tool_input",{}).get("command","n/a"))))[:200]}, ensure_ascii=False))'
fi
