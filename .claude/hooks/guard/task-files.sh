#!/usr/bin/env bash
# A tripwire for shell writes to a task's records: an existing `~/.agent/tasks/<task>/SPEC.md` or `.task-id`, its
# PROGRESS.md (whose gate-stamped transitions are the recorded status), and a review's `*.expect`,
# `*.provenance.json` and `*.out.md`. It refuses a command whose literal target is one of them: an output redirection
# (`>`, `>>`, `>|`, `&>`), `tee`, `dd of=`, a `truncate` operand, the destination of `install` and `ln`, both ends of
# `mv`, a `sed -i`, `perl -i`, `ruby -i` or `awk -i inplace` file, or a Python snippet's write target
# (`lib/py_write_targets.py`; a snippet it cannot resolve counts every quoted literal). A `cp`, `mv` or `rsync`
# destination anywhere inside a task directory is refused whatever its name, so a whole task folder is never copied
# over another, and so is an `rm`, `unlink` or `find -delete` of a protected file, a task directory or the tasks root.
# Inline Python that imports the task modules (`task_state`, `task_progress`, `task_gates`, `task_record`) while
# the command or its cwd involves the tasks root is refused as a write. The path is decided by
# `lib/spec_guard.py --shell` (realpath, `$HOME` read as the hook's HOME, names compared case-insensitively); a SPEC.md
# or `.task-id` not there yet passes only as a new task's first write. Reads, and the tools that write these files
# from their own processes (`crew-task.py`, `crew-review-findings.py`, `capture`), are never refused.
# This is a tripwire for accidental and literal writes, not a lock: a path in a variable, `eval` of built text, an
# encoded command or a script written now and run later is not seen (docs/hooks.md "Status integrity").
# Without shfmt the awk normaliser reads the command, with the same coverage.
set -euo pipefail
HOOK_NAME=task-files
# shellcheck source=lib/hook.sh
. "$(dirname "$0")/../lib/hook.sh"
hook_input
hook_event
cmd=$(hook_field command)
[ -n "$cmd" ] || hook_allow
TASKS_ROOT=$HOME/.agent/tasks
# True when $1 names a protected file anywhere in it, compared case-insensitively.
names_one() {
  local found=1
  shopt -s nocasematch
  case "$1" in *spec.md* | *.task-id* | *progress.md* | *.expect* | *.provenance.json* | *.out.md*) found=0 ;; esac
  shopt -u nocasematch
  return "$found"
}
# True when the command names `~/.agent` (the tasks root or a directory above it) or runs inside the tasks root.
involves_root() {
  case "$cmd" in *.agent*) return 0 ;; esac
  case "$HOOK_CWD/" in "$TASKS_ROOT"/*) return 0 ;; esac
  return 1
}
# Cheap exit: a command that names no protected file and does not involve the tasks root.
involves_root || names_one "$cmd" || hook_allow

CANDS=()
# Keep a literal write target whose name is a protected one (kind `w`), with the directory it is relative to.
want() {
  if names_one "${2##*/}"; then CANDS+=(w "$1" "$2"); fi
}
# Keep a copy destination (kind `d`): refused anywhere inside a task directory, whatever its name.
dest() { CANDS+=(d "$1" "$2"); }
# Keep a removal (kind `r`): refused for a protected file, a task directory, or the tasks root and above.
gone() { CANDS+=(r "$1" "$2"); }
# Every operand of the loaded segment (its words after the command, options left out); `--` ends the options, and
# each option named in $1 (a `|`-separated list) takes the next word as its value.
operands() {
  local j=1 only=0 valued="|${1:-}|"
  OPS=()
  while [ "$j" -lt "${#SEG_WORDS[@]}" ]; do
    case "$only${SEG_WORDS[$j]}" in
      0--) only=1 ;;
      0-?*) case "$valued" in *"|${SEG_WORDS[$j]}|"*) j=$((j + 1)) ;; esac ;;
      *) [ -z "${SEG_WORDS[$j]}" ] || OPS+=("${SEG_WORDS[$j]}") ;;
    esac
    j=$((j + 1))
  done
}
# The destination of a copy-like command (`-t DIR`, else the last operand) and what each source becomes when it is a
# directory, as kind $2 (`dest` or `want`); `mv` also removes its sources. $1 lists the options that take a value.
copies() {
  local target="" j=1 add=$2 word
  while [ "$j" -lt "${#SEG_WORDS[@]}" ]; do
    case "${SEG_WORDS[$j]}" in
      -t) target=${SEG_WORDS[$((j + 1))]:-} ;;
      --target-directory=*) target=${SEG_WORDS[$j]#*=} ;;
    esac
    j=$((j + 1))
  done
  operands "$1"
  [ "${#OPS[@]}" -gt 0 ] || return 0
  if [ -z "$target" ]; then
    target=${OPS[$((${#OPS[@]} - 1))]}
    unset "OPS[$((${#OPS[@]} - 1))]"
  fi
  "$add" "$SEG_DIR" "$target"
  word=${target//\$\{HOME\}/$HOME}
  hook_path "${word//\$HOME/$HOME}" "$SEG_DIR"
  for word in ${OPS[@]+"${OPS[@]}"}; do
    [ ! -d "$HOOK_PATH" ] || "$add" "$SEG_DIR" "$target/$(basename -- "$word")"
    [ "$base" != mv ] || want "$SEG_DIR" "$word"
  done
}
# True when the loaded segment edits files in place: sed's `-i`, BSD's `-I` and `--in-place`, bundled or not; perl's
# and ruby's `-i` (`-pi.bak`), never perl's `-I` include; awk's `-i inplace`.
in_place() {
  local flag='^-[A-Za-z]*[iI]|^--in-place' word last=""
  case "$base" in perl | ruby) flag='^-[0-9a-hj-zA-HJ-Z]*i' ;; awk | gawk) flag='^-iinplace|^--include=inplace' ;; esac
  for word in "${SEG_WORDS[@]:1}"; do
    if [[ $word =~ $flag ]]; then return 0; fi
    case "$base:$last:$word" in awk:-i:inplace | gawk:-i:inplace | awk:--include:inplace | gawk:--include:inplace) return 0 ;; esac
    last=$word
  done
  return 1
}
TASK_MODULES='(^|[^A-Za-z0-9_])(import|from)[[:space:]]+[^#]*(task_state|task_progress|task_gates|task_record)([^A-Za-z0-9_]|$)'

hook_segments "$cmd"
k=0
while [ "$k" -lt "${#HOOK_REDIRS[@]}" ]; do
  hook_redir "$k"
  want "$REDIR_DIR" "$REDIR_PATH"
  k=$((k + 1))
done
i=0
while [ "$i" -lt "${#HOOK_SEGS[@]}" ]; do
  hook_seg "$i"
  i=$((i + 1))
  base=${SEG_WORDS[0]##*/}
  case "$base" in
    tee)
      operands
      for word in ${OPS[@]+"${OPS[@]}"}; do want "$SEG_DIR" "$word"; done ;;
    dd)
      for word in "${SEG_WORDS[@]:1}"; do
        case "$word" in of=*) want "$SEG_DIR" "${word#of=}" ;; esac
      done ;;
    truncate)
      operands "-s|-r|--size|--reference"
      for word in ${OPS[@]+"${OPS[@]}"}; do want "$SEG_DIR" "$word"; done ;;
    cp | mv) copies "-S|--suffix" dest ;;
    rsync) copies "-e|--rsh|--exclude|--include|--filter|-f|--files-from|--exclude-from|--include-from" dest ;;
    install) copies "-m|--mode|-o|--owner|-g|--group|-S|--suffix" want ;;
    ln) copies "-S|--suffix" want ;;
    rm | unlink)
      operands
      for word in ${OPS[@]+"${OPS[@]}"}; do gone "$SEG_DIR" "$word"; done ;;
    find)
      # `find PATH... -delete`: each starting path, the words before the first option or expression.
      case " ${SEG_WORDS[*]} " in *" -delete "*) ;; *) continue ;; esac
      j=1
      while [ "$j" -lt "${#SEG_WORDS[@]}" ]; do
        case "${SEG_WORDS[$j]}" in -* | "(" | "!") break ;; esac
        gone "$SEG_DIR" "${SEG_WORDS[$j]}"
        j=$((j + 1))
      done ;;
    sed | gsed | perl | ruby | awk | gawk)
      in_place || continue
      operands "-e|-f|-E|-v"
      for word in ${OPS[@]+"${OPS[@]}"}; do want "$SEG_DIR" "$word"; done ;;
    python | python[0-9]*)
      snippet=$SEG_BODY
      j=1
      while [ "$j" -lt "${#SEG_WORDS[@]}" ]; do
        case "${SEG_WORDS[$j]}" in -c | -[A-Za-z]*c) snippet+=$'\n'"${SEG_WORDS[$((j + 1))]:-}" ;; esac
        j=$((j + 1))
      done
      if involves_root && grep -Eq -- "$TASK_MODULES" <<<"$snippet"; then
        hook_deny "Task file guard: this shell command runs inline Python that imports the task modules next to the tasks root, which writes task records outside crew-task.py. Run the crew-task.py command instead."
      fi
      names_one "$snippet" || continue
      # A snippet the parser cannot resolve (exit 3) counts every quoted literal.
      targets=$(python3 -I "$HOOK_LIB/py_write_targets.py" <<<"$snippet" 2>/dev/null) \
        || targets=$(grep -oE "\"[^\"]+\"|'[^']+'" <<<"$snippet" | sed -e 's/^.//' -e 's/.$//') || targets=""  # crew-lint: allow-swallow
      while IFS= read -r word; do
        [ -z "$word" ] || want "$SEG_DIR" "$word"
      done <<<"$targets" ;;
  esac
done
[ "${#CANDS[@]}" -gt 0 ] || hook_allow

verdict=$(printf '%s\0' "${CANDS[@]}" | python3 -I "$HOOK_LIB/spec_guard.py" --shell "$TASKS_ROOT" 2>/dev/null) \
  || hook_fail "cannot check the task paths this command writes (lib/spec_guard.py failed)"
case "$verdict" in
  "deny "*) hook_deny "${verdict#deny }" ;;
esac
hook_allow
