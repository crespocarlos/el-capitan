#!/usr/bin/env bash
# Destructive git: `reset --hard`, `clean` with force, and force pushes (`-f`, `--force`, a `+ref`,
# also next to `--force-with-lease`; `--force-if-includes` without a lease). Registered on the Bash matcher, so this is the only rule that
# speaks for those commands. The command is read through the normaliser in lib/hook.sh, so quotes,
# escapes, `sh -c` payloads, `$(...)`, chained segments and git's global options hide nothing, while
# a quoted message or a heredoc body stays data.
set -euo pipefail
HOOK_NAME=destructive-git
# shellcheck source=lib/hook.sh
. "$(dirname "$0")/../lib/hook.sh"
hook_input
hook_event
cmd=$(hook_field command)
[ -n "$cmd" ] || hook_allow

FORCE='^(--force|-[A-Za-z]*f[A-Za-z]*)$'
hook_segments "$cmd"
i=0
while [ "$i" -lt "${#HOOK_SEGS[@]}" ]; do
  hook_seg "$i"
  i=$((i + 1))
  hook_git || continue
  case "$GIT_SUB" in
    reset)
      if hook_git_arg '^--hard$'; then hook_deny 'Destructive git command blocked: git reset --hard discards uncommitted work.'; fi ;;
    clean)
      if hook_git_arg "$FORCE"; then hook_deny 'Destructive git command blocked: git clean with force deletes untracked files.'; fi ;;
    push)
      # `--force-if-includes` only tightens a lease, so it passes next to `--force-with-lease`.
      if hook_git_arg "$FORCE" || hook_git_arg '^\+.+$' \
        || { hook_git_arg '^--force-if-includes$' && ! hook_git_arg '^--force-with-lease(=.*)?$'; }; then
        hook_deny 'Force push blocked. Use --force-with-lease alone, or ask the user to confirm.'
      fi ;;
  esac
done
hook_allow
