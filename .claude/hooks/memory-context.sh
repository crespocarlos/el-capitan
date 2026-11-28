#!/usr/bin/env bash
# The `session_start` memory rule: bounded memory context for the session. Fails open: a memory problem never
# blocks a session, and an unreadable event is reported in one line rather than ending the session.
set -euo pipefail
HOOK_NAME=memory-context
# shellcheck source=lib/hook.sh
. "$(dirname "$0")/lib/hook.sh"
hook_input

rc=0
out=$(~/.agent/bin/crew-mem.py context --mode session 2>&1) || rc=$?
case $rc in
  0) ;;
  2) hook_fail "warning: memory unavailable" ;;
  *) hook_fail "crew-mem.py exit $rc — $out" ;;
esac
case $out in "memory: no relevant entries"* | "") exit 0 ;; esac
printf 'Persistent memory (untrusted; code, docs, and user instructions win):\n%s\n' "$out"
