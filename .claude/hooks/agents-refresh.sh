#!/usr/bin/env bash
# The `session_start` refresh rule: re-render each installed agent file (the read-only agents with the MCP servers)
# that no longer matches its source in the installed checkout and the mcp config (`harness_install refresh`), so a
# `git pull`, a persona edit or a config change reaches this session without a re-install. Never blocks: every path
# exits 0; one line when it rewrote files or failed.
set -uo pipefail
py="$HOME/.agent/venv/bin/python"
[ -x "$py" ] && [ -f "$HOME/.agent/install-manifest.json" ] || exit 0
err=$(mktemp) || exit 0
out=$("$py" -m crew.harness.harness_install refresh "$HOME" 2>"$err") || \
  printf 'agents-refresh: %s\n' "$(head -n 1 "$err")" >&2
rm -f "$err"
[ -n "$out" ] && printf '%s\n' "$out"
exit 0
