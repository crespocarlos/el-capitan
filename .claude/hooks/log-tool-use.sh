#!/usr/bin/env bash
# Capture minimal, local-only session telemetry. This never writes durable memory.
set -euo pipefail

INPUT=$(cat)
INPUT="$INPUT" python3 - <<'PY'
import datetime
import hashlib
import json
import os
from pathlib import Path

try:
    event = json.loads(os.environ["INPUT"])
except json.JSONDecodeError:
    print("{}")
    raise SystemExit

session = str(event.get("session_id") or event.get("conversation_id") or "unknown")
session_id = hashlib.sha256(session.encode()).hexdigest()[:24]
event_name = str(event.get("hook_event_name") or event.get("event") or "postToolUse")
tool_name = str(event.get("tool_name") or event.get("tool") or event.get("name") or "unknown")
tool_input = event.get("tool_input") or {}
command = str(tool_input.get("command") or event.get("command") or "")
path = str(tool_input.get("file_path") or event.get("file_path") or "")

if command.startswith("git commit"):
    action = "commit"
elif command.startswith("git push"):
    action = "push"
elif command.startswith("gh pr "):
    action = "pull-request"
elif path:
    action = "file-edit"
else:
    action = "tool"

record = {
    "ts": datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z"),
    "event": event_name,
    "tool": tool_name,
    "action": action,
    "failure": "failure" in event_name.lower(),
    "target": Path(path).name if path else action,
}
root = Path(os.environ.get("CREW_MEMORY_DIR", Path.home() / ".agent" / "memory"))
directory = root / ".sessions"
directory.mkdir(mode=0o700, parents=True, exist_ok=True)
with (directory / f"{session_id}.jsonl").open("a", encoding="utf-8") as output:
    output.write(json.dumps(record, sort_keys=True) + "\n")
print("{}")
PY
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
