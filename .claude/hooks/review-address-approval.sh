#!/usr/bin/env bash
# UserPromptSubmit hook: record the approval half of the review-address gate.
#
# Only a user turn reaches this hook, so writing `approved` here is what makes the gate
# unforgeable by the model. It stays inert until the orchestrator has written `pending`, which
# happens when the verdict table is presented.
set +e
exec 2>/dev/null

state="$HOME/.agent/review-address"
pending="$state/pending"
approved="$state/approved"
[ -f "$pending" ] || exit 0

input=$(cat)
prompt=$(printf '%s' "$input" | jq -r '.prompt // empty' 2>/dev/null) || exit 0
[ -n "$prompt" ] || exit 0

# `none` answered the gate but authorizes no edit, so it records nothing: the skill goes straight
# to the summary, and a later unapproved edit is still denied. Every other accepted shape — a bare
# affirmative, a cherry-pick list, or a number list — authorizes at least one fix.
if printf '%s' "$prompt" | grep -Eqi '^[[:space:]]*(all|yes|ok|approve|approved|apply( all)?|go ahead|do it|proceed)[[:space:].!]*$|^[[:space:]]*[0-9]+([[:space:],]+[0-9]+)*[[:space:]]*$'; then
  mkdir -p "$state" 2>/dev/null
  printf '%s\n' "$prompt" > "$approved"
fi
exit 0
