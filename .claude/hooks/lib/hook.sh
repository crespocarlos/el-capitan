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
# Two parsers emit these records. With `shfmt` on PATH (optional, preferred) the command is parsed
# into a real bash syntax tree (`shfmt --to-json`) and lib/segments.jq derives the records from it;
# each string payload (`sh -c`, `eval`, a shell's stdin) goes through shfmt again. Without shfmt, or
# when shfmt or jq fails on any part of the command, the awk program below reads the whole command,
# so a parse failure never becomes an allow the awk path would not give.
# `hook_seg N` loads segment N into SEG_DIR, SEG_BODY (heredoc and here-string text), SEG_QUOTED (one
# `1` or `0` per word: whether any of it was quoted) and SEG_WORDS.
HOOK_US=$'\037'
# Each nested payload (`$(...)`, `sh -c`, `eval`, a shell's stdin) is scanned again: the cap bounds
# the work one command can cause, and past it the command is denied rather than partly read.
HOOK_MAX_PAYLOADS=64
HOOK_LIB=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)

# shfmt's JSON grows with nesting depth times size (a 27 KB pipeline of 3,900 stages prints 1.6 GB),
# so a command over HOOK_SHFMT_BYTES, or with more than HOOK_SHFMT_NESTING characters that can nest
# (`|`, `&`, `(`, `{`, a backtick), goes to awk instead.
HOOK_SHFMT_BYTES=16384
HOOK_SHFMT_NESTING=64

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

