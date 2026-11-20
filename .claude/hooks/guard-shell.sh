#!/usr/bin/env bash
# Shell guard for Cursor `beforeShellExecution`, Claude Code `PreToolUse` (Bash), and Cursor's
# lowercase `preToolUse`. Four rules, one preamble, one process.
#
# The four rules were four scripts, each repeating the same jq check, JSON validation, event
# normalization, and allow/deny emitter. Merging them removes that duplication and halves the
# processes a shell call pays for; the rules themselves are unchanged, so the allow/deny fixtures in
# `.claude/hooks/fixtures/run.sh` are the contract this file must keep.
#
# Rules, in order:
#   1. destructive git and local PR-ref reads (`block-destructive-git.sh`)
#   2. credential-like commits and implicit PR targets (`check-publish.sh`)
#   3. Python snippets that rewrite a tracked file (`block-shell-source-edits.sh`)
#   4. zsh equals expansion in an unquoted separator
#
# The first three rules are the ones the retired scripts carried. Rule 4 is new: this repository's
# agents lost three diagnostic runs to `echo =====` aborting a command chain. The allow/deny fixtures
# in `.claude/hooks/fixtures/run.sh` are the contract for all four.
#
# Fails closed: unparsable input or a missing parser denies the command.
set -euo pipefail

if ! command -v jq >/dev/null 2>&1; then
  echo "guard-shell: jq is required; denying so the guard cannot be bypassed." >&2
  exit 2
fi

input=$(cat)
if ! jq -e . >/dev/null 2>&1 <<<"$input"; then
  echo "guard-shell: hook input is not valid JSON; denying." >&2
  exit 2
fi

event=$(printf '%s' "$input" | jq -r '.hook_event_name // empty')
cursor_shell=no
case "$event" in
  PreToolUse) cmd=$(printf '%s' "$input" | jq -r '.tool_input.command // empty'); shape=claude ;;
  preToolUse) cmd=$(printf '%s' "$input" | jq -r '.tool_input.command // .command // empty'); shape=cursor ;;
  beforeShellExecution) cmd=$(printf '%s' "$input" | jq -r '.command // empty'); shape=cursor; cursor_shell=yes ;;
  *) echo "unknown hook_event_name: ${event:-missing}" >&2; exit 2 ;;
esac
cwd=$(printf '%s' "$input" | jq -r '.cwd // empty')
[ -d "$cwd" ] || cwd=$PWD

allow() { jq -n '{permission:"allow"}'; exit 0; }
deny() {
  if [ "$shape" = claude ]; then
    jq -n --arg m "$1" '{hookSpecificOutput:{hookEventName:"PreToolUse",permissionDecision:"deny",permissionDecisionReason:$m}}'
  else
    jq -n --arg m "$1" '{permission:"deny",user_message:$m,agent_message:$m}'
  fi
  exit 0
}

# Here-strings, not pipes: under pipefail, grep -q closing early fails the writer and hides a match.
matches() { grep -Eq -- "$1" <<<"$cmd"; }

msg=''

# --- 1. destructive git, local PR refs ------------------------------------------------------------
# `git` prefix: any run of global options (`-C dir`, `-c k=v`, `--git-dir=`, `--work-tree`,
# `--no-pager`) before the subcommand. Destructive subcommands are just as destructive through them,
# and these are the forms an agent reaches for in a worktree.
GIT='git(([[:space:]]+-{1,2}[^[:space:];&|]+([[:space:]]+[^[:space:];&|]+)?)*)[[:space:]]+'
RESET_OR_CLEAN="${GIT}(reset[[:space:]]+--hard|clean[[:space:]]+-[A-Za-z]*f)"
# `push` is destructive with -f/--force, and with a `+refspec`.
FORCE_PUSH="${GIT}push([[:space:]][^;&|]*)?([[:space:]](-[A-Za-z]*f[A-Za-z]*|--force(-if-includes)?)([[:space:]]|$)|[[:space:]]\+[^[:space:]]+)"

# Quoted text is data: `git commit -m "do not git reset --hard"` must not be denied, and a wrapper
# (`bash -c "git reset --hard"`) is already covered by the escape rule below.
INSPECT=$(printf '%s' "$cmd" | sed -E "s/'[^']*'/''/g; s/\"[^\"]*\"/\"\"/g")

if grep -Eqi -- "$RESET_OR_CLEAN" <<<"$INSPECT"; then
  msg='Destructive git command blocked.'
elif grep -Eqi -- "$FORCE_PUSH" <<<"$INSPECT" && ! grep -q -- '--force-with-lease' <<<"$INSPECT"; then
  msg='Force push blocked. Use --force-with-lease, or ask the user to confirm.'
elif grep -Eqi '(^|[;&| ]+)gh[[:space:]]+pr[[:space:]]+(checkout|co)([[:space:]]|$)|(^|[;&| ]+)git[[:space:]].*(fetch|pull)[[:space:]].*(refs/)?pull/[^[:space:];&|]+' <<<"$cmd"; then
  msg='Pulling a PR into the local checkout is blocked. Read it with `gh pr diff <n>` and `gh api "repos/<owner>/<repo>/contents/<path>?ref=<headSHA>"`.'
