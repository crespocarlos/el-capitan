#!/usr/bin/env bash
# SessionStart: re-render each read-only agent copy in ~/.cursor/agents that no longer matches its source and the
# mcp config (`install_blocks.py refresh-agents`), so a `git pull`, a persona edit or a config change reaches this
# session without a re-install. Never blocks: every path exits 0; one line when it rewrote copies or failed.
set -uo pipefail
script=$0
# install links this file into ~/.claude/hooks with an absolute target; the checkout holds install_blocks.py.
if [ -L "$script" ]; then script=$(readlink "$script"); fi
checkout=$(cd "$(dirname "$script")/../.." 2>/dev/null && pwd) || exit 0
blocks="$checkout/.claude/install_blocks.py"
[ -f "$blocks" ] && [ -f "$HOME/.agent/install-manifest.json" ] || exit 0
err=$(mktemp) || exit 0
out=$(python3 "$blocks" refresh-agents "$HOME" "$checkout" 2>"$err") || \
  printf 'agents-refresh: %s\n' "$(head -n 1 "$err")" >&2
rm -f "$err"
[ -n "$out" ] && printf '%s\n' "$out"
exit 0
