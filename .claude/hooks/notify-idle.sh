#!/bin/bash
# Sends a macOS desktop notification when Claude Code needs input.
# Called by Notification hook on idle_prompt.
set +e
exec 2>/dev/null

REPO=$(basename "$(git rev-parse --show-toplevel 2>/dev/null)" 2>/dev/null || echo 'unknown')
BRANCH=$(git branch --show-current 2>/dev/null || echo '')

if [[ "$(uname)" == "Darwin" ]]; then
  osascript \
    -e "display notification \"$REPO${BRANCH:+ ($BRANCH)} needs your input\" with title \"el-capitan\"" \
    -e 'tell application "iTerm2" to activate' \
    2>/dev/null || true
fi

exit 0
