#!/bin/bash
# Shows a macOS banner when Claude Code waits for input (Notification hook, matcher idle_prompt).
# Quiet by design: it never activates or focuses an application, does nothing in a background job
# (CLAUDE_JOB_DIR set) or with EL_CAPITAN_NOTIFY=off, and shows at most one banner per session every
# 10 minutes; the time of the last one is kept in ~/.agent/memory/.sessions/<session>.notified.
# Without osascript (any system but macOS) it exits silently. It always exits 0.
set +e
exec 2>/dev/null
INTERVAL=600
[ "${EL_CAPITAN_NOTIFY:-}" = off ] && exit 0
[ -n "${CLAUDE_JOB_DIR:-}" ] && exit 0
command -v osascript >/dev/null || exit 0
HOOK_NAME=notify-idle
# shellcheck source=lib/hook.sh
. "$(dirname "$0")/lib/hook.sh"
hook_input

SESSION=$(printf '%s' "$HOOK_INPUT" | jq -r '.session_id // .conversation_id // "unknown"')
KEY=$(printf '%s' "${SESSION:-unknown}" | { shasum -a 256 || sha256sum; } | cut -c1-24)
[ -n "$KEY" ] || KEY=$(printf '%s' "${SESSION:-unknown}" | tr -c 'A-Za-z0-9_-' _ | cut -c1-64)
DIR=${CREW_MEMORY_DIR:-$HOME/.agent/memory}/.sessions
STAMP=$DIR/$KEY.notified
NOW=$(date +%s)
LAST=$(cat "$STAMP")
case "$LAST" in '' | *[!0-9]*) LAST=0 ;; esac
[ $((NOW - LAST)) -lt "$INTERVAL" ] && exit 0
mkdir -p -m 700 "$DIR" && printf '%s\n' "$NOW" > "$STAMP"

REPO=$(basename "$(~/.agent/bin/crew-repo-info.py --field root 2>/dev/null || echo '')" 2>/dev/null || echo 'unknown')  # crew-lint: allow-swallow
BRANCH=$(~/.agent/bin/crew-repo-info.py --field branch 2>/dev/null || echo '')  # crew-lint: allow-swallow
MESSAGE="${REPO:-unknown}${BRANCH:+ ($BRANCH)} needs your input"
MESSAGE=${MESSAGE//[\"\\]/}
osascript -e "display notification \"$MESSAGE\" with title \"el-capitan\"" || true

exit 0
