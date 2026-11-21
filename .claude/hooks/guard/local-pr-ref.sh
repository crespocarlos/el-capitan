#!/usr/bin/env bash
# Local PR refs: `gh pr checkout` and `pull/<n>` fetches put a PR into the working checkout, which
# makes a review read the author's tree instead of the reviewed commit.
set -euo pipefail
HOOK_NAME=local-pr-ref
# shellcheck source=lib/hook.sh
. "$(dirname "$0")/../lib/hook.sh"
hook_input
hook_event
cmd=$(hook_field command)
[ -n "$cmd" ] || hook_allow

CHECKOUT='(^|[;&| ]+)gh[[:space:]]+pr[[:space:]]+(checkout|co)([[:space:]]|$)'
FETCH='(^|[;&| ]+)git[[:space:]].*(fetch|pull)[[:space:]].*(refs/)?pull/[^[:space:];&|]+'
READ='(^|[;&| ]+)git[[:space:]].*(show|diff|log|cat-file|rev-parse|fetch|pull).*(refs/)?pull/'

if grep -Eqi -- "$CHECKOUT|$FETCH" <<<"$cmd"; then
  hook_deny 'Pulling a PR into the local checkout is blocked. Read it with `gh pr diff <n>` and `gh api "repos/<owner>/<repo>/contents/<path>?ref=<headSHA>"`.'
fi
if grep -Eqi -- "$READ" <<<"$cmd"; then
  hook_deny 'Reading a local PR ref is blocked. Read PR-head content with `gh pr diff <n>` or `gh api "repos/<owner>/<repo>/contents/<path>?ref=<headSHA>"`.'
fi
hook_allow
