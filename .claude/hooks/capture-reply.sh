#!/usr/bin/env bash
# Subagent stop, Claude Code `SubagentStop` and Cursor `subagentStop` (`crew-review-findings.py capture`): saves a
# dispatched agent's reply (a reviewer persona, the probe, a spec critic or explorer) when the dispatch prompt
# carries the `crew-review-out:` marker its `.expect` nonce confirms, records the run's usage on the task a `crew-task:`
# line names, and saves a `crew-builder` reply as that task's REPORT.md. Never blocks. Claude Code's fast path: a
# transcript whose first user line holds neither line ends here in shell; Cursor's payload goes to Python, which reads
# its `task` field and finds the transcript (`review_transcript.py`). Each outcome is one line, on stdout in Claude
# Code and in ~/.agent/state/capture-reply.log in both (Cursor's stdout gets `{}`). When the reply answers nothing,
# Python's `capture-continue:` line becomes, once per dispatch, Cursor's `followup_message` or Claude Code's
# `{"decision": "block", "reason": ...}` (then the only stdout). A crash is `failed (exit N)`; exit 0.
# Cursor's Claude-format copy never processes: it stands down for the registered counterpart, and without one (a
# stale ~/.cursor/hooks.json) it logs `re-run install.sh` and exits with no output.
set -uo pipefail
HOOK_NAME=capture-reply
# shellcheck source=lib/hook.sh
. "$(dirname "$0")/lib/hook.sh"
log="$HOME/.agent/state/capture-reply.log"
hook_stand_down capture-reply.sh
if hook_cursor_copy; then
  { mkdir -p "${log%/*}" && printf '%s SubagentStop capture-reply: Cursor runs the Claude-format copy and ~/.cursor/hooks.json registers no subagentStop capture-reply.sh; re-run install.sh\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" >>"$log"; } 2>/dev/null
  exit 0
fi
hook_input
native=0
[ "$HOOK_EVENT" = subagentStop ] && native=1
printed=""
cont=""
say() {
  [ "$native" = 1 ] || printed="$printed$1"$'\n'
  { mkdir -p "${log%/*}" && printf '%s %s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "${HOOK_EVENT:-?}" "$1" >>"$log"; } 2>/dev/null
}
finish() {
  if [ -n "$cont" ] && [ "$native" = 1 ]; then
    jq -cn --arg m "$cont" '{followup_message: $m}'
  elif [ -n "$cont" ]; then
    jq -cn --arg m "$cont" '{decision: "block", reason: $m}'
  elif [ "$native" = 1 ]; then
    printf '{}\n'
  else
    printf '%s' "$printed"
  fi
  exit 0
}
if [ "$native" = 0 ]; then
  path=$(printf '%s' "$HOOK_INPUT" | jq -r '.agent_transcript_path // ""' 2>/dev/null) || path=""
  prompt=$(grep -m1 -E '"(type|role)": *"user"' "$path" 2>/dev/null) || prompt=""
  if [ -z "$prompt" ] || ! printf '%s' "$prompt" | grep -q -e 'crew-review-out: ' -e 'crew-task: '; then
    say 'capture-reply: no marker; nothing saved'
    agent=$(printf '%s' "$HOOK_INPUT" | jq -r '.agent_type // ""' 2>/dev/null) || agent=""
    case "$agent" in crew-builder | *:crew-builder)
      say 'capture-reply: no report saved: the dispatch prompt has no `crew-task: <TASK_DIR>` line' ;;
    esac
    finish
  fi
fi
tool="$HOME/.agent/bin/crew-review-findings.py"
if [ ! -x "$tool" ]; then
  say "capture-reply: $tool missing; re-run install.sh"
  finish
fi
out=$(printf '%s' "$HOOK_INPUT" | python3 "$tool" capture 2>/dev/null)
rc=$?
while IFS= read -r line; do
  case "$line" in
    'capture-reply: '*) say "$line" ;;
    'capture-continue: '*) cont=${line#capture-continue: } ;;
  esac
done <<EOF
$out
EOF
[ "$rc" -eq 0 ] || say "capture-reply: failed (exit $rc)"
finish
