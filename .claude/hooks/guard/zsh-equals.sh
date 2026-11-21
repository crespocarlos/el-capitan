#!/usr/bin/env bash
# zsh equals-expansion. Measured with `zsh -c '<cmd>; echo after'`: an unquoted word whose first
# character is `=` is a command-path lookup, so `==`, `===`, `====` and `=ls` all print
# `not found` and drop the rest of the line. `echo =` is the one safe unquoted form — zsh reads a
# lone `=` as text — and every quoted form is text.
#
# Gate on the shell that will run the command, never on `$SHELL`: that variable is the *login* shell,
# so a bash-executing harness on a zsh-login host would deny commands it runs correctly. Cursor's
# shell execution is the login shell (zsh on macOS); a harness that also executes zsh declares it
# with `CREW_SHELL_IS_ZSH=1` in the hook environment. bash expands nothing here.
set -euo pipefail
HOOK_NAME=zsh-equals
# shellcheck source=lib/hook.sh
. "$(dirname "$0")/../lib/hook.sh"
hook_input
hook_event
cmd=$(hook_field command)
[ -n "$cmd" ] || hook_allow
if [ "$HOOK_EVENT" != beforeShellExecution ] && [ "${CREW_SHELL_IS_ZSH:-}" != 1 ]; then
  hook_allow
fi

# Heredoc bodies are data, but only the body: a line after the terminator is real shell and must
# still be checked, so the body is removed rather than the whole command exempted. `<<-` strips
# leading tabs from its terminator, so the comparison strips them too; an exact compare left the
# state open forever and silently stopped checking every line after it.
body=$(printf '%s\n' "$cmd" | awk '
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
# Quotes, bracket tests, and comments are data too. Order matters: quotes first, so a `#` inside a
# string cannot look like a comment, and comments before the match, so a `# =====` divider is not
# denied. A here-string `<<<` keeps its argument but loses the operator.
bare=$(printf '%s\n' "$body" | sed -e "s/'[^']*'//g" -e 's/"[^"]*"//g' -e 's/\[\[[^]]*\]\]//g' \
  -e 's/\[[^]]*\]//g' -e 's/<<</ /g' -e 's/#.*//')
word=$(grep -Eo '(^|[[:space:]])=[^[:space:]]+' <<<"$bare" | head -1 | tr -d '[:space:]') || true
[ -n "$word" ] || hook_allow
hook_deny "Bare \`${word}\` is zsh equals-expansion, not text: the shell reads it as a command path, fails with \`not found\`, and aborts the rest of the line, so every command after it is lost. Quote the separator (\`echo '====='\` or \`printf '%s\n' '-----'\`) and re-run."
