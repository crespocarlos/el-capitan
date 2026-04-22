#!/bin/bash
# Logs tool calls to ~/.agent/telemetry/ as JSONL for observability.
# Called by PostToolUse hook — receives JSON on stdin.
# Uses jq for parsing; falls back gracefully if unavailable.

exec 2>/dev/null

TELEMETRY_DIR="$HOME/.agent/telemetry"
mkdir -p "$TELEMETRY_DIR" || exit 0

LOG_FILE="$TELEMETRY_DIR/$(date +%Y-%m-%d).jsonl"
# NOTE: session-start.sh / session-end.sh also write to this directory.
INPUT=$(cat) || exit 0

if command -v jq >/dev/null 2>&1; then
  TOOL=$(echo "$INPUT" | jq -r '.tool_name // "unknown"')
  FILE_PATH=$(echo "$INPUT" | jq -r '.tool_input.file_path // .tool_input.command // "n/a"' | head -c 200)
  SESSION_ID=$(echo "$INPUT" | jq -r '.session_id // "unknown"')
else
  TOOL="unknown"
  FILE_PATH="n/a"
  SESSION_ID="unknown"
fi

TIMESTAMP=$(date -u +%Y-%m-%dT%H:%M:%SZ)

echo "{\"ts\":\"$TIMESTAMP\",\"tool\":\"$TOOL\",\"target\":\"$FILE_PATH\",\"session\":\"$SESSION_ID\"}" >> "$LOG_FILE"

exit 0
