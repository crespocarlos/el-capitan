#!/usr/bin/env bash
# Python snippets that rewrite a tracked file. The intent is snippets, not normal Python tools: an
# artifact write is fine unless it names a tracked file, and a snippet that rewrites tracked source
# loses the edit log, so the native Edit or Write tool is the only way through.
set -euo pipefail
HOOK_NAME=source-edit
# shellcheck source=lib/hook.sh
. "$(dirname "$0")/../lib/hook.sh"
hook_input
hook_event
cmd=$(hook_field command)
cwd=$HOOK_CWD
[ -n "$cmd" ] || hook_allow

# The `/?` before `python` also matches an absolute or venv-relative interpreter
# (`/usr/bin/python3`, `.venv/bin/python3`), which has no word boundary to rely on otherwise;
# `([[:space:]]|$)` lets a bare `python3<<PY` (no space before the heredoc) still match.
snippet='(^|[;&|[:space:]]|/)python([0-9.]*)?([[:space:]]|$).*(<<|-[[:space:]]*c)'
write='write_(text|bytes)[[:space:]]*\(|open[[:space:]]*\(.*["'\'']([wax+]+|r\+)["'\'']|os\.replace[[:space:]]*\(|shutil\.(copy|move)'
grep -Eq "$snippet" <<<"$cmd" && grep -Eq "$write" <<<"$cmd" || hook_allow

root=$(git -C "$cwd" rev-parse --show-toplevel 2>/dev/null) || root=""
[ -n "$root" ] || hook_allow
# Each path literal is checked against the index individually instead of enumerating every tracked
# file: no full `git ls-files` scan per matching command, and resolving each candidate against `$cwd`
# catches a write issued after `cd`-ing into a subdirectory.
while IFS= read -r candidate; do
  [ -n "$candidate" ] || continue
  resolved=$(cd "$cwd" 2>/dev/null && realpath "$candidate" 2>/dev/null) || continue
  case "$resolved" in "$root"/*) rel=${resolved#"$root"/} ;; *) continue ;; esac
  if git -C "$root" ls-files --error-unmatch -- "$rel" >/dev/null 2>&1; then
    hook_deny "Shell rewrite blocked: Python snippets must not rewrite tracked file '$rel'. Use the Edit or Write tool."
  fi
done < <(grep -oE '"[^"]+"|'"'"'[^'"'"']+'"'"'' <<<"$cmd" | sed -e 's/^.//' -e 's/.$//')
hook_allow
