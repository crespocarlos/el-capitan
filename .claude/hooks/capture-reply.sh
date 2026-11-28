#!/usr/bin/env bash
# The `subagent_stop` rule (`crew-review-findings.py capture`): saves a dispatched agent's reply (a reviewer persona,
# the probe, a spec critic or explorer) when the dispatch prompt carries the `crew-review-out:` marker its `.expect`
# nonce confirms, records the run's usage on the task a `crew-task:` line names, and saves a `crew-builder` reply as
# that task's REPORT.md. Never blocks. Each outcome is one line, on stdout and in ~/.agent/state/capture-reply.log. When the reply answers nothing, Python's `capture-continue:` line becomes, once per
# dispatch, `{"followup": ...}` (then the only stdout). A crash is `failed (exit N)`; exit 0.
set -uo pipefail
HOOK_NAME=capture-reply
# shellcheck source=lib/hook.sh
. "$(dirname "$0")/lib/hook.sh"
log="$HOME/.agent/state/capture-reply.log"
hook_input
printed=""
cont=""
say() {
  printed="$printed$1"$'\n'
  { mkdir -p "${log%/*}" && printf '%s %s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "${HOOK_HARNESS:-?}" "$1" >>"$log"; } 2>/dev/null
}
finish() {
  if [ -n "$cont" ]; then jq -cn --arg m "$cont" '{followup: $m}'; else printf '%s' "$printed"; fi
  exit 0
}
tool="$HOME/.agent/bin/crew-review-findings.py"
if [ ! -x "$tool" ]; then
  say "capture-reply: $tool missing; re-run install.sh"
  finish
fi
out=$(printf '%s' "$HOOK_INPUT" | "$tool" capture 2>/dev/null)
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
