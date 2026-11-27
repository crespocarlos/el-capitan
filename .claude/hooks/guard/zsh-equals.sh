#!/usr/bin/env bash
# zsh equals-expansion. Measured with `zsh -c '<cmd>; echo after'`: an unquoted word whose first
# character `=` is a command-path lookup, so `==`, `===`, `====` and `=ls` all print `not found` and
# drop the rest of the line. `echo =` is the one safe unquoted form, and every quoted form is text.
#
# Which shell runs the command decides whether this applies, and the rule must not guess. Three
# signals, strongest first: the event shape (Cursor's shell execution is the login shell), an explicit
# `CREW_SHELL_IS_ZSH` declaration, then `$SHELL`. The third was previously excluded on the grounds
# that it names the *login* shell — true, but assuming bash instead made the rule dead code in this
# harness: `CREW_SHELL_IS_ZSH` is set nowhere, so every `echo =====` went through. A heuristic that can
# be wrong in a case where the alternative is silently never running is worse than the heuristic.
set -euo pipefail
HOOK_NAME=zsh-equals
# shellcheck source=lib/hook.sh
. "$(dirname "$0")/../lib/hook.sh"
hook_stand_down guard/zsh-equals.sh
hook_input
hook_event
cmd=$(hook_field command)
[ -n "$cmd" ] || hook_allow
executing_shell=${SHELL:-/bin/sh}
case "$executing_shell" in
  */zsh*) login_is_zsh=1 ;;
  *) login_is_zsh=0 ;;
esac
if [ "$HOOK_EVENT" != beforeShellExecution ] \
   && [ "${CREW_SHELL_IS_ZSH:-}" != 1 ] && [ "$login_is_zsh" != 1 ]; then
  hook_allow
fi

# Heredoc bodies are data, but only the body: a line after the terminator is real shell and must
# still be checked, so the body is removed rather than the whole command exempted. `<<-` strips
# leading tabs from its terminator, so the comparison strips them too; an exact compare left the
# state open forever and silently stopped checking every line after it.
command -v awk >/dev/null 2>&1 || hook_fail "awk is not installed; cannot parse the shell command"
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
