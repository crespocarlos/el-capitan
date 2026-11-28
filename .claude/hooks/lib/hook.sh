#!/usr/bin/env bash
# The one rule contract, shared by every hook rule under `.claude/hooks/` (each listed in `contract.json`).
#
# A rule reads one normalised event on stdin, which `crew-hook.py` built from the harness's payload (`event`,
# `harness`, `deny_rules`, `cwd`, `session`, `tool`, `input`, ...), and answers on stdout in no harness's format; the
# harness's adapter encodes the answer. One mechanism per run, never both:
#   deny          one JSON object `{"deny": MESSAGE}` (hook_deny), exit 0.
#   no objection  exit 0 and nothing on stdout (hook_allow), so the harness's own permission flow decides.
#   context       plain text on stdout; a stop's request to go on is `{"followup": TEXT}`.
#   cannot judge  one line on stderr and no objection.
# A denial is logged to ~/.agent/state/guard.log: time, rule, harness and a hash of what was denied, never its text.
#
# Usage: set HOOK_NAME, source this file, then call hook_input and hook_field NAME, and finish with hook_deny
# MESSAGE or hook_allow. A shell guard reads the command through the normaliser below (hook_segments, hook_seg,
# hook_git) rather than matching the raw text.
# Compatible with bash 3.2 (macOS /bin/bash): no associative arrays, namerefs or mapfile.
# shellcheck shell=bash

hook_fail() {
  printf '%s: %s\n' "${HOOK_NAME:-hook}" "$1" >&2
  hook_allow
}

# The off switches, read from the hook's own environment (the harness's, never the command's):
# `EL_CAPITAN_GUARDS=off` turns every blocking hook into no objection, and
# `EL_CAPITAN_GUARD_<NAME>=off` (HOOK_NAME upper-cased, `-` as `_`) turns off that one.
hook_off() {
  local switch
  switch=EL_CAPITAN_GUARD_$(printf '%s' "${HOOK_NAME:-hook}" | tr 'a-z-' 'A-Z_')
  [ "${EL_CAPITAN_GUARDS:-}" = off ] || [ "${!switch:-}" = off ]
}

# Read the event once and split it in one parser call; no input at all counts as `{}`. HOOK_DENY_RULES is 1 only when
# the harness holds the demoted rules with deny rules of its own. HOOK_CWD is anchored to a directory that exists.
hook_input() {
  HOOK_INPUT=$(cat) || hook_fail "cannot read hook input"
  command -v jq >/dev/null 2>&1 || hook_fail "jq is not installed; cannot read hook input"
  [ -n "$HOOK_INPUT" ] || HOOK_INPUT='{}'
  local parsed
  parsed=$(printf '%s' "$HOOK_INPUT" | jq -er '[(.event // ""), (.harness // ""), (if .deny_rules == true then 1 else 0 end), (.cwd // "")] | @tsv' 2>/dev/null) \
    || hook_fail "hook input is not valid JSON"
  IFS=$'\t' read -r HOOK_EVENT HOOK_HARNESS HOOK_DENY_RULES HOOK_CWD <<<"$parsed"
  if [ -z "$HOOK_CWD" ] || [ ! -d "$HOOK_CWD" ]; then HOOK_CWD=$PWD; fi
}

# One field of the tool's input (`command`, `file_path`, ...).
hook_field() {
  printf '%s' "$HOOK_INPUT" | jq -r --arg k "$1" '(.input // {})[$k] // ""' || hook_fail "cannot read $1 from hook input"
}

