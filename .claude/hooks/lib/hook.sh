#!/usr/bin/env bash
# The one hook contract, shared by every hook under `.claude/hooks/`.
#
# One mechanism per run, never both:
#   block         Claude `PreToolUse`: exit 2, the reason on stderr, nothing on stdout.
#                 Cursor `preToolUse` / `beforeShellExecution`: one JSON deny on stdout, exit 0.
#   no objection  exit 0 and print nothing on either stream, so the harness's own permission flow
#                 decides. An explicit allow would skip interactive approval, so none is emitted.
#   cannot judge  one line on stderr and no objection. A hook that sets `HOOK_FAIL_CLOSED=1` exits 2
#                 instead while `HOOK_FAIL_BLOCKS` (default: HOOK_FAIL_CLOSED) is 1; the same rule
#                 carries `onFailure: "block"` in `.claude/settings.json` and `failClosed: true` in
#                 `.cursor/hooks.template.json`, so a crash blocks too. An off switch (hook_off)
#                 turns that exit 2 into no objection as well.
#
# Usage: set HOOK_NAME, source this file, then call hook_input, hook_event, hook_field NAME, and
# finish with hook_deny MESSAGE or hook_allow. A shell guard reads the command through the
# normaliser below (hook_segments, hook_seg, hook_git) rather than matching the raw text.
# Compatible with bash 3.2 (macOS /bin/bash): no associative arrays, namerefs or mapfile.
# shellcheck shell=bash

hook_fail() {
  printf '%s: %s\n' "${HOOK_NAME:-hook}" "$1" >&2
  if [ "${HOOK_FAIL_BLOCKS:-${HOOK_FAIL_CLOSED:-0}}" = 1 ] && ! hook_off; then exit 2; fi
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

# Read stdin once, then split the envelope in one parser call. No input at all counts as `{}`.
# jq's own diagnostics are captured, not printed: the contract is one stderr line per failure. The
# shape is guessed from the raw text first, so a failure before the parse still answers Cursor.
hook_input() {
  HOOK_INPUT=$(cat) || hook_fail "cannot read hook input"
  case "$HOOK_INPUT" in *'"PreToolUse"'*) HOOK_SHAPE=claude ;; *) HOOK_SHAPE=cursor ;; esac
  command -v jq >/dev/null 2>&1 || hook_fail "jq is not installed; cannot read hook input"
  [ -n "$HOOK_INPUT" ] || HOOK_INPUT='{}'
  local parsed
  parsed=$(printf '%s' "$HOOK_INPUT" | jq -er '[(.hook_event_name // ""), (.cwd // "")] | @tsv' 2>/dev/null) \
    || hook_fail "hook input is not valid JSON"
  meta=$parsed
  HOOK_EVENT=${meta%%$'\t'*}
  HOOK_CWD=${meta#*$'\t'}
}

# Normalize the three event spellings into one shape, and anchor cwd to something that exists.
hook_event() {
  case "$HOOK_EVENT" in
    PreToolUse) HOOK_SHAPE=claude ;;
    preToolUse | beforeShellExecution) HOOK_SHAPE=cursor ;;
    *) hook_fail "unsupported hook_event_name: ${HOOK_EVENT:-missing}" ;;
  esac
  if [ -z "$HOOK_CWD" ] || [ ! -d "$HOOK_CWD" ]; then HOOK_CWD=$PWD; fi
}