elif grep -Eqi '(^|[;&| ]+)git[[:space:]].*(show|diff|log|cat-file|rev-parse|fetch|pull).*(refs/)?pull/' <<<"$cmd"; then
  msg='Reading a local PR ref is blocked. Read PR-head content with `gh pr diff <n>` or `gh api "repos/<owner>/<repo>/contents/<path>?ref=<headSHA>"`.'
elif grep -Eq '(^|[;&| ]+)(gh|git)[^;&|]*\\' <<<"$cmd"; then
  msg='Escaped gh/git commands are blocked. Use the literal command form so the guard can read it.'
fi
[ -z "$msg" ] || deny "$msg"

# --- 2. credential-like commits, implicit PR targets ------------------------------------------------
added_lines() { grep -E '^\+' <<<"$1" | grep -Ev '^\+\+\+ (a/|b/|/dev/null)' || true; }

GIT_COMMIT='(^|[;&|(/[:space:]])git([[:space:]]+-[Cc][[:space:]]+[^[:space:]]+)*[[:space:]]+commit([[:space:]]|$)'
GH_PR_CREATE='(^|[;&|(/[:space:]])gh[[:space:]]+pr[[:space:]]+create([[:space:]]|$)'
DIR_FROM_C='git[[:space:]]+-C[[:space:]]+([^[:space:];&|]+)'
# Anchored to a command position so `cd` inside a commit message cannot redirect the scan.
DIR_FROM_CD='(^|[;&|][[:space:]]*|&&[[:space:]]*|\|\|[[:space:]]*)cd[[:space:]]+([^[:space:];&|]+)'
# High-precision formats only: a false positive blocks the commit.
SECRET_PATTERN='-----BEGIN [A-Z ]*PRIVATE KEY-----|AKIA[0-9A-Z]{16}|gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{22,}|xox[abprs]-[A-Za-z0-9-]{10,}|sk-ant-[A-Za-z0-9_-]{20,}|AIza[0-9A-Za-z_-]{35}'