# A denial names both off switches on its one line, so whoever is blocked learns them from it.
hook_deny() {
  local switch message
  switch=EL_CAPITAN_GUARD_$(printf '%s' "${HOOK_NAME:-hook}" | tr 'a-z-' 'A-Z_')
  if hook_off; then hook_allow; fi
  message="$1 (Off switch, set in the harness environment: $switch=off for this guard, EL_CAPITAN_GUARDS=off for all.)"
  { mkdir -p "$HOME/.agent/state" && printf '%s\t%s\t%s\t%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "${HOOK_NAME:-hook}" \
    "${HOOK_HARNESS:-unknown}" "$(printf '%s' "${HOOK_SUBJECT:-}" | cksum | cut -d' ' -f1)" \
    >>"$HOME/.agent/state/guard.log"; } 2>/dev/null || true
  jq -cn --arg m "$message" '{deny: $m}' || hook_fail "cannot emit the denial"
  exit 0
}

hook_allow() {
  exit 0
}

# The command normaliser. `hook_segments CMD` splits a shell command into simple commands the way
# the shell would run them, and stores one record per segment in HOOK_SEGS:
#   - quotes are removed and their content kept (`git "reset" --hard` reads as `git reset --hard`),
#     backslash escapes and `$'...'` are decoded, and a quoted `;` or `|` stays inside its word;
#   - segments split on `;`, `&&`, `||`, `|`, `&`, newlines and parentheses; `$(...)`, backticks,
#     `sh|bash|zsh -c PAYLOAD` and `eval` bodies are parsed again as segments of their own;
#   - leading `VAR=value` assignments and wrappers (`env`, `command`, `sudo`, `timeout`, `if`, ...)
#     are dropped with their options and option values (`nice -n 5`, `sudo -u me`, `timeout 10`),
#     redirections and their targets are dropped from the words (an output redirection's target is kept
#     apart, in HOOK_REDIRS, read with hook_redir), comments are skipped;
#   - each segment carries the directory it runs in: the hook's cwd, moved by every earlier `cd`
#     whose target holds no `$` or backtick (one the guard cannot resolve leaves it unchanged);
#   - heredoc bodies and here-strings are data of the segment that reads them, never commands,
#     except when that segment is a shell with no `-c` and no script argument: then the body is its
#     script and is parsed as a payload. So is the text piped into such a shell by `echo`, `printf`
#     or a `cat` of a heredoc; what any other producer (`cat file | sh`) pipes is not read;
#   - past MAX_PAYLOADS nested payloads the command is too complex to judge: HOOK_OVERFLOW is 1.
# shfmt (the venv's, from the pinned `shfmt-py` wheel, when none is on PATH) parses the command into a
# bash syntax tree (`shfmt --to-json`) and lib/segments.jq derives the records from it; each string
# payload (`sh -c`, `eval`, a shell's stdin) goes through shfmt again. A command shfmt or jq cannot read,
# or no shfmt at all, sets HOOK_UNPARSED to the reason; one nesting too deeply sets HOOK_OVERFLOW.
# `hook_seg N` loads segment N into SEG_DIR, SEG_BODY (heredoc and here-string text), SEG_QUOTED (one
# `1` or `0` per word: whether any of it was quoted) and SEG_WORDS.
HOOK_US=$'\037'
# Each nested payload (`$(...)`, `sh -c`, `eval`, a shell's stdin) is scanned again: the cap bounds
# the work one command can cause, and past it the command is denied rather than partly read.
HOOK_MAX_PAYLOADS=64
HOOK_LIB=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)

# shfmt's JSON grows with nesting depth times size (a 27 KB pipeline of 3,900 stages prints 1.6 GB),
# so a command with more than HOOK_SHFMT_NESTING characters that can nest (`|`, `&`, `(`, `{`, a
# backtick) is too complex to judge; a long flat command (a big heredoc) is parsed.
HOOK_SHFMT_NESTING=64
HOOK_SHFMT=$(command -v shfmt || echo "${HOME:-}/.agent/venv/bin/shfmt")

