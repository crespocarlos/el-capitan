#!/usr/bin/env bash
# Credential-like commits, and `gh pr create` whose target is implied rather than named. The only rule
# registered `onFailure: "block"` / `failClosed: true`: a failure here is a credential leak.
set -euo pipefail
HOOK_NAME=credentials
HOOK_FAIL_CLOSED=1
# shellcheck source=lib/hook.sh
. "$(dirname "$0")/../lib/hook.sh"
hook_input
hook_event
cmd=$(hook_field command)
repo=$HOOK_CWD

matches() { grep -Eq -- "$1" <<<"$2"; }
COMMIT='(^|[;&|(/[:space:]])git([[:space:]]+-[Cc][[:space:]]+[^[:space:]]+)*[[:space:]]+commit([[:space:]]|$)'
PR_CREATE='(^|[;&|(/[:space:]])gh[[:space:]]+pr[[:space:]]+create([[:space:]]|$)'
if [ -z "$cmd" ] || ! matches "$COMMIT|$PR_CREATE" "$cmd"; then hook_allow; fi

# Message bodies are data, blanked before the directory scan: `git commit -m "fix cd back"` must not
# look for a repository named `back`, while a quoted directory (`cd 'x'`) keeps its value. Only a `cd`
# in a command position counts, or one inside a message would redirect the scan.
skeleton=$(printf '%s' "$cmd" | sed -E \
  -e "s/(-m|-F|--message|--file|--body)[[:space:]]+'[^']*'/\1 ''/g" \
  -e 's/(-m|-F|--message|--file|--body)[[:space:]]+"[^"]*"/\1 ""/g')
dir=""
if [[ $skeleton =~ git[[:space:]]+-C[[:space:]]+([^[:space:];&|]+) ]]; then dir=${BASH_REMATCH[1]}
elif [[ $skeleton =~ (^|[;&|][[:space:]]*|&&[[:space:]]*|\|\|[[:space:]]*)cd[[:space:]]+([^[:space:];&|]+) ]]; then
  dir=${BASH_REMATCH[2]}
fi
# Adopt the candidate only when it is a repository, rather than denying a clean commit.
if [ -n "$dir" ]; then
  dir=${dir//\"/}; dir=${dir//\'/}; dir=${dir/#\~/$HOME}
  [[ $dir = /* ]] || dir=$HOOK_CWD/$dir
  if git -C "$dir" rev-parse --git-dir >/dev/null 2>&1; then repo=$dir; fi
fi

added_lines() { grep -E '^\+' <<<"$1" | grep -Ev '^\+\+\+ (a/|b/|/dev/null)' || true; }
# High-precision formats only: a false positive blocks a real commit.
SECRET='-----BEGIN [A-Z ]*PRIVATE KEY-----|AKIA[0-9A-Z]{16}|gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{22,}|xox[abprs]-[A-Za-z0-9-]{10,}|sk-ant-[A-Za-z0-9_-]{20,}|AIza[0-9A-Za-z_-]{35}'
if matches "$COMMIT" "$cmd"; then
  staged=$(git -C "$repo" diff --cached -U0 2>/dev/null) \
    || hook_deny "Commit check failed: cannot read the git index in $repo."
  added=$(added_lines "$staged")
  if matches '[[:space:]](-a|--all|-[A-Za-z]*a[A-Za-z]*)([[:space:]]|$)' "$cmd"; then
    unstaged=$(git -C "$repo" diff -U0 2>/dev/null) \
      || hook_deny "Commit check failed: cannot read the working tree in $repo."
    added+=$'\n'$(added_lines "$unstaged")
  fi
  if matches "$SECRET" "$added"; then
    hook_deny 'Commit blocked: changes being committed contain a credential-like token or private key. Remove it; rotate it if it was real.'
  fi
fi

if matches "$PR_CREATE" "$cmd" && git -C "$repo" remote get-url upstream >/dev/null 2>&1 \
  && ! matches '[[:space:]](--repo|-R)([[:space:]=]|$)' "$cmd"; then
  hook_deny 'PR blocked: an upstream remote exists, so pass --repo explicitly. Target upstream unless the user chose origin.'
fi
hook_allow
