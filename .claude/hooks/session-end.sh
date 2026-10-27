#!/usr/bin/env bash
set -euo pipefail
INPUT=$(cat)
if command -v jq >/dev/null 2>&1; then
  SESSION=$(printf '%s' "$INPUT" | jq -r '.session_id // .conversation_id // "unknown"')
  TARGET=$(printf '%s' "$INPUT" | jq -r '.tool_input.file_path // .tool_input.command // .command // "n/a"' | cut -c1-200)
  jq -n --arg session "$SESSION" --arg event "end" --arg target "$TARGET" '{session:$session,event:$event,target:$target}'
else
  INPUT="$INPUT" python3 -c 'import json,os; d=json.loads(os.environ["INPUT"]); print(json.dumps({"session":d.get("session_id",d.get("conversation_id","unknown")),"event":"end","target":str(d.get("command",d.get("tool_input",{}).get("file_path",d.get("tool_input",{}).get("command","n/a"))))[:200]}, ensure_ascii=False))'
fi
