#!/usr/bin/env bash
# Local PR refs: `gh pr checkout` and `pull/<n>` fetches put a PR into the working checkout, which
# makes a review read the author's tree instead of the reviewed commit. `gh` is read by hook_gh, so
# `-R`, escapes and a runner in front hide nothing. Only a ref counts: an argument
# before `--` that starts with `refs/pull/`, `pull/<n>` or `pull/*` (or carries one after `..`, `:`, `^`, `+`
# or `~`), so a path such as `src/pull/handler.ts` is never mistaken for one.
set -euo pipefail
HOOK_NAME=local-pr-ref
# shellcheck source=lib/hook.sh
. "$(dirname "$0")/../lib/hook.sh"
hook_stand_down guard/local-pr-ref.sh fail-closed
hook_input
hook_event
cmd=$(hook_field command)
[ -n "$cmd" ] || hook_allow

PULL='Pulling a PR into the local checkout is blocked. Read it with `gh pr diff <n>` and `gh api "repos/<owner>/<repo>/contents/<path>?ref=<headSHA>"`.'
READ='Reading a local PR ref is blocked. Read PR-head content with `gh pr diff <n>` or `gh api "repos/<owner>/<repo>/contents/<path>?ref=<headSHA>"`.'
REF='(^|[.:^+~])(refs/pull/|pull/([0-9*]|\$))'
hook_segments "$cmd"
i=0
while [ "$i" -lt "${#HOOK_SEGS[@]}" ]; do
  hook_seg "$i"
  i=$((i + 1))
  if hook_gh && [ "$GH_CMD" = pr ]; then
    case "$GH_SUB" in checkout | co) hook_deny "$PULL" ;; esac
  fi
  hook_git || continue
  case "$GIT_SUB" in
    fetch | pull) if hook_git_arg "$REF"; then hook_deny "$PULL"; fi ;;
    show | diff | log | cat-file | rev-parse) if hook_git_arg "$REF"; then hook_deny "$READ"; fi ;;
  esac
done
hook_allow