# Commit messages and other message arguments are data, not commands: blank them before parsing
# directories, or `git commit -m "fix cd back"` scans a nonexistent repo. Blanking every quoted string
# would also blank a quoted directory (`cd 'x'`, `git -C "x"`) and let the scan fall back to the wrong
# repo, so only the message bodies are removed.
if matches "$GIT_COMMIT" || matches "$GH_PR_CREATE"; then
  skeleton=$(printf '%s' "$cmd" | sed -E \
    -e "s/(-m|-F|--message|--file|--body)[[:space:]]+'[^']*'/\1 ''/g" \
    -e 's/(-m|-F|--message|--file|--body)[[:space:]]+"[^"]*"/\1 ""/g')

  repo=$cwd
  dir=""
  if [[ $skeleton =~ $DIR_FROM_C ]]; then dir=${BASH_REMATCH[1]}
  elif [[ $skeleton =~ $DIR_FROM_CD ]]; then dir=${BASH_REMATCH[2]}
  fi
  if [ -n "$dir" ]; then
    dir=${dir//\"/}; dir=${dir//\'/}; dir=${dir/#\~/$HOME}
    [[ $dir = /* ]] || dir=$cwd/$dir
    # Only adopt the candidate when it is a repository; otherwise keep scanning $cwd rather than
    # denying a legitimate commit with a misleading error.
    if git -C "$dir" rev-parse --git-dir >/dev/null 2>&1; then
      repo=$dir
    fi
  fi

  if matches "$GIT_COMMIT"; then
    staged=$(git -C "$repo" diff --cached -U0 2>/dev/null) \
      || deny "Commit check failed: cannot read the git index in $repo."
    added=$(added_lines "$staged")
    if matches '[[:space:]](-a|--all|-[A-Za-z]*a[A-Za-z]*)([[:space:]]|$)'; then
      unstaged=$(git -C "$repo" diff -U0 2>/dev/null) \
        || deny "Commit check failed: cannot read the working tree in $repo."
      added+=$'\n'$(added_lines "$unstaged")
    fi
    if grep -Eq -- "$SECRET_PATTERN" <<<"$added"; then
      deny 'Commit blocked: changes being committed contain a credential-like token or private key. Remove it; rotate it if it was real.'
    fi
  fi

  if matches "$GH_PR_CREATE" \
    && git -C "$repo" remote get-url upstream >/dev/null 2>&1 \
    && ! matches '[[:space:]](--repo|-R)([[:space:]=]|$)'; then
    deny 'PR blocked: an upstream remote exists, so pass --repo explicitly. Target upstream unless the user chose origin.'
  fi
fi

# --- 3. Python snippets that rewrite a tracked file -------------------------------------------------
# Intentional target: Python snippets, not normal Python tools. A snippet that writes a task artifact
# is permitted unless it names a tracked file; a snippet that rewrites tracked source loses the edit
# log and must use the native Edit or Write tool instead.
# The `/?` before `python` also matches an absolute or venv-relative interpreter
# (`/usr/bin/python3`, `.venv/bin/python3`), which has no word boundary this guard can rely on
# otherwise; `([[:space:]]|$)` lets a bare `python3<<PY` (no space before the heredoc) still match.
if grep -Eq '(^|[;&|[:space:]]|/)python([0-9.]*)?([[:space:]]|$).*(<<|-[[:space:]]*c)' <<<"$cmd" \
  && grep -Eq 'write_(text|bytes)[[:space:]]*\(|open[[:space:]]*\(.*["'\'']([wax+]+|r\+)["'\'']|os\.replace[[:space:]]*\(|shutil\.(copy|move)' <<<"$cmd"; then
  root=$(git -C "$cwd" rev-parse --show-toplevel 2>/dev/null) || root=""
  # Check candidate path literals individually against the index instead of enumerating every tracked
  # file: avoids a full `git ls-files` scan per matching command on a large monorepo checkout, and
  # resolving each candidate against `$cwd` (rather than a raw substring match against the
  # repo-root-relative form) catches a write issued after `cd`-ing into a subdirectory.
  while [ -n "$root" ] && IFS= read -r candidate; do
    [ -n "$candidate" ] || continue
    resolved=$(cd "$cwd" 2>/dev/null && realpath "$candidate" 2>/dev/null) || continue
    case "$resolved" in
      "$root"/*) rel=${resolved#"$root"/} ;;
      *) continue ;;
    esac
    if git -C "$root" ls-files --error-unmatch -- "$rel" >/dev/null 2>&1; then
      deny "Shell rewrite blocked: Python snippets must not rewrite tracked file '$rel'. Use the Edit or Write tool."
    fi
  done < <(grep -oE '"[^"]+"|'"'"'[^'"'"']+'"'"'' <<<"$cmd" | sed -e 's/^.//' -e 's/.$//')
fi

# --- 4. zsh equals expansion ------------------------------------------------------------------------
# An unquoted word whose first character is `=` is a command-path lookup in zsh (`echo =====` looks up
# a command named `====`), fails with `not found`, and aborts the rest of the command line — every
# statement after the separator is lost. The trigger is a length of two or more: `echo =` is fine, as
# are `x=y`, `--flag=value`, `[[ a == a ]]`, `[ a = a ]`, and any quoted form.
#
# Gate on the shell that will actually run the command, never on `$SHELL`: that variable is the
# *login* shell, so a bash-executing harness on a zsh-login host would deny commands it runs
# correctly. Cursor's shell execution is the login shell (zsh on macOS); a harness that also executes
# zsh declares it with `CREW_SHELL_IS_ZSH=1` in the hook environment. bash expands nothing here, so
# everywhere else the rule stays out of the way.
if { [ "$cursor_shell" = yes ] || [ "${CREW_SHELL_IS_ZSH:-}" = 1 ]; }; then
  # Heredoc bodies are data, but only the body: a line after the terminator is real shell and must
  # still be checked, so the body is removed rather than the whole command exempted. `<<-` strips
  # leading tabs from its terminator, so the comparison strips them too; an exact compare left the
  # state open forever and silently stopped checking every line after it.
  no_heredoc=$(printf '%s\n' "$cmd" | awk '
    {
      line = $0
      sub(/^[ \t]+/, "", line)
      if (heredoc != "") { if (line == heredoc) heredoc = ""; next }
      if (match($0, /<<-?[ \t]*["\047]?[A-Za-z_][A-Za-z0-9_]*["\047]?/)) {
        token = substr($0, RSTART, RLENGTH)
        sub(/<<-?[ \t]*/, "", token)
        gsub(/["\047]/, "", token)
        heredoc = token
      }
      print
    }')
  # Quoted strings, bracket tests, and comments are data too. Order matters: quotes first, so a `#`
  # inside a string cannot look like a comment, and comments before the match, so a `# =====` section
  # divider is not denied. A here-string `<<<` keeps its argument but loses the operator.
  stripped=$(printf '%s\n' "$no_heredoc" \
    | sed -e "s/'[^']*'//g" -e 's/"[^"]*"//g' -e 's/\[\[[^]]*\]\]//g' -e 's/\[[^]]*\]//g' \
          -e 's/<<</ /g' -e 's/#.*//')
  if grep -Eq '(^|[[:space:]])=[^[:space:]]' <<<"$stripped"; then
    word=$(grep -Eo '(^|[[:space:]])=[^[:space:]]*' <<<"$stripped" | head -1 | tr -d '[:space:]')
    deny "Bare \`${word}\` is zsh equals-expansion, not text: the shell reads it as a command path, fails with \`not found\`, and aborts the rest of the line, so every command after it is lost. Quote the separator (\`echo '====='\` or \`printf '%s\n' '-----'\`) and re-run."
  fi
fi

allow
