#!/bin/bash
# Logs tool calls to ~/.agent/telemetry/ as JSONL for observability.
# Called by PostToolUse hook — receives JSON on stdin.
# Must exit 0 on any error (never block the agent).

TELEMETRY_DIR="$HOME/.agent/telemetry"
mkdir -p "$TELEMETRY_DIR" 2>/dev/null || exit 0

LOG_FILE="$TELEMETRY_DIR/$(date +%Y-%m-%d).jsonl"
INPUT=$(cat 2>/dev/null) || exit 0

TOOL=$(echo "$INPUT" | jq -r '.tool_name // "unknown"' 2>/dev/null) || TOOL="unknown"
FILE_PATH=$(echo "$INPUT" | jq -r '.tool_input.file_path // .tool_input.command // "n/a"' 2>/dev/null) || FILE_PATH="n/a"
TIMESTAMP=$(date -u +%Y-%m-%dT%H:%M:%SZ)

echo "{\"ts\":\"$TIMESTAMP\",\"tool\":\"$TOOL\",\"target\":\"$FILE_PATH\"}" >> "$LOG_FILE" 2>/dev/null

exit 0
