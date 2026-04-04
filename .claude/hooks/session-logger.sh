#!/bin/bash
set +e
exec 2>/dev/null

INPUT=$(cat)
[ -z "$INPUT" ] && exit 0

# Extract fields — PostToolUse has tool_name and tool_input; Stop does not
if command -v jq >/dev/null 2>&1; then
  TOOL_NAME=$(echo "$INPUT" | jq -r '.tool_name // empty')
  TARGET=$(echo "$INPUT" | jq -r '.tool_input.file_path // .tool_input.command // empty')
else
  TOOL_NAME=$(echo "$INPUT" | grep -o '"tool_name":"[^"]*"' | head -1 | sed 's/"tool_name":"//;s/"//')
  TARGET=$(echo "$INPUT" | grep -o '"file_path":"[^"]*"' | head -1 | sed 's/"file_path":"//;s/"//')
fi

SESSION_UUID="${CLAUDE_SESSION_ID:-$(uuidgen 2>/dev/null || echo "unknown")}"
TIMESTAMP=$(date -u +%Y-%m-%dT%H:%M:%SZ)
EXIT_CODE="${CLAUDE_TOOL_EXIT_CODE:-0}"

mkdir -p ~/.agent/sessions
LOGFILE=~/.agent/sessions/$(date +%Y-%m-%d).jsonl
echo "{\"session_uuid\":\"$SESSION_UUID\",\"timestamp\":\"$TIMESTAMP\",\"tool_name\":\"${TOOL_NAME:-null}\",\"target\":\"${TARGET:-null}\",\"exit_code\":$EXIT_CODE}" >> "$LOGFILE" || true

exit 0
