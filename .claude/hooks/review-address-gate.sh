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
# Both carry the session and review directory they belong to. A marker from another session is
# stale by definition — the table it answered is not on screen — so it allows rather than denying
# an unrelated edit, which is what a single unscoped file got wrong: one `pending` left behind by
# an earlier review blocked the next unrelated edit with a message about findings nobody had
# presented. A plain-text marker written before this rule has no session, is likewise stale, and
# allows, so an existing install heals itself.
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

# Cursor sends `conversation_id`, Claude Code sends `session_id`.
session=$(jq -r '.session_id // .conversation_id // empty' <<<"$input")

state="$HOME/.agent/review-address"
pending="$state/pending"
approved="$state/approved"

[ -f "$pending" ] || allow

# A marker that is not this session's cannot describe a table the user is looking at.
armed_session=$(jq -r '.session // empty' "$pending" 2>/dev/null || true)
[ "$armed_session" = "$session" ] && [ -n "$session" ] || allow

armed_review=$(jq -r '.review_dir // empty' "$pending" 2>/dev/null || true)

# Approval must answer this exact arming, in this session, so a stale "all" from an earlier review
# cannot authorize this one. The prompt text is kept for the audit trail.
if [ -f "$approved" ]; then
  approved_session=$(jq -r '.session // empty' "$approved" 2>/dev/null || true)
  approved_review=$(jq -r '.review_dir // empty' "$approved" 2>/dev/null || true)
  if [ "$approved_session" = "$session" ] && [ "$approved_review" = "$armed_review" ]; then
    allow
  fi
fi

deny "Review-address gate: the verdict table for ${armed_review:-this review} in this session has no approval recorded. Reply with which fixes to apply (all / none / numbers). Do not apply edits unprompted — the approval is recorded from your own message."
