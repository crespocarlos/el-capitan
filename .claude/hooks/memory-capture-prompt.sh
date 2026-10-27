#!/usr/bin/env bash
# Ask the agent for one user-approved memory proposal after a substantive session.
set -euo pipefail

INPUT=$(cat)
INPUT="$INPUT" python3 - <<'PY'
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
root = Path(os.environ.get("CREW_MEMORY_DIR", Path.home() / ".agent" / "memory"))
events_path = root / ".sessions" / f"{session_id}.jsonl"
guard_path = root / ".sessions" / f"{session_id}.memory-prompted"
if guard_path.exists() or not events_path.exists():
    print("{}")
    raise SystemExit

try:
    records = [json.loads(line) for line in events_path.read_text(encoding="utf-8").splitlines()]
except (OSError, json.JSONDecodeError):
    print("{}")
    raise SystemExit

failure_count = sum(record.get("failure") for record in records)
substantive_actions = {"file-edit", "commit", "push", "pull-request"}
substantive_count = sum(record.get("action") in substantive_actions for record in records)
if failure_count < 2 and substantive_count == 0:
    print("{}")
    raise SystemExit

guard_path.write_text("prompted\n", encoding="utf-8")
reason = (
    f"{failure_count} repeated tool failure(s)"
    if failure_count >= 2
    else f"{substantive_count} substantive action(s)"
)
message = (
    "Memory capture check: this session had "
    + reason
    + ". Review the session for at most three durable, non-derivable lessons, "
      "user preferences, or process gaps. Do not write memory yet. Present only "
      "the candidates with evidence and ask the user whether to store them; if "
      "there are none, say `nothing to persist`."
)
print(json.dumps({"followup_message": message}))
PY
