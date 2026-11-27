#!/usr/bin/env bash
# Stop hook: queue a memory-capture review for the turn that just ended; it drafts, never asks.
#
# The agent writes inbox drafts and asks nothing: the one approval question is the closing
# confirmation of `crew open pr`, and a subagent's question would never reach a human anyway.
# `crew-inbox.py pending` lists the queued review at the next session start and in `crew ls`.
#
# The guard file is written only after the queue entry exists, so an interrupted run retries rather
# than marking itself prompted for a review nobody saw.
set -euo pipefail
HOOK_NAME=memory-capture-prompt
. "$(dirname "$0")/lib/hook.sh"
hook_input
INPUT="$HOOK_INPUT" python3 - <<'PY'
import hashlib
import json
import os
from pathlib import Path

event = json.loads(os.environ["INPUT"])
session = str(event.get("session_id") or event.get("conversation_id") or "unknown")
session_id = hashlib.sha256(session.encode()).hexdigest()[:24]
root = Path(os.environ.get("CREW_MEMORY_DIR", Path.home() / ".agent" / "memory"))
events_path = root / ".sessions" / f"{session_id}.jsonl"
guard_path = root / ".sessions" / f"{session_id}.memory-prompted"
queue_path = root / ".sessions" / "review-queue.jsonl"


def finish(payload: dict) -> None:
    print(json.dumps(payload))
    raise SystemExit


if guard_path.exists() or not events_path.exists():
    finish({})
try:
    records = [json.loads(line) for line in events_path.read_text(encoding="utf-8").splitlines()]
except (OSError, json.JSONDecodeError):
    finish({})

failure_count = sum(record.get("failure") for record in records)
substantive_actions = {"file-edit", "commit", "push", "pull-request"}
substantive_count = sum(record.get("action") in substantive_actions for record in records)
if failure_count < 2 and substantive_count == 0:
    finish({})

# Queue first: the entry is what a human sees, so it must exist before the guard suppresses a retry.
entry = json.dumps({"session": session_id, "failures": failure_count,
                    "substantive": substantive_count}) + "\n"
try:
    queue_path.parent.mkdir(parents=True, exist_ok=True)
    with queue_path.open("a", encoding="utf-8") as handle:
        handle.write(entry)
except OSError:
    finish({})
guard_path.write_text("prompted\n", encoding="utf-8")

message = (
    "Memory capture check: this session had "
    + (f"{failure_count} repeated tool failure(s)" if failure_count >= 2
       else f"{substantive_count} substantive action(s)")
    + ". Review it for at most three durable, non-derivable lessons, then draft each as one `.md` "
      "file in `~/.agent/memory/.inbox/` with the usual frontmatter. Ask nothing about importing them: "
      "the closing confirmation of `crew open pr` and the next session start show the drafts. If "
      "nothing qualifies, write nothing."
)
finish({"followup_message": message})
PY