# The shfmt path: the records of $1 on stdout, status 1 when shfmt or jq fails on any payload (shfmt's
# tree is streamed into jq, never held in a variable). The payload count runs across the shfmt runs,
# so the cap means what it means on the awk path.
hook_shfmt() {
  local texts=("$1") dirs=("$HOOK_CWD") k=0 qn=1 out line
  while [ "$k" -lt "${#texts[@]}" ]; do
    out=$(printf '%s' "${texts[$k]}" | shfmt -ln=bash --to-json 2>/dev/null \
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

# True when $1 is small and shallow enough for the shfmt path (bytes and nesting counted in one awk run).
hook_shfmt_fits() {
  local size
  [ "${#1}" -le "$HOOK_SHFMT_NESTING" ] && return 0
  size=$(printf '%s' "$1" | LC_ALL=C awk '{ n += length($0) + 1; m += gsub(/[|&({`]/, "") } END { print n + 0, m + 0 }') || return 1
  [ "${size% *}" -le "$((HOOK_SHFMT_BYTES + 1))" ] && [ "${size#* }" -le "$HOOK_SHFMT_NESTING" ]
}

hook_segments() {
  local out
  HOOK_SEGS=()
  HOOK_REDIRS=()
  if command -v shfmt >/dev/null 2>&1 && hook_shfmt_fits "$1" && out=$(hook_shfmt "$1"); then
    hook_records "$out"
    return
  fi
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
# The record escapes, as `enc` in lib/segments.jq: \035 is the escape byte, so a US or RS inside a word
# never splits it, and a newline is RS (BWK awk's split() also splits on a newline). Words are stored
# escaped; dec gives back the text a payload needs.
function enc(s) { gsub(/\035/, "\035e", s); gsub(/\037/, "\035u", s); gsub(/\036/, "\035r", s); gsub(/\n/, RS_, s); return s }
function dec(s) { gsub(RS_, "\n", s); gsub(/\035r/, "\036", s); gsub(/\035u/, "\037", s); gsub(/\035e/, "\035", s); return s }
# W is the word as written; WA the same word with every expansion that may be empty left out.
function add(x) { W = W x; WA = WA x }
function pushword() {
  if (INW) {
    if (REDIR == 2) HSD = HSD W "\n"
    else if (REDIR == 3) { PN++; PD[PN] = W; PS[PN] = HSTRIP; PO[PN] = 0 }
    else if (REDIR == 1 && !REDIRIN) { RN++; RD[RN] = DIR; RW[RN] = W }
    else if (REDIR == 0) {
      WSTR = (NW ? WSTR US : "") enc(W); QSTR = QSTR (WQ ? 1 : 0); NW++
      if (WA != W) ADIFF = 1
      if (WA != "" || WQ) { ASTR = (ANW ? ASTR US : "") enc(WA); AQSTR = AQSTR (WQ ? 1 : 0); ANW++ }
    }
    REDIR = 0
  }
  W = ""; WA = ""; INW = 0; WQ = 0
}
# Options of a wrapper that take the next word as their value. Mirrors `optval` in lib/segments.jq.
function optval(w, o) {
  if (w == "nice") return o == "-n"
  if (w == "sudo") return o ~ /^-[ugCDhpRrtTU]$/
  if (w == "env") return o ~ /^-[uCS]$/
  if (w == "timeout") return o ~ /^-[sk]$/
  if (w == "stdbuf") return o ~ /^-[ioe]$/
  return 0
}
# A script argument: stdin by name reads stdin; any other script is a file the guard does not read.
function script(w, idx) { if (w == "/dev/stdin" || w == "/dev/fd/0") SHIN[idx] = 1 }
# A shell with `-c` runs its payload, the first word after `-c` that is not an option; with no `-c`
# and no script argument (or with `-s`) it runs stdin. Mirrors `shellin` in lib/segments.jq.
function shellin(a, i, n, idx,    j, s) {
  s = 0
  for (j = i + 1; j <= n; j++) {
    if (a[j] ~ /^-[A-Za-z]*c[A-Za-z]*$/) {
      for (j++; j <= n && a[j] ~ /^[-+]/; j++) {
        if (a[j] == "--" || a[j] == "-") { j++; break }
        if (a[j] ~ /^[-+][oO]$/ || a[j] ~ /^--(rcfile|init-file)$/) j++
      }
      if (j <= n) enqueue(dec(a[j]), DIR)
      return
    }
    if (a[j] ~ /^[-+][oO]$/ || a[j] ~ /^--(rcfile|init-file)$/) { j++; continue }
    if (a[j] == "--") { if (j < n && !s) { script(dec(a[j + 1]), idx); return } break }
    if (a[j] ~ /^[-+]/) { if (a[j] ~ /^-[A-Za-z]*s/) s = 1; continue }
    if (!s) { script(dec(a[j]), idx); return }
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
  return dec(t)
}
# The index of the command word: leading assignments and wrappers with their options are skipped.
# Mirrors `lead` in lib/segments.jq.
function lead(a, n,    i, w) {
  i = 1
  while (i <= n) {
    if (a[i] ~ /^[A-Za-z_][A-Za-z0-9_]*=/) { i++; continue }
    if (a[i] !~ /^(env|command|exec|nohup|time|timeout|stdbuf|builtin|sudo|nice|then|do|else|if|elif|while|until|!|\{|\})$/) break
    w = a[i]; i++
    while (i <= n && a[i] ~ /^-/) { if (optval(w, a[i])) i++; i++ }
    if (w == "timeout" && i <= n) i++
  }
  return i
}
# When an expansion that may be empty sits in a word, a second record follows with those expansions
# left out (a word left empty and unquoted is dropped, as bash drops it), so `${X}git` reads as git.
function store(   a, n, i, j, k, out, base, idx, b, m) {
  if (NW == 0) return 0
  n = split(WSTR, a, US); i = lead(a, n)
  if (i > n) return 0
  out = a[i]; for (j = i + 1; j <= n; j++) out = out US a[j]
  NSEG++; SD[NSEG] = DIR; SW[NSEG] = out; SB[NSEG] = HSD; SQ[NSEG] = substr(QSTR, i); idx = NSEG
  PIPE[idx] = PIPEIN; PIPEIN = 0
  if (ADIFF) {
    m = split(ASTR, b, US); j = lead(b, m)
    if (j <= m) {
      out = b[j]; for (k = j + 1; k <= m; k++) out = out US b[k]
      NSEG++; SD[NSEG] = DIR; SW[NSEG] = out; SB[NSEG] = ""; SQ[NSEG] = substr(AQSTR, j)
    }
  }
  base = a[i]; sub(/.*\//, "", base)
  if (base == "cd") {
    j = i + 1; while (j <= n && a[j] ~ /^-./) j++
    if (j > n || a[j] !~ /[$`]|[[:cntrl:]]/) DIR = resolve(j <= n ? a[j] : "~", DIR)
  }
  if (base ~ /^(sh|bash|zsh|dash|ksh)$/) shellin(a, i, n, idx)
  if (base == "echo" || base == "printf") LIT[idx] = lit(a, i, n, base)
  if (base == "cat") { CAT[idx] = 1; for (j = i + 1; j <= n; j++) if (a[j] !~ /^-/) CAT[idx] = 0 }
  if (base == "eval" && i < n) { out = a[i + 1]; for (j = i + 2; j <= n; j++) out = out " " a[j]; enqueue(dec(out), DIR) }
  return idx
}
function endseg(   k, idx) {
  pushword(); idx = store(); LAST = idx
  for (k = 1; k <= PN; k++) if (PO[k] == 0) PO[k] = idx ? idx : -1
  WSTR = ""; QSTR = ""; NW = 0; HSD = ""; REDIR = 0; ASTR = ""; AQSTR = ""; ANW = 0; ADIFF = 0
}
# After a scan, every shell that runs stdin gets that text as a payload: its own heredoc or
# here-string, or what an `echo`, `printf` or heredoc `cat` pipes into it. What any other producer
# pipes is not read.
function stdins(first,    k, p) {
  for (k = first; k <= NSEG; k++) {
    if (!SHIN[k]) continue
    if (SB[k] != "") { enqueue(SB[k], SD[k]); continue }
    p = PIPE[k]
    while (p > 0 && CAT[p] && SB[p] == "") p = PIPE[p]
    if (p > 0 && (p in LIT)) enqueue(LIT[p], SD[k])
    else if (p > 0 && CAT[p]) enqueue(SB[p], SD[k])
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
    if (c != "\\") { add(c); i++; continue }
    nx = substr(s, i + 1, 1); i += 2
    if (nx == "n") add("\n")
    else if (nx == "t") add("\t")
    else if (nx == "x" && hexval(substr(s, i, 1)) >= 0) {
      v = hexval(substr(s, i, 1)); i++
      if (hexval(substr(s, i, 1)) >= 0) { v = v * 16 + hexval(substr(s, i, 1)); i++ }
      add(sprintf("%c", v))
    } else if (nx ~ /[0-7]/) {
      v = nx + 0; while (substr(s, i, 1) ~ /[0-7]/ && v < 32) { v = v * 8 + substr(s, i, 1); i++ }
      add(sprintf("%c", v))
    } else add(nx)
  }
  return i
}
# `$(...)` or a backtick: the body is a payload, and the text may expand to nothing, so WA leaves it
# out (an arithmetic `$((...))` always expands to a number, so WA keeps it, as the tree does).
function subst(s, i, n, open,    j, t) {
  if (open == "`") { j = index(substr(s, i + 1), "`"); j = j ? i + j : n + 1; enqueue(substr(s, i + 1, j - i - 1), DIR) }
  else { j = closing(s, i + 2, n); enqueue(substr(s, i + 2, j - i - 2), DIR) }
  t = substr(s, i, j - i + 1); INW = 1
  if (open == "(" && substr(s, i + 2, 1) == "(") add(t); else W = W t
  return j + 1
}
# `${...}` or `$name` (`$1`, `$@`, ...): an expansion that may be empty, so it goes into W and not WA.
# A `$(...)` or backtick inside `${...}` is still read as a payload.
function param(s, i, n,    c, j, depth) {
  INW = 1; c = substr(s, i + 1, 1)
  if (c ~ /[A-Za-z_]/) { j = i + 1; while (substr(s, j, 1) ~ /[A-Za-z0-9_]/) j++; W = W substr(s, i, j - i); return j }
  if (c != "{") { W = W substr(s, i, 2); return i + 2 }
  W = W "${"; i += 2; depth = 1
  while (i <= n) {
    c = substr(s, i, 1)
    if (c == "\\") { W = W substr(s, i, 2); i += 2; continue }
    if (c == "$" && substr(s, i + 1, 1) == "(") { j = length(WA); i = subst(s, i, n, "("); WA = substr(WA, 1, j); continue }
    if (c == "`") { i = subst(s, i, n, "`"); continue }
    if (c == "{") depth++
    else if (c == "}" && --depth == 0) { W = W c; return i + 1 }
    W = W c; i++
  }
  return i
}
function isparam(s, i) { return substr(s, i, 1) == "$" && substr(s, i + 1, 1) ~ /[{A-Za-z_0-9@*#?$!-]/ }
# `<(...)` or `>(...)`: the body is a payload.
function psubst(s, i, n,    j) {
  j = closing(s, i + 2, n); enqueue(substr(s, i + 2, j - i - 2), DIR)
  add(substr(s, i, j - i + 1)); INW = 1
  return j + 1
}
function dquote(s, i, n,    c, nx) {
  while (i <= n) {
    c = substr(s, i, 1)
    if (c == "\"") return i + 1
    if (c == "\\") {
      nx = substr(s, i + 1, 1)
      if (nx == "\n") { i += 2; continue }
      if (nx == "$" || nx == "`" || nx == "\"" || nx == "\\") { add(nx); i += 2; continue }
    }
    if (c == "$" && substr(s, i + 1, 1) == "(") { i = subst(s, i, n, "("); continue }
    if (c == "`") { i = subst(s, i, n, "`"); continue }
    if (isparam(s, i)) { i = param(s, i, n); continue }
    add(c); i++
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
  if (INW && W ~ /^[0-9]+$/) { W = ""; WA = ""; INW = 0; WQ = 0 } else pushword()
  if (c == "<" && substr(s, i + 1, 2) == "<<") { REDIR = 2; return i + 3 }
  if (c == "<" && substr(s, i + 1, 1) == "<") {
    i += 2; HSTRIP = 0; if (substr(s, i, 1) == "-") { HSTRIP = 1; i++ }
    REDIR = 3; return i
  }
  i++; if (substr(s, i, 1) ~ /[>|]/) i++
  if (substr(s, i, 1) == "&") { i++; while (i <= n && substr(s, i, 1) ~ /[0-9-]/) i++; return i }
  REDIR = 1; REDIRIN = (c == "<"); return i
}
function scan(s, dir,    n, i, c, j, first) {
  n = length(s); i = 1; DIR = dir; W = ""; WA = ""; INW = 0; WQ = 0; WSTR = ""; QSTR = ""; NW = 0; REDIR = 0; HSD = ""; PN = 0
  PIPEIN = 0; first = NSEG + 1
  while (i <= n) {
    c = substr(s, i, 1)
    if (c == "'") { j = index(substr(s, i + 1), "'"); if (j == 0) j = n - i + 1; add(substr(s, i + 1, j - 1)); INW = 1; WQ = 1; i += j + 1 }
    else if (c == "\"") { INW = 1; WQ = 1; i = dquote(s, i + 1, n) }
    else if (c == "$" && substr(s, i + 1, 1) == "'") { INW = 1; WQ = 1; i = ansi(s, i + 2, n) }
    else if (c == "$" && substr(s, i + 1, 1) == "(") i = subst(s, i, n, "(")
    else if (c == "`") i = subst(s, i, n, "`")
    else if (isparam(s, i)) i = param(s, i, n)
    else if ((c == "<" || c == ">") && substr(s, i + 1, 1) == "(") i = psubst(s, i, n)
    else if (c == "\\") { if (substr(s, i + 1, 1) != "\n") { add(substr(s, i + 1, 1)); INW = 1 } i += 2 }
    else if (c == "#" && !INW) { while (i <= n && substr(s, i, 1) != "\n") i++ }
    else if (c == " " || c == "\t") { pushword(); i++ }
    else if (c == "\n") { endseg(); i = heredocs(s, i + 1, n) }
    else if (c == "&" && substr(s, i + 1, 1) == ">") { pushword(); REDIR = 1; REDIRIN = 0; i += 2; if (substr(s, i, 1) == ">") i++ }
    else if (c == "|" && substr(s, i + 1, 1) != "|") {
      endseg(); PIPEIN = LAST ? LAST : -1; i++; if (substr(s, i, 1) == "&") i++
    }
    else if (c == "|") { endseg(); PIPEIN = 0; i += 2 }
    else if (c == ";" || c == "&" || c == "(" || c == ")") { endseg(); i++ }
    else if (c == ">" || c == "<") i = redirect(s, i, n, c)
    else { add(c); INW = 1; i++ }
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
    print enc(SD[k]) US enc(SB[k]) US SQ[k] US SW[k]
  }
  for (k = 1; k <= RN; k++) print US "redir" US enc(RD[k]) US enc(RW[k])
  if (OVERFLOW) print US "overflow"
}
AWK
  out=$(printf '%s\n' "$1" | awk -v cwd="$HOOK_CWD" -v home="${HOME:-}" -v max="$HOOK_MAX_PAYLOADS" "$HOOK_AWK" 2>/dev/null) \
    || hook_fail "cannot parse the shell command"
  hook_records "$out"
}

# Either parser's output into HOOK_SEGS; past the payload cap the command is too complex to judge and
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
