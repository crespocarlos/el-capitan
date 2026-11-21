#!/usr/bin/env bash
# The one hook contract, shared by every hook under `.claude/hooks/`.
#
# One mechanism per run, never both:
#   block         Claude `PreToolUse`: exit 2, the reason on stderr, nothing on stdout.
#                 Cursor `preToolUse` / `beforeShellExecution`: one JSON deny on stdout, exit 0.
#   no objection  exit 0 and print nothing on either stream, so the harness's own permission flow
#                 decides. An explicit allow would skip interactive approval, so none is emitted.
#   cannot judge  one line on stderr and exit 0. A hook that sets `HOOK_FAIL_CLOSED=1` exits 2
#                 instead; the same rule carries `onFailure: "block"` in `.claude/settings.json` and
#                 `failClosed: true` in `.cursor/hooks.template.json`, so a crash blocks too.
#
# Usage: set HOOK_NAME, source this file, then call hook_input, hook_event, hook_field NAME, and
# finish with hook_deny MESSAGE or hook_allow.
# shellcheck shell=bash

hook_fail() {
  printf '%s: %s\n' "${HOOK_NAME:-hook}" "$1" >&2
  if [ "${HOOK_FAIL_CLOSED:-0}" = 1 ]; then exit 2; fi
  exit 0
}

# Read stdin once, then split the envelope in one parser call. No input at all counts as `{}`.
# jq's own diagnostics are captured, not printed: the contract is one stderr line per failure.
hook_input() {
  HOOK_INPUT=$(cat) || hook_fail "cannot read hook input"
  command -v jq >/dev/null 2>&1 || hook_fail "jq is not installed; cannot read hook input"
  [ -n "$HOOK_INPUT" ] || HOOK_INPUT='{}'
  local parsed
  parsed=$(printf '%s' "$HOOK_INPUT" | jq -er '[(.hook_event_name // ""), (.cwd // "")] | @tsv' 2>/dev/null) \
    || hook_fail "hook input is not valid JSON"
  meta=$parsed
  HOOK_EVENT=${meta%%$'\t'*}
  HOOK_CWD=${meta#*$'\t'}
}

# Normalize the three event spellings into one shape, and anchor cwd to something that exists.
hook_event() {
  case "$HOOK_EVENT" in
    PreToolUse) HOOK_SHAPE=claude ;;
    preToolUse | beforeShellExecution) HOOK_SHAPE=cursor ;;
    *) hook_fail "unsupported hook_event_name: ${HOOK_EVENT:-missing}" ;;
  esac
  if [ -z "$HOOK_CWD" ] || [ ! -d "$HOOK_CWD" ]; then HOOK_CWD=$PWD; fi
}

# One `tool_input` field across both harness shapes; `beforeShellExecution` carries it at the top.
hook_field() {
  printf '%s' "$HOOK_INPUT" | jq -r --arg k "$1" \
    'if .hook_event_name == "beforeShellExecution" then (.command // "")
     else (.tool_input[$k] // .[$k] // "") end' \
    || hook_fail "cannot read $1 from hook input"
}

hook_deny() {
  if [ "$HOOK_SHAPE" = claude ]; then
    printf '%s\n' "$1" >&2
    exit 2
  fi
  jq -n --arg m "$1" '{permission:"deny",user_message:$m,agent_message:$m}' \
    || hook_fail "cannot emit the denial"
  exit 0
}

# No objection is silence: exit 0 with nothing on either stream, so the harness's own permission flow
# decides. An explicit allow would skip interactive approval, so none is emitted.
#
# One measured exception: Cursor reads *no output at all* from a hook registered `failClosed: true` as
# a crash and blocks the command, so silence there is not a decline. The only such hook is
# `guard/credentials.sh`, and it answers with `{}` — an empty decision object, which carries no
# permission at all, so it adds nothing to the harness's own flow and skips no approval.
hook_allow() {
  if [ "${HOOK_FAIL_CLOSED:-0}" = 1 ] && [ "$HOOK_SHAPE" = cursor ]; then
    jq -n '{}' || hook_fail "cannot emit the decision"
  fi
  exit 0
}
