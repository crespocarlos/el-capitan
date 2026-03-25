#!/bin/bash
# Logs tool calls to ~/.agent/telemetry/ as JSONL for observability.
# Called by PostToolUse hook — receives JSON on stdin.
# Must exit 0 and produce no stderr (Claude Code treats stderr as hook error).

exec 2>/dev/null

TELEMETRY_DIR="$HOME/.agent/telemetry"
mkdir -p "$TELEMETRY_DIR" || exit 0

LOG_FILE="$TELEMETRY_DIR/$(date +%Y-%m-%d).jsonl"
INPUT=$(cat) || exit 0

TOOL=$(echo "$INPUT" | jq -r '.tool_name // "unknown"') || TOOL="unknown"
FILE_PATH=$(echo "$INPUT" | jq -r '.tool_input.file_path // .tool_input.command // "n/a"') || FILE_PATH="n/a"
TIMESTAMP=$(date -u +%Y-%m-%dT%H:%M:%SZ)

echo "{\"ts\":\"$TIMESTAMP\",\"tool\":\"$TOOL\",\"target\":\"$FILE_PATH\"}" >> "$LOG_FILE"

exit 0
