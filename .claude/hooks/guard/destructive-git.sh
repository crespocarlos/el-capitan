#!/usr/bin/env bash
# Destructive git: `reset --hard`, `clean -f`, force pushes, and the escaped form that dodges the
# pattern. Registered on the Bash matcher, so this is the only rule that speaks for those commands.
set -euo pipefail
HOOK_NAME=destructive-git
# shellcheck source=lib/hook.sh
. "$(dirname "$0")/../lib/hook.sh"
hook_input
hook_event
cmd=$(hook_field command)
[ -n "$cmd" ] || hook_allow

# Any run of global options (`-C dir`, `-c k=v`, `--git-dir=`, `--work-tree`, `--no-pager`) before
# the subcommand: destructive subcommands are just as destructive through them, and an agent in a
# worktree reaches for exactly those forms.
GIT='git(([[:space:]]+-{1,2}[^[:space:];&|]+([[:space:]]+[^[:space:];&|]+)?)*)[[:space:]]+'
RESET_OR_CLEAN="${GIT}(reset[[:space:]]+--hard|clean[[:space:]]+-[A-Za-z]*f)"
FORCE_PUSH="${GIT}push([[:space:]][^;&|]*)?([[:space:]](-[A-Za-z]*f[A-Za-z]*|--force(-if-includes)?)([[:space:]]|$)|[[:space:]]\+[^[:space:]]+)"
# Quoted text is data: `git commit -m "do not git reset --hard"` is a message, not a command.
INSPECT=$(printf '%s' "$cmd" | sed -E "s/'[^']*'/''/g; s/\"[^\"]*\"/\"\"/g")

if grep -Eqi -- "$RESET_OR_CLEAN" <<<"$INSPECT"; then
  hook_deny 'Destructive git command blocked.'
fi
if grep -Eqi -- "$FORCE_PUSH" <<<"$INSPECT" && ! grep -q -- '--force-with-lease' <<<"$INSPECT"; then
  hook_deny 'Force push blocked. Use --force-with-lease, or ask the user to confirm.'
fi
# A backslash inside the command hides the subcommand from every pattern above. Two kinds exist and
# only one is an escape: `git res\et` uses a backslash to break a word, while `--jq '"#\(.x)"'` uses
# one inside a quoted argument as a jq escape. The scan therefore blanks quoted content (so a quoted
# backslash is invisible) and keeps everything else, which is the inverse of INSPECT only in that it
# preserves unquoted backslashes.
ESCAPE_VIEW=$(printf '%s' "$cmd" | sed -E "s/'[^']*'//g; s/\"[^\"]*\"//g")
if grep -Eq '(^|[;&| ]+)(gh|git)[^;&|]*\\' <<<"$ESCAPE_VIEW"; then
  hook_deny 'Escaped gh/git commands are blocked. Use the literal command form so the guard can read it.'
fi
hook_allow
