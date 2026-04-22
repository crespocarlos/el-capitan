#!/bin/bash
# Logs session_start to ~/.agent/telemetry/ for observability.
# Called by SessionStart hook.
set +e
exec 2>/dev/null

SESSION_UUID="${CLAUDE_SESSION_ID:-$(uuidgen 2>/dev/null || echo "unknown")}"
TIMESTAMP=$(date -u +%Y-%m-%dT%H:%M:%SZ)

mkdir -p ~/.agent/telemetry
echo "{\"ts\":\"$TIMESTAMP\",\"event\":\"session_start\",\"session\":\"$SESSION_UUID\",\"cwd\":\"$(pwd)\"}" \
  >> ~/.agent/telemetry/$(date +%Y-%m-%d).jsonl || true

exit 0
