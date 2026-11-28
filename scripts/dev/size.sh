#!/usr/bin/env bash
# The program's size numbers for this working tree, each against the baseline commit measured the same way:
# code and tests in lines, prompts and the five always-on rules in bytes. Usage: bash scripts/dev/size.sh
set -euo pipefail
cd "$(dirname "$0")/../.."
BASE=6e81879
CODE='^(\.agent/tools/.*\.py|\.claude/hooks/.*|\.claude/[^/]*\.py|install\.sh|tui/[^/]*\.py)$'
TESTS='^evals/.*\.py$'
PROMPTS='^(\.cursor/agents/|\.cursor/skills/|rules/)'
ALWAYS='^rules/(personal|agent-output|crew-router|crew-orchestrator|memory-capture)\.mdc$'
now() { git ls-files | grep -E "$1" | while read -r f; do [ -f "$f" ] && cat "$f"; done | wc "$2" | tr -d ' '; }
base() { git ls-tree -r --name-only "$BASE" | grep -E "$1" | while read -r f; do git show "$BASE:$f"; done | wc "$2" | tr -d ' '; }
for row in "code $CODE -l" "tests $TESTS -l" "prompts $PROMPTS -c" "always-on $ALWAYS -c"; do
  read -r name pattern unit <<< "$row"
  current=$(now "$pattern" "$unit") baseline=$(base "$pattern" "$unit")
  printf '%-9s %8d  %+6d (%+.1f%%) vs %s\n' "$name" "$current" "$((current - baseline))" \
    "$(awk "BEGIN { print ($current - $baseline) * 100 / $baseline }")" "$BASE"
done