# Every record field is escaped with \035 as the escape byte (`\035e` for \035, `\035u` for US, `\035r`
# for RS) and a newline is RS, so no byte inside a field can split it. `hook_unesc TEXT [nl]` undoes the
# escapes into HOOK_TEXT; with `nl`, RS is read back as a newline first.
HOOK_ESC=$'\035'
hook_unesc() {
  HOOK_TEXT=$1
  if [ "${2:-}" = nl ]; then HOOK_TEXT=${HOOK_TEXT//$'\036'/$'\n'}; fi
  case "$HOOK_TEXT" in *"$HOOK_ESC"*) ;; *) return 0 ;; esac
  HOOK_TEXT=${HOOK_TEXT//"${HOOK_ESC}r"/$'\036'}
  HOOK_TEXT=${HOOK_TEXT//"${HOOK_ESC}u"/$HOOK_US}
  HOOK_TEXT=${HOOK_TEXT//"${HOOK_ESC}e"/$HOOK_ESC}
}

# The records of $1 on stdout, status 1 when shfmt or jq fails on any payload (shfmt's tree is streamed
# into jq, never held in a variable). The payload count runs across the shfmt runs.
hook_shfmt() {
  local texts=("$1") dirs=("$HOOK_CWD") k=0 qn=1 out line
  while [ "$k" -lt "${#texts[@]}" ]; do
    out=$(printf '%s' "${texts[$k]}" | "$HOOK_SHFMT" -ln=bash --to-json 2>/dev/null \
      | jq -r --rawfile src <(printf '%s' "${texts[$k]}") --arg dir "${dirs[$k]}" --arg home "${HOME:-}" \
        --argjson qn "$qn" --argjson max "$HOOK_MAX_PAYLOADS" -f "$HOOK_LIB/segments.jq" 2>/dev/null
      [ "${PIPESTATUS[*]}" = "0 0 0" ]) || return 1
    while IFS= read -r line; do
      case "$line" in
        "${HOOK_US}payload${HOOK_US}"*)
          line=${line#"${HOOK_US}payload${HOOK_US}"}
          hook_unesc "${line%%"$HOOK_US"*}" nl
          dirs[${#dirs[@]}]=$HOOK_TEXT
          hook_unesc "${line#*"$HOOK_US"}" nl
          texts[${#texts[@]}]=$HOOK_TEXT ;;
        "${HOOK_US}qn${HOOK_US}"*) qn=${line##*"$HOOK_US"} ;;
        *) printf '%s\n' "$line" ;;
      esac
    done <<<"$out"
    k=$((k + 1))
  done
}

# True when $1 is shallow enough for shfmt: the characters that can nest are counted, never parsed.
hook_shfmt_fits() {
  local nesting
  [ "${#1}" -le "$HOOK_SHFMT_NESTING" ] && return 0
  nesting=$(printf '%s' "$1" | LC_ALL=C awk '{ m += gsub(/[|&({`]/, "") } END { print m + 0 }') || return 1
  [ "$nesting" -le "$HOOK_SHFMT_NESTING" ]
}

hook_segments() {
  local out
  HOOK_SEGS=()
  HOOK_REDIRS=()
  HOOK_OVERFLOW=0
  HOOK_UNPARSED=""
  if [ ! -x "$HOOK_SHFMT" ]; then HOOK_UNPARSED="(shfmt is not installed); run install.sh"
  elif ! hook_shfmt_fits "$1"; then HOOK_OVERFLOW=1
  elif out=$(hook_shfmt "$1"); then hook_records "$out"
  else HOOK_UNPARSED="(shfmt rejected it); fix the syntax or simplify it"
  fi
}

# The records into HOOK_SEGS; past the payload cap the command is too complex to judge and
# HOOK_OVERFLOW is 1 (the shell guard denies it as its `too-complex` rule).
hook_records() {
  local rec
  HOOK_OVERFLOW=0
  while IFS= read -r rec; do
    case "$rec" in
      "") ;;
      "${HOOK_US}redir${HOOK_US}"*) HOOK_REDIRS[${#HOOK_REDIRS[@]}]=${rec#"${HOOK_US}redir${HOOK_US}"} ;;
      "${HOOK_US}overflow") HOOK_OVERFLOW=1 ;;
      *) HOOK_SEGS[${#HOOK_SEGS[@]}]=$rec ;;
    esac
  done <<<"$1"
}

# IFS is set on `read` alone: bash before 4.4 also splits a here-string with the current IFS.
hook_seg() {
  IFS=$HOOK_US read -r -a HOOK_PARTS <<<"${HOOK_SEGS[$1]}"
  [ "${#HOOK_PARTS[@]}" -gt 3 ] || HOOK_PARTS[3]=""
  hook_unesc "${HOOK_PARTS[0]}" nl
  SEG_DIR=$HOOK_TEXT
  hook_unesc "${HOOK_PARTS[1]:-}" nl
  SEG_BODY=$HOOK_TEXT
  SEG_QUOTED=${HOOK_PARTS[2]:-}
  SEG_WORDS=("${HOOK_PARTS[@]:3}")
  case "${HOOK_SEGS[$1]}" in *"$HOOK_ESC"*) ;; *) return 0 ;; esac
  local k=3
  SEG_WORDS=()
  while [ "$k" -lt "${#HOOK_PARTS[@]}" ]; do
    hook_unesc "${HOOK_PARTS[$k]}"
    SEG_WORDS[${#SEG_WORDS[@]}]=$HOOK_TEXT
    k=$((k + 1))
  done
}

# `hook_redir N` loads output redirection N (`>`, `>>`, `>|`, `&>`, `&>>` and a target word, as written) into
# REDIR_DIR (where its command runs) and REDIR_PATH.
hook_redir() {
  hook_unesc "${HOOK_REDIRS[$1]%%"$HOOK_US"*}" nl
  REDIR_DIR=$HOOK_TEXT
  hook_unesc "${HOOK_REDIRS[$1]#*"$HOOK_US"}" nl
  REDIR_PATH=$HOOK_TEXT
}

# An absolute path for $1 relative to $2, in HOOK_PATH; `~` is the hook's HOME.
hook_path() {
  case "$1" in
    "~") HOOK_PATH=${HOME:-/} ;;
    "~/"*) HOOK_PATH=${HOME:-}/${1#"~/"} ;;
    /*) HOOK_PATH=$1 ;;
    *) HOOK_PATH=$2/$1 ;;
  esac
}

# When the loaded segment runs git: GIT_SUB is the subcommand after every global option (`-C dir`,
# `-c k=v`, `--git-dir`, `--work-tree`, `--no-pager`, ...), GIT_ARGS its arguments, and GIT_TREE the
# segment's directory with each `-C` applied. Returns 1 for any other segment.
# Which word is git: the first word whose basename is `git` and that is either the command itself or
# an unquoted word, so a runner in front (`timeout 10 git`, `xargs git`, `find -exec git`, `watch`,
# `parallel`) hides nothing, while a quoted argument of another command (`grep "git" checkout`) stays
# data. The word must be followed by a subcommand; `which git` is not a git segment.
hook_git() {
  local i=0 n=${#SEG_WORDS[@]}
  while [ "$i" -lt "$n" ]; do
    if [ "${SEG_WORDS[$i]##*/}" = git ] && { [ "$i" = 0 ] || [ "${SEG_QUOTED:$i:1}" = 0 ]; }; then break; fi
    i=$((i + 1))
  done
  [ "$i" -lt "$n" ] || return 1
  i=$((i + 1))
  GIT_TREE=$SEG_DIR
  while [ "$i" -lt "$n" ]; do
    case "${SEG_WORDS[$i]}" in
      -C) i=$((i + 1)); hook_path "${SEG_WORDS[$i]:-.}" "$GIT_TREE"; GIT_TREE=$HOOK_PATH ;;
      -c | --git-dir | --work-tree | --namespace | --config-env | --super-prefix) i=$((i + 1)) ;;
      -*) ;;
      *) break ;;
    esac
    i=$((i + 1))
  done
  [ "$i" -lt "$n" ] || return 1
  GIT_SUB=${SEG_WORDS[$i]}
  GIT_ARGS=("${SEG_WORDS[@]:$((i + 1))}")
}

