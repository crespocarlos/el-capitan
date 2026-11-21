#!/bin/bash
# Sends a macOS desktop notification when Claude Code needs input.
# Called by Notification hook on idle_prompt.
set +e
exec 2>/dev/null
HOOK_NAME=notify-idle
# shellcheck source=lib/hook.sh
. "$(dirname "$0")/lib/hook.sh"
hook_input

REPO=$(basename "$(~/.agent/bin/crew-repo-info.py --field root 2>/dev/null || echo '')" 2>/dev/null || echo 'unknown')  # crew-lint: allow-swallow
BRANCH=$(~/.agent/bin/crew-repo-info.py --field branch 2>/dev/null || echo '')  # crew-lint: allow-swallow

if [[ "$(uname)" == "Darwin" ]]; then
  osascript \
    -e "display notification \"$REPO${BRANCH:+ ($BRANCH)} needs your input\" with title \"el-capitan\"" \
    -e 'tell application "iTerm2" to activate' \
    2>/dev/null || true
fi

exit 0
