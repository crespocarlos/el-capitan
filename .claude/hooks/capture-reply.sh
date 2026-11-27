#!/usr/bin/env bash
# Claude Code `SubagentStop` (`crew-review-findings.py capture`): saves a reviewer persona's reply when the dispatch
# prompt carries the `crew-review-out:` marker its `.expect` nonce confirms, and records the run's token usage on the
# task a `crew-task:` line names. Never blocks: a transcript whose first user line (the dispatch prompt) holds neither
# line ends here in shell, each outcome is one line on stdout, a crash is `failed (exit N)`, and every path exits 0.
set -uo pipefail
HOOK_NAME=capture-reply
# shellcheck source=lib/hook.sh
. "$(dirname "$0")/lib/hook.sh"
hook_input
path=$(printf '%s' "$HOOK_INPUT" | jq -r '.agent_transcript_path // ""' 2>/dev/null) || path=""
prompt=$(grep -m1 -E '"type": *"user"' "$path" 2>/dev/null) || prompt=""
if [ -z "$prompt" ] || ! printf '%s' "$prompt" | grep -q -e 'crew-review-out: ' -e 'crew-task: '; then
  printf 'capture-reply: no marker; nothing saved\n'
  exit 0
fi
tool="$HOME/.agent/bin/crew-review-findings.py"
if [ ! -x "$tool" ]; then
  printf 'capture-reply: %s missing; re-run install.sh\n' "$tool"
  exit 0
fi
out=$(printf '%s' "$HOOK_INPUT" | python3 "$tool" capture 2>/dev/null)
rc=$?
printf '%s\n' "$out" | grep '^capture-reply: '
[ "$rc" -eq 0 ] || printf 'capture-reply: failed (exit %s)\n' "$rc"
exit 0