# When the loaded segment runs gh: GH_CMD and GH_SUB are its first two words that are not options
# (`gh pr -R o/r checkout 12` gives `pr` and `checkout`), with `-R`/`--repo` taking a value. The gh
# word is found the way hook_git finds git, so a runner in front (`xargs gh`) hides nothing.
hook_gh() {
  local i=0 n=${#SEG_WORDS[@]}
  GH_CMD="" GH_SUB=""
  while [ "$i" -lt "$n" ]; do
    if [ "${SEG_WORDS[$i]##*/}" = gh ] && { [ "$i" = 0 ] || [ "${SEG_QUOTED:$i:1}" = 0 ]; }; then break; fi
    i=$((i + 1))
  done
  [ "$i" -lt "$n" ] || return 1
  i=$((i + 1))
  while [ "$i" -lt "$n" ] && [ -z "$GH_SUB" ]; do
    case "${SEG_WORDS[$i]}" in
      -R | --repo) i=$((i + 1)) ;;
      -*) ;;
      *) if [ -z "$GH_CMD" ]; then GH_CMD=${SEG_WORDS[$i]}; else GH_SUB=${SEG_WORDS[$i]}; fi ;;
    esac
    i=$((i + 1))
  done
  [ -n "$GH_CMD" ]
}

# REPO is $1 when it is a git repository, else the hook's cwd when that is one, else empty.
hook_repo() {
  local dir
  REPO=""
  for dir in "$1" "$HOOK_CWD"; do
    if git -C "$dir" rev-parse --git-dir >/dev/null 2>&1; then REPO=$dir; return 0; fi
  done
}

# The added lines of a unified diff on stdin, without the `+` and without `+++` file headers.
hook_plus_lines() { sed -n '/^+++ /d; s/^+//p'; }

# What `git add ARGS...` would stage in $1: changed lines of tracked files, then the content of
# untracked files (skipped when $2 is `no`, which is what `git commit -a` stages, and for `-u`,
# `--update`, `-p` and `--patch`, which never stage an untracked file).
hook_git_added() {
  local dir=$1 untracked=$2 word only=0 paths=()
  shift 2
  for word in "$@"; do
    case "$only$word" in
      0--) only=1 ;;
      0--update | 0--patch | 0-[!-]*[up]* | 0-[up]*) untracked=no ;;
      0-*) ;;
      *) paths+=("$word") ;;
    esac
  done
  git -C "$dir" diff -U0 -- ${paths[@]+"${paths[@]}"} | hook_plus_lines
  [ "$untracked" = yes ] || return 0
  git -C "$dir" ls-files -z -o --exclude-standard -- ${paths[@]+"${paths[@]}"} \
    | while IFS= read -r -d '' file; do head -c 1048576 "$dir/$file"; printf '\n'; done
}

# True when an argument of the loaded git segment before `--` matches the extended regex $1.
hook_git_arg() {
  local word
  for word in ${GIT_ARGS[@]+"${GIT_ARGS[@]}"}; do
    [ "$word" != -- ] || return 1
    if [[ $word =~ $1 ]]; then return 0; fi
  done
  return 1
}
