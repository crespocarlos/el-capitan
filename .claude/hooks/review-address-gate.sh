#!/usr/bin/env bash
# Deny edits under `crew review address` until the user's own prompt approved a fix set.
#
# The skill requires a verdict table and an explicit `all`/`none`/cherry-pick answer before any
# edit lands. Prose could not hold that gate: `personal.mdc` ranks the current user instruction
# above the pipeline rules, so a bare "crew review address" was readable as authorization to skip
# straight to edits. This makes the gate structural.
#
# Two markers, deliberately unequal:
#   pending   — written by the orchestrator when it presents the verdict table. Model-written,
#               so it can only *narrow* the gate: it asserts "a table was shown", nothing more.
#   approved  — written only by review-address-approval.sh, a UserPromptSubmit hook fed by the
#               user's own message. The model cannot produce a user turn, so it cannot forge this.
#
# No pending marker means an ordinary edit, and the hook stays out of the way.
set -euo pipefail

if ! command -v jq >/dev/null 2>&1; then
  echo "review-address-gate: jq is required; denying so the gate cannot be bypassed." >&2
  exit 2
fi

input=$(cat)
if ! jq -e . >/dev/null 2>&1 <<<"$input"; then
  echo "review-address-gate: hook input is not valid JSON; denying." >&2
  exit 2
fi

event=$(jq -r '.hook_event_name // empty' <<<"$input")
case "$event" in
  PreToolUse|preToolUse) ;;
  *) echo "review-address-gate: unknown hook event: ${event:-missing}" >&2; exit 2 ;;
esac

cwd=$(jq -r '.cwd // empty' <<<"$input")
[ -d "$cwd" ] || cwd=$PWD

allow() { jq -n '{permission:"allow"}'; exit 0; }
deny() {
  local message=$1
  if [ "$event" = "PreToolUse" ]; then
    jq -n --arg m "$message" \
      '{hookSpecificOutput:{hookEventName:"PreToolUse",permissionDecision:"deny",permissionDecisionReason:$m}}'
  else
    jq -n --arg m "$message" '{permission:"deny",user_message:$m,agent_message:$m}'
  fi
  exit 0
}

state="$HOME/.agent/review-address"
pending="$state/pending"
approved="$state/approved"

[ -f "$pending" ] || allow

# Approval must postdate the table it answers, so a stale "all" from an earlier run cannot
# authorize this one. `test -nt` is POSIX and needs no date parsing.
if [ -f "$approved" ] && [ "$approved" -nt "$pending" ]; then
  allow
fi

deny "Review-address gate: no approval recorded for the findings just presented. Show the verdict table, ask which fixes to apply (all / none / numbers), and wait for the user's reply. Do not apply edits unprompted — the approval is recorded from the user's own message."
