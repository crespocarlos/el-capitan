#!/usr/bin/env bash
set -euo pipefail
out=$(~/.agent/bin/mem.py context --mode session 2>&1) || rc=$?
case ${rc:-0} in
  0) printf '%s\n' "$out" ;;
  2) printf 'warning: memory unavailable\n' >&2 ;;
  *) printf 'error: mem.py exit %s — %s\n' "${rc:-1}" "$out" >&2 ;;
esac
