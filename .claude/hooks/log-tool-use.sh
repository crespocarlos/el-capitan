#!/usr/bin/env bash
# The `post_tool` rule: minimal, local-only session telemetry. This never writes durable memory, and it never
# blocks a tool call: unreadable input is reported in one line.
set -euo pipefail
HOOK_NAME=log-tool-use
# shellcheck source=lib/hook.sh
. "$(dirname "$0")/lib/hook.sh"
hook_input

INPUT="$HOOK_INPUT" python3 - <<'PY'
import datetime
import hashlib
import json
import os
from pathlib import Path

event = json.loads(os.environ["INPUT"])
session_id = hashlib.sha256(str(event.get("session") or "unknown").encode()).hexdigest()[:24]
fields = event.get("input") or {}
command = str(fields.get("command") or "")
path = str(fields.get("file_path") or "")

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
    "event": str(event.get("native") or "post_tool"),
    "tool": str(event.get("tool") or "unknown"),
    "action": action,
    "failure": event.get("failure") is True,
    "target": Path(path).name if path else action,
}
root = Path(os.environ.get("CREW_MEMORY_DIR", Path.home() / ".agent" / "memory"))
directory = root / ".sessions"
directory.mkdir(mode=0o700, parents=True, exist_ok=True)
with (directory / f"{session_id}.jsonl").open("a", encoding="utf-8") as output:
    output.write(json.dumps(record, sort_keys=True) + "\n")
PY
