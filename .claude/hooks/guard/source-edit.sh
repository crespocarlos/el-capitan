#!/usr/bin/env bash
# Inline snippets that rewrite a tracked file: `python -c`, `node -e`/`-p`, `perl -e` and a heredoc or
# here-string fed to one of them. The intent is snippets, not normal tools: a write is fine unless its
# target names a tracked file (Python: the parsed write target, `lib/py_write_targets.py`; otherwise any
# path literal in a snippet that writes), and a snippet that rewrites tracked source loses
# the edit log, so the native Edit or Write tool is the only way through. The snippet body comes from
# the normaliser in lib/hook.sh, so both quoting styles read the same, and each path is checked
# against the index of the tree its segment runs in (after any `cd`).
set -euo pipefail
HOOK_NAME=source-edit
# shellcheck source=lib/hook.sh
. "$(dirname "$0")/../lib/hook.sh"
hook_stand_down guard/source-edit.sh fail-closed
hook_input
hook_event
cmd=$(hook_field command)
[ -n "$cmd" ] || hook_allow

q="[\"']"
WRITE="write_(text|bytes)[[:space:]]*\(|open[[:space:]]*\(.*$q([wax+]+b?|r\+b?)$q|os\.(replace|rename)[[:space:]]*\(|shutil\.(copy|move)"
WRITE+="|(writeFile|appendFile|copyFile|rename)(Sync)?[[:space:]]*\(|createWriteStream|open[^;]*$q[[:space:]]*\+?>"
PY_WRITE="subprocess|os\.(open|write|system|popen)[[:space:]]*\(|fileinput|(exec|eval|getattr|__import__)[[:space:]]*\("
hook_segments "$cmd"
i=0
while [ "$i" -lt "${#HOOK_SEGS[@]}" ]; do
  hook_seg "$i"
  i=$((i + 1))
  case "${SEG_WORDS[0]##*/}" in python | python[0-9]* | node | nodejs | perl) ;; *) continue ;; esac
  snippet=$SEG_BODY
  j=1
  while [ "$j" -lt "${#SEG_WORDS[@]}" ]; do
    case "${SEG_WORDS[$j]}" in
      -c | -e | -E | -p | --eval | --print | -[A-Za-z]*[ce]) snippet+=$'\n'"${SEG_WORDS[$((j + 1))]:-}" ;;
    esac
    j=$((j + 1))
  done
  # Python can also write through a process, `os.open`, `fileinput` or code it builds at run time.
  pattern=$WRITE
  case "${SEG_WORDS[0]##*/}" in python*) pattern+="|$PY_WRITE" ;; esac
  if [ -z "$snippet" ] || ! grep -Eq -- "$pattern" <<<"$snippet"; then continue; fi
  # Python is parsed (never run) and only a write's target counts, so a tracked file the snippet merely
  # reads passes. Node, Perl and a Python snippet that does not parse, or holds a write the parser cannot
  # resolve (exit 3), keep the broader rule: any quoted literal in a snippet that writes somewhere.
  parsed=0
  case "${SEG_WORDS[0]##*/}" in
    python*) candidates=$(python3 -I "$HOOK_LIB/py_write_targets.py" <<<"$snippet" 2>/dev/null) && parsed=1 ;;  # crew-lint: allow-swallow
  esac
  if [ "$parsed" -eq 0 ]; then
    candidates=$(grep -oE "\"[^\"]+\"|'[^']+'" <<<"$snippet" | sed -e 's/^.//' -e 's/.$//') || candidates=""
  fi
  while IFS= read -r candidate; do
    candidate=${candidate#"${candidate%%[!+<> ]*}"}
    [ -n "$candidate" ] || continue
    # Only a tracked regular file counts: `.` and a directory name match tracked files below them.
    hook_path "$candidate" "$SEG_DIR"
    [ -f "$HOOK_PATH" ] || continue
    if git --literal-pathspecs -C "$SEG_DIR" ls-files --error-unmatch -- "$candidate" >/dev/null 2>&1; then
      hook_deny "Shell rewrite blocked: an inline snippet must not rewrite tracked file '$candidate'. Use the Edit or Write tool."
    fi
  done <<<"$candidates"
done
hook_allow
