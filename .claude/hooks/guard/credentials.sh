#!/usr/bin/env bash
# Credential-like commits, and `gh pr create` whose target is implied rather than named. A commit is
# scanned for what it would record: the index, the working tree with `-a`, and whatever a `git add` in
# the same command stages. Registered `onFailure: "block"` / `failClosed: true`, yet only an error once
# the secret scan has started (scanning=1) blocks; one before it (input, normaliser) reports a line and
# lets the command through, as does any failure under an off switch. Piped scripts: the command guards.
set -euo pipefail
HOOK_NAME=credentials
HOOK_FAIL_CLOSED=1 HOOK_FAIL_BLOCKS=0 HOOK_SHELL_STDIN=allow
# shellcheck source=lib/hook.sh
. "$(dirname "$0")/../lib/hook.sh"
hook_stand_down guard/credentials.sh fail-closed
hook_input
hook_event
cmd=$(hook_field command)
[ -n "$cmd" ] || hook_allow

scanning=0
internal() {
  if [ "$scanning" = 1 ]; then hook_deny "Commit blocked: the secret scan failed ($1), so the commit was not checked."; fi
  printf '%s: %s; no objection\n' "$HOOK_NAME" "$1" >&2
  hook_allow
}
trap 'rc=$?; [ "$rc" = 0 ] || [ "$rc" = 2 ] || internal "unexpected exit $rc"' EXIT
hook_segments "$cmd"
commits="" adds="" i=0
while [ "$i" -lt "${#HOOK_SEGS[@]}" ]; do
  hook_seg "$i"
  i=$((i + 1))
  if [ "${SEG_WORDS[0]##*/}" = gh ] && [ "${SEG_WORDS[1]:-} ${SEG_WORDS[2]:-}" = "pr create" ]; then
    named=0
    for word in "${SEG_WORDS[@]}"; do case "$word" in --repo | --repo=* | -R*) named=1 ;; esac; done
    hook_repo "$SEG_DIR"
    if [ "$named" = 0 ] && [ -n "$REPO" ] && git -C "$REPO" remote get-url upstream >/dev/null 2>&1; then
      hook_deny 'PR blocked: an upstream remote exists, so pass --repo explicitly. Target upstream unless the user chose origin.'
    fi
  fi
  hook_git || continue
  case "$GIT_SUB" in commit) commits+=" $((i - 1))" ;; add) adds+=" $((i - 1))" ;; esac
done
[ -n "$commits" ] || hook_allow

scanning=1 added="" HOOK_FAIL_BLOCKS=1
# One pattern, shared with `crew-task.py ship`, high-precision formats only (a false positive blocks a real
# commit); when it cannot be read the scan fails and the commit is blocked.
SECRET=$(head -n 1 "$(dirname "$0")/../lib/token-patterns.ere")
for k in $adds $commits; do
  hook_seg "$k"
  hook_git
  hook_repo "$GIT_TREE"
  [ -n "$REPO" ] || continue
  if [ "$GIT_SUB" = add ]; then added+=$'\n'$(hook_git_added "$REPO" yes ${GIT_ARGS[@]+"${GIT_ARGS[@]}"}); continue; fi
  staged=$(git -C "$REPO" diff --cached -U0 2>/dev/null) || hook_deny "Commit check failed: cannot read the git index in $REPO."
  added+=$'\n'$(hook_plus_lines <<<"$staged")
  if hook_git_arg '^(--all|-[A-Za-z]*a[A-Za-z]*)$'; then added+=$'\n'$(hook_git_added "$REPO" no); fi
done
found=0
grep -Eq -- "$SECRET" <<<"$added" 2>/dev/null || found=$?
[ "$found" -le 1 ] || internal "grep exited $found"
[ "$found" = 1 ] || hook_deny 'Commit blocked: changes being committed contain a credential-like token or private key. Remove it; rotate it if it was real.'
hook_allow
