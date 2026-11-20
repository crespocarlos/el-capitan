#!/usr/bin/env bash
# UserPromptSubmit hook: record the approval half of the review-address gate.
#
# Only a user turn reaches this hook, so writing `approved` here is what makes the gate
# unforgeable by the model. It stays inert until the orchestrator has written `pending`, which
# happens when the verdict table is presented.
#
# The record copies the pending marker's `session` and `review_dir` rather than inventing its own:
# that is what ties the approval to the exact table it answers. The gate then requires both to
# match, so an "all" from one review cannot authorize another in the same session, and a marker
# left over from a previous session cannot approve anything.
set +e
exec 2>/dev/null

state="$HOME/.agent/review-address"
pending="$state/pending"
approved="$state/approved"
[ -f "$pending" ] || exit 0

input=$(cat)
prompt=$(printf '%s' "$input" | jq -r '.prompt // empty' 2>/dev/null) || exit 0
[ -n "$prompt" ] || exit 0

# A plain-text or malformed marker belongs to a version that had no session scoping; it is stale
# by definition, so it records nothing and the gate treats it the same way.
armed_session=$(jq -r '.session // empty' "$pending" 2>/dev/null) || exit 0
armed_review=$(jq -r '.review_dir // empty' "$pending" 2>/dev/null) || exit 0
[ -n "$armed_session" ] || exit 0

# The approval must come from the same session that armed the gate.
prompt_session=$(printf '%s' "$input" | jq -r '.session_id // .conversation_id // empty' 2>/dev/null)
[ "$prompt_session" = "$armed_session" ] || exit 0

# `none` answered the gate but authorizes no edit, so it records nothing: the skill goes straight
# to the summary, and a later unapproved edit is still denied. Every other accepted shape — a bare
# affirmative, a cherry-pick list, or a number list — authorizes at least one fix.
if printf '%s' "$prompt" | grep -Eqi '^[[:space:]]*(all|yes|ok|approve|approved|apply( all)?|go ahead|do it|proceed)[[:space:].!]*$|^[[:space:]]*[0-9]+([[:space:],]+[0-9]+)*[[:space:]]*$'; then
  mkdir -p "$state" 2>/dev/null
  # Kept as a JSON object, not the raw prompt: the gate needs the identity fields, and `prompt`
  # preserves what the user said for the audit trail.
  jq -n --arg session "$armed_session" --arg review "$armed_review" --arg prompt "$prompt" \
    '{session:$session, review_dir:$review, prompt:$prompt}' > "$approved"
fi
exit 0
