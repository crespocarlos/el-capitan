#!/usr/bin/env bash
# SessionStart context: inject bounded memory context. Fails open — a memory problem never blocks a
# session, and an unreadable hook input is reported in one line rather than ending the session.
set -euo pipefail
HOOK_NAME=memory-context
# shellcheck source=lib/hook.sh
. "$(dirname "$0")/lib/hook.sh"
hook_stand_down cursor-memory-context.sh
hook_input

rc=0
out=$(~/.agent/bin/crew-mem.py context --mode session 2>&1) || rc=$?
case $rc in
  0) printf '%s\n' "$out" ;;
  2) hook_fail "warning: memory unavailable" ;;
  *) hook_fail "crew-mem.py exit $rc — $out" ;;
esac