# One `tool_input` field across both harness shapes; `beforeShellExecution` carries it at the top.
hook_field() {
  printf '%s' "$HOOK_INPUT" | jq -r --arg k "$1" \
    'if .hook_event_name == "beforeShellExecution" then (.command // "")
     else (.tool_input[$k] // .[$k] // "") end' \
    || hook_fail "cannot read $1 from hook input"
}

# A denial names both off switches on its one line, so whoever is blocked learns them from it.
hook_deny() {
  local switch message
  switch=EL_CAPITAN_GUARD_$(printf '%s' "${HOOK_NAME:-hook}" | tr 'a-z-' 'A-Z_')
  if hook_off; then hook_allow; fi
  message="$1 (Off switch, set in the harness environment: $switch=off for this guard, EL_CAPITAN_GUARDS=off for all.)"
  if [ "$HOOK_SHAPE" = claude ]; then
    printf '%s\n' "$message" >&2
    exit 2
  fi
  jq -n --arg m "$message" '{permission:"deny",user_message:$m,agent_message:$m}' \
    || hook_fail "cannot emit the denial"
  exit 0
}

# No objection is silence: exit 0 with nothing on either stream, so the harness's own permission flow
# decides. An explicit allow would skip interactive approval, so none is emitted.
#
# One measured exception: Cursor reads *no output at all* from a hook registered `failClosed: true` as
# a crash and blocks the command, so silence there is not a decline. The only such hook is
# `guard/credentials.sh`, and it answers with `{}` — an empty decision object, which carries no
# permission at all, so it adds nothing to the harness's own flow and skips no approval.
hook_allow() {
  if [ "${HOOK_FAIL_CLOSED:-0}" = 1 ] && [ "${HOOK_SHAPE:-}" = cursor ]; then printf '{}\n'; fi
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
#     redirections and their targets are dropped, comments are skipped;
#   - each segment carries the directory it runs in: the hook's cwd, moved by every earlier `cd`
#     whose target holds no `$` or backtick (one the guard cannot resolve leaves it unchanged);
#   - heredoc bodies and here-strings are data of the segment that reads them, never commands,
#     except when that segment is a shell with no `-c` and no script argument: then the body is its
#     script and is parsed as a payload. So is the text piped into such a shell by `echo`, `printf`
#     or a `cat` of a heredoc; any other producer (`cat file | sh`, `curl ... | bash`) cannot be
#     read, and hook_segments denies it unless the caller set HOOK_SHELL_STDIN=allow;
#   - past MAX_PAYLOADS nested payloads the command is too complex to judge: hook_segments denies.
# `hook_seg N` loads segment N into SEG_DIR, SEG_BODY (heredoc and here-string text), SEG_QUOTED (one
# `1` or `0` per word: whether any of it was quoted) and SEG_WORDS.
HOOK_US=$'\037'
# Each nested payload (`$(...)`, `sh -c`, `eval`, a shell's stdin) is scanned again: the cap bounds
# the work one command can cause, and past it the command is denied rather than partly read.
HOOK_MAX_PAYLOADS=64
hook_segments() {
  local out rec
  HOOK_SEGS=()
  # Checked first: piping into a missing awk can also print `printf: write error` on stderr.
  command -v awk >/dev/null 2>&1 || hook_fail "awk is not installed; cannot parse the shell command"
  [ -n "${HOOK_AWK:-}" ] || read -r -d '' HOOK_AWK <<'AWK' || true
function resolve(p, dir) {
  if (p == "" || p == "-") return dir
  if (p == "~") return home
  if (substr(p, 1, 2) == "~/") return home substr(p, 2)
  if (substr(p, 1, 1) == "/") return p
  return dir "/" p
}
# Past MAX_PAYLOADS (HOOK_MAX_PAYLOADS) the END block reports an overflow, so nothing is dropped silently.
function enqueue(s, d) { if (QN >= MAX_PAYLOADS) { OVERFLOW = 1; return } QN++; Q[QN] = s; QD[QN] = d }
function pushword() {
  if (INW) {
    if (REDIR == 2) HSD = HSD W "\n"
    else if (REDIR == 3) { PN++; PD[PN] = W; PS[PN] = HSTRIP; PO[PN] = 0 }
    else if (REDIR == 0) { WSTR = (NW ? WSTR US : "") W; QSTR = QSTR (WQ ? 1 : 0); NW++ }
    REDIR = 0
  }
  W = ""; INW = 0; WQ = 0
}
# Options of a wrapper that take the next word as their value.
function optval(w, o) {
  if (w == "nice") return o == "-n"
  if (w == "sudo") return o ~ /^-[ugCDhpRrtTU]$/
  if (w == "env") return o ~ /^-[uCS]$/
  if (w == "timeout") return o ~ /^-[sk]$/
  if (w == "stdbuf") return o ~ /^-[ioe]$/
  return 0
}
# A shell with `-c` runs its payload; with no `-c` and no script argument (or with `-s`) it runs stdin.
function shellin(a, i, n, idx,    j, s) {
  s = 0
  for (j = i + 1; j <= n; j++) {
    if (a[j] ~ /^-[A-Za-z]*c[A-Za-z]*$/) { if (j < n) enqueue(a[j + 1], DIR); return }
    if (a[j] ~ /^[-+][oO]$/ || a[j] ~ /^--(rcfile|init-file)$/) { j++; continue }
    if (a[j] == "--") { if (j < n && !s) return; break }
    if (a[j] ~ /^[-+]/) { if (a[j] ~ /^-[A-Za-z]*s/) s = 1; continue }
    if (!s) return
    break
  }
  SHIN[idx] = 1
}
# The literal text `echo` or `printf` writes, with `\n` read as a newline.
function lit(a, i, n, base,    j, t, k) {
  j = i + 1; t = ""; k = 0
  if (base == "echo") while (j <= n && a[j] ~ /^-[neE]+$/) j++
  for (; j <= n; j++) t = t (k++ ? " " : "") a[j]
  gsub(/\\n/, "\n", t)
  return t
}
function store(   a, n, i, j, out, base, idx, w) {
  if (NW == 0) return 0
  n = split(WSTR, a, US); i = 1
  while (i <= n) {
    if (a[i] ~ /^[A-Za-z_][A-Za-z0-9_]*=/) { i++; continue }
    if (a[i] !~ /^(env|command|exec|nohup|time|timeout|stdbuf|builtin|sudo|nice|then|do|else|if|elif|while|until|!|\{|\})$/) break
    w = a[i]; i++
    while (i <= n && a[i] ~ /^-/) { if (optval(w, a[i])) i++; i++ }
    if (w == "timeout" && i <= n) i++
  }
  if (i > n) return 0
  out = a[i]; for (j = i + 1; j <= n; j++) out = out US a[j]
  NSEG++; SD[NSEG] = DIR; SW[NSEG] = out; SB[NSEG] = HSD; SQ[NSEG] = substr(QSTR, i); idx = NSEG
  PIPE[idx] = PIPEIN; PIPEIN = 0
  base = a[i]; sub(/.*\//, "", base)
  if (base == "cd") {
    j = i + 1; while (j <= n && a[j] ~ /^-./) j++
    if (j > n || a[j] !~ /[$`]/) DIR = resolve(j <= n ? a[j] : "~", DIR)
  }
  if (base ~ /^(sh|bash|zsh|dash|ksh)$/) shellin(a, i, n, idx)
  if (base == "echo" || base == "printf") LIT[idx] = lit(a, i, n, base)
  if (base == "cat") { CAT[idx] = 1; for (j = i + 1; j <= n; j++) if (a[j] !~ /^-/) CAT[idx] = 0 }
  if (base == "eval" && i < n) { out = a[i + 1]; for (j = i + 2; j <= n; j++) out = out " " a[j]; enqueue(out, DIR) }
  return idx
}
function endseg(   k, idx) {
  pushword(); idx = store(); LAST = idx
  for (k = 1; k <= PN; k++) if (PO[k] == 0) PO[k] = idx ? idx : -1
  WSTR = ""; QSTR = ""; NW = 0; HSD = ""; REDIR = 0
}
# After a scan, every shell that runs stdin gets that text as a payload: its own heredoc or
# here-string, or what an `echo`, `printf` or heredoc `cat` pipes into it. Any other producer is opaque.
function stdins(first,    k, p) {
  for (k = first; k <= NSEG; k++) {
    if (!SHIN[k]) continue
    if (SB[k] != "") { enqueue(SB[k], SD[k]); continue }
    p = PIPE[k]
    while (p > 0 && CAT[p] && SB[p] == "") p = PIPE[p]
    if (p > 0 && (p in LIT)) enqueue(LIT[p], SD[k])
    else if (p > 0 && CAT[p]) enqueue(SB[p], SD[k])
    else if (p != 0) OPAQUE = 1
  }
}
function closing(s, i, n,    c, depth, j) {
  depth = 1
  while (i <= n) {
    c = substr(s, i, 1)
    if (c == "\\") { i += 2; continue }
    if (c == "'") { j = index(substr(s, i + 1), "'"); if (j == 0) return n + 1; i += j + 1; continue }
    if (c == "(") depth++
    else if (c == ")") { depth--; if (depth == 0) return i }
    i++
  }
  return n + 1
}
function hexval(d) { return index("0123456789abcdef", tolower(d)) - 1 }
function ansi(s, i, n,    c, nx, v) {
  while (i <= n) {
    c = substr(s, i, 1)
    if (c == "'") return i + 1
    if (c != "\\") { W = W c; i++; continue }
    nx = substr(s, i + 1, 1); i += 2
    if (nx == "n") W = W "\n"
    else if (nx == "t") W = W "\t"
    else if (nx == "x" && hexval(substr(s, i, 1)) >= 0) {
      v = hexval(substr(s, i, 1)); i++
      if (hexval(substr(s, i, 1)) >= 0) { v = v * 16 + hexval(substr(s, i, 1)); i++ }
      W = W sprintf("%c", v)
    } else if (nx ~ /[0-7]/) {
      v = nx + 0; while (substr(s, i, 1) ~ /[0-7]/ && v < 32) { v = v * 8 + substr(s, i, 1); i++ }
      W = W sprintf("%c", v)
    } else W = W nx
  }
  return i
}
function subst(s, i, n, open,    j) {
  if (open == "`") { j = index(substr(s, i + 1), "`"); j = j ? i + j : n + 1; enqueue(substr(s, i + 1, j - i - 1), DIR) }
  else { j = closing(s, i + 2, n); enqueue(substr(s, i + 2, j - i - 2), DIR) }
  W = W substr(s, i, j - i + 1); INW = 1
  return j + 1
}
function dquote(s, i, n,    c, nx) {
  while (i <= n) {
    c = substr(s, i, 1)
    if (c == "\"") return i + 1
    if (c == "\\") {
      nx = substr(s, i + 1, 1)
      if (nx == "\n") { i += 2; continue }
      if (nx == "$" || nx == "`" || nx == "\"" || nx == "\\") { W = W nx; i += 2; continue }
    }
    if (c == "$" && substr(s, i + 1, 1) == "(") { i = subst(s, i, n, "("); continue }
    if (c == "`") { i = subst(s, i, n, "`"); continue }
    W = W c; i++
  }
  return i
}
function heredocs(s, i, n,    k, line, t, e, body) {
  for (k = 1; k <= PN; k++) {
    body = ""
    while (i <= n) {
      e = index(substr(s, i), "\n")
      if (e == 0) { line = substr(s, i); i = n + 1 } else { line = substr(s, i, e - 1); i += e }
      t = line; if (PS[k]) sub(/^\t+/, "", t)
      if (t == PD[k]) break
      body = body line "\n"
    }
    if (PO[k] > 0) SB[PO[k]] = SB[PO[k]] body
  }
  PN = 0
  return i
}
function redirect(s, i, n, c) {
  if (INW && W ~ /^[0-9]+$/) { W = ""; INW = 0; WQ = 0 } else pushword()
  if (c == "<" && substr(s, i + 1, 2) == "<<") { REDIR = 2; return i + 3 }
  if (c == "<" && substr(s, i + 1, 1) == "<") {
    i += 2; HSTRIP = 0; if (substr(s, i, 1) == "-") { HSTRIP = 1; i++ }
    REDIR = 3; return i
  }
  i++; if (substr(s, i, 1) ~ /[>|]/) i++
  if (substr(s, i, 1) == "&") { i++; while (i <= n && substr(s, i, 1) ~ /[0-9-]/) i++; return i }
  REDIR = 1; return i
}
function scan(s, dir,    n, i, c, j, first) {
  n = length(s); i = 1; DIR = dir; W = ""; INW = 0; WQ = 0; WSTR = ""; QSTR = ""; NW = 0; REDIR = 0; HSD = ""; PN = 0
  PIPEIN = 0; first = NSEG + 1
  while (i <= n) {
    c = substr(s, i, 1)
    if (c == "'") { j = index(substr(s, i + 1), "'"); if (j == 0) j = n - i + 1; W = W substr(s, i + 1, j - 1); INW = 1; WQ = 1; i += j + 1 }
    else if (c == "\"") { INW = 1; WQ = 1; i = dquote(s, i + 1, n) }
    else if (c == "$" && substr(s, i + 1, 1) == "'") { INW = 1; WQ = 1; i = ansi(s, i + 2, n) }
    else if (c == "$" && substr(s, i + 1, 1) == "(") i = subst(s, i, n, "(")
    else if (c == "`") i = subst(s, i, n, "`")
    else if (c == "\\") { if (substr(s, i + 1, 1) != "\n") { W = W substr(s, i + 1, 1); INW = 1 } i += 2 }
    else if (c == "#" && !INW) { while (i <= n && substr(s, i, 1) != "\n") i++ }
    else if (c == " " || c == "\t") { pushword(); i++ }
    else if (c == "\n") { endseg(); i = heredocs(s, i + 1, n) }
    else if (c == "&" && substr(s, i + 1, 1) == ">") { pushword(); REDIR = 1; i += 2; if (substr(s, i, 1) == ">") i++ }
    else if (c == "|" && substr(s, i + 1, 1) != "|") {
      endseg(); PIPEIN = LAST ? LAST : -1; i++; if (substr(s, i, 1) == "&") i++
    }
    else if (c == "|") { endseg(); PIPEIN = 0; i += 2 }
    else if (c == ";" || c == "&" || c == "(" || c == ")") { endseg(); i++ }
    else if (c == ">" || c == "<") i = redirect(s, i, n, c)
    else { W = W c; INW = 1; i++ }
  }
  endseg()
  stdins(first)
}
BEGIN { US = sprintf("%c", 31); RS_ = sprintf("%c", 30); MAX_PAYLOADS = max + 0 }
{ text = (NR == 1) ? $0 : text "\n" $0 }
END {
  QN = 1; Q[1] = text; QD[1] = cwd
  for (qi = 1; qi <= QN; qi++) scan(Q[qi], QD[qi])
  for (k = 1; k <= NSEG; k++) {
    gsub(/\n/, RS_, SW[k]); gsub(/\n/, RS_, SB[k]); print SD[k] US SB[k] US SQ[k] US SW[k]
  }
  if (OVERFLOW) print US "overflow"
  if (OPAQUE) print US "stdin"
}
AWK
  out=$(printf '%s\n' "$1" | awk -v cwd="$HOOK_CWD" -v home="${HOME:-}" -v max="$HOOK_MAX_PAYLOADS" "$HOOK_AWK" 2>/dev/null) \
    || hook_fail "cannot parse the shell command"
  while IFS= read -r rec; do
    case "$rec" in
      "") ;;
      "${HOOK_US}overflow")
        hook_deny "Blocked: command too complex for the guard (more than $HOOK_MAX_PAYLOADS nested commands to check). Split it into smaller commands." ;;
      "${HOOK_US}stdin")
        [ "${HOOK_SHELL_STDIN:-deny}" = allow ] \
          || hook_deny "Blocked: a shell reads its script from a pipe the guard cannot read, so the commands it runs go unchecked. Run the script as a file (\`bash FILE\`) or pass it with \`bash -c\`." ;;
      *) HOOK_SEGS[${#HOOK_SEGS[@]}]=$rec ;;
    esac
  done <<<"$out"
}

# IFS is set on `read` alone: bash before 4.4 also splits a here-string with the current IFS.
hook_seg() {
  IFS=$HOOK_US read -r -a HOOK_PARTS <<<"${HOOK_SEGS[$1]}"
  [ "${#HOOK_PARTS[@]}" -gt 3 ] || HOOK_PARTS[3]=""
  SEG_DIR=${HOOK_PARTS[0]}
  SEG_BODY=${HOOK_PARTS[1]:-}
  SEG_BODY=${SEG_BODY//$'\036'/$'\n'}
  SEG_QUOTED=${HOOK_PARTS[2]:-}
  SEG_WORDS=("${HOOK_PARTS[@]:3}")
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
