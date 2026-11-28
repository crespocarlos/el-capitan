#!/usr/bin/env bash
# The shell guard: the `pre_shell` rule (contract.json). It reads the event once and normalises the command once
# (lib/hook.sh), then runs each rule below in its own subshell, cheapest first; the first objection denies, naming
# that rule's off switch (`EL_CAPITAN_GUARD_<RULE>=off`). A rule that crashes is skipped with one stderr line;
# credentials handles its own failures and denies the commands it scans when it cannot scan them.
# Everywhere: owner-only, worker-tree, destructive-git, task-files, source-edit, credentials, and too-complex (a
# command nesting more payloads than the normaliser reads); a deny rule matches the command's prefix and misses
# `git -C <tree>`, the cwd and a write's target, which these parse. Demoted (`DEMOTED`): they run only where the
# harness's manifest declares no deny rule that holds in this mode (`deny_rules` false in the event); elsewhere its
# own deny and ask rules hold them.
set -uo pipefail
HOOK_NAME=shell
# shellcheck source=lib/hook.sh
. "$(dirname "$0")/../lib/hook.sh"
hook_input
cmd=$(hook_field command)
[ -n "$cmd" ] || hook_allow
HOOK_SUBJECT=$cmd
DEMOTED="local-pr-ref:LOCAL_PR_REF pr-repo:PR_REPO"
TASKS_ROOT=$HOME/.agent/tasks
STALE_SECONDS=21600

# A rule's objection: its message on stdout, and the rule's subshell ends.
deny() {
  printf '%s\n' "$1"
  exit 0
}

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

# `crew-task.py restore-status ... --acc*`: it records a Status written outside the gates as the task's own, so only
# the owner runs it, in their own terminal (`task_gates.restore_status` refuses it in code too). Found by file name
# behind an interpreter, a wrapper, `sh -c` or `$(...)`; any `--acc*` word counts.
rule_owner_only() {
  case "$cmd" in *--acc*) ;; *) return 0 ;; esac
  local i=0 tool sub accept word
  while [ "$i" -lt "${#HOOK_SEGS[@]}" ]; do
    hook_seg "$i"
    i=$((i + 1))
    tool=0 sub="" accept=0
    for word in "${SEG_WORDS[@]}"; do
      if [ "$tool" = 0 ]; then
        [ "${word##*/}" != crew-task.py ] || tool=1
        continue
      fi
      case "$word" in --acc*) accept=1 ;; -*) ;; *) [ -n "$sub" ] || sub=$word ;; esac
    done
    if [ "$tool" = 1 ] && [ "$sub" = restore-status ] && [ "$accept" = 1 ]; then
      deny "Owner only: crew-task.py restore-status --accept records a Status written outside the gates as the task's own; the owner runs it in their own terminal. Run restore-status without --accept to write the recorded status back."
    fi
  done
}

# `git checkout`, `switch`, `restore` and `reset --hard` in a tree whose `.crew-worker.lock` is younger than
# STALE_SECONDS (task_lock.py). Each segment is judged in its own tree (cwd, `cd`, `git -C`). The builder is exempt:
# CREW_WORKER_TASK equal to the lock's task= (the hook's environment, or an inline `CREW_WORKER_TASK=<id>` prefix).
rule_worker_tree() {
  local i=0 who=${CREW_WORKER_TASK:-} root lock started task age
  local inline='(^|[[:space:];&|])CREW_WORKER_TASK=["'"'"']?([^[:space:]"'"'"';&|]*)'
  if [[ $cmd =~ $inline ]]; then who=${BASH_REMATCH[2]}; fi
  while [ "$i" -lt "${#HOOK_SEGS[@]}" ]; do
    hook_seg "$i"
    i=$((i + 1))
    hook_git || continue
    case "$GIT_SUB" in
      checkout | switch | restore) ;;
      reset) hook_git_arg '^--hard$' || continue ;;
      *) continue ;;
    esac
    root=$(git -C "$GIT_TREE" rev-parse --show-toplevel 2>/dev/null) || continue
    lock="$root/.crew-worker.lock"
    [ -f "$lock" ] || continue
    started=$(awk -F= '$1=="started"{print $2}' "$lock" 2>/dev/null || true)
    task=$(awk -F= '$1=="task"{print $2}' "$lock" 2>/dev/null || true)
    case "$started" in '' | *[!0-9]*) continue ;; esac
    if [ -n "$who" ] && [ "$who" = "$task" ]; then continue; fi
    age=$(($(date +%s) - started))
    if [ "$age" -lt "$STALE_SECONDS" ]; then
      # No task id and no removal command: the denied agent cannot tell a live worker from a crashed one.
      deny "A worker holds $root (lock $((age / 60)) min old). Do not change its branch from outside: wait, or use git -C on another tree; if you believe the worker has ended, ask the user before removing the lock."
    fi
  done
}

# `reset --hard`, `clean` with force, and force pushes (`-f`, `--force`, a `+ref`, also next to
# `--force-with-lease`; `--force-if-includes` without a lease).
rule_destructive_git() {
  local i=0 force='^(--force|-[A-Za-z]*f[A-Za-z]*)$'
  while [ "$i" -lt "${#HOOK_SEGS[@]}" ]; do
    hook_seg "$i"
    i=$((i + 1))
    hook_git || continue
    case "$GIT_SUB" in
      reset) if hook_git_arg '^--hard$'; then deny 'Destructive git command blocked: git reset --hard discards uncommitted work.'; fi ;;
      clean) if hook_git_arg "$force"; then deny 'Destructive git command blocked: git clean with force deletes untracked files.'; fi ;;
      push)
        if hook_git_arg "$force" || hook_git_arg '^\+.+$' \
          || { hook_git_arg '^--force-if-includes$' && ! hook_git_arg '^--force-with-lease(=.*)?$'; }; then
          deny 'Force push blocked. Use --force-with-lease alone, or ask the user to confirm.'
        fi ;;
    esac
  done
}

# Demoted: `gh pr checkout` puts a PR into the working checkout, so a review reads the author's tree.
rule_local_pr_ref() {
  local i=0
  while [ "$i" -lt "${#HOOK_SEGS[@]}" ]; do
    hook_seg "$i"
    i=$((i + 1))
    if hook_gh && [ "$GH_CMD" = pr ]; then
      case "$GH_SUB" in checkout | co) deny 'Pulling a PR into the local checkout is blocked. Read it with `gh pr diff <n>` and `gh api "repos/<owner>/<repo>/contents/<path>?ref=<headSHA>"`.' ;; esac
    fi
  done
}

# Demoted: `gh pr create` without `--repo` in a repository with an `upstream` remote, whose target is implied.
rule_pr_repo() {
  local i=0 word named
  while [ "$i" -lt "${#HOOK_SEGS[@]}" ]; do
    hook_seg "$i"
    i=$((i + 1))
    hook_gh && [ "$GH_CMD $GH_SUB" = "pr create" ] || continue
    named=0
    for word in "${SEG_WORDS[@]}"; do case "$word" in --repo | --repo=* | -R*) named=1 ;; esac; done
    hook_repo "$SEG_DIR"
    if [ "$named" = 0 ] && [ -n "$REPO" ] && git -C "$REPO" remote get-url upstream >/dev/null 2>&1; then
      deny 'PR blocked: an upstream remote exists, so pass --repo explicitly. Target upstream unless the user chose origin.'
    fi
  done
}

# Deny when $1, resolved against $2, is an existing tracked file of its checkout or a task's SPEC.md, PROGRESS.md or
# `.task-id`; a scratch or new file is neither.
guarded() {
  local dir tasks
  hook_path "$1" "$2"
  [ -f "$HOOK_PATH" ] || return 0
  dir=$(cd "${HOOK_PATH%/*}/" && pwd -P) || return 0
  tasks=$(cd "$TASKS_ROOT" 2>/dev/null && pwd -P) || tasks=$TASKS_ROOT
  case "${dir#"$tasks"/}/${HOOK_PATH##*/}" in
    /* | */*/*) ;;
    */SPEC.md | */PROGRESS.md | */.task-id) deny "Shell rewrite blocked: '$1' is a task record. Use the Edit tool." ;;
  esac
  if git --literal-pathspecs -C "$dir" ls-files --error-unmatch -- "${HOOK_PATH##*/}" >/dev/null 2>&1; then
    deny "Shell rewrite blocked: '$1' is a tracked file. Use the Edit or Write tool; shell writes are for scratch and new files."
  fi
}

# Every harness: a `>`/`>>` redirect, `tee`, `sed -i` or `perl -i` onto a tracked file or task record, or a
# `python -c`, `node -e`, `perl -e` snippet or heredoc that writes one. A Python snippet is parsed, never run
# (`lib/py_write_targets.py`), so only a write's target counts; Node, Perl and a Python snippet that does not parse
# count any quoted literal.
rule_source_edit() {
  local i=0 j word snippet pattern candidates candidate parsed q="[\"']" write py_write
  write="write_(text|bytes)[[:space:]]*\(|open[[:space:]]*\(.*$q([wax+]+b?|r\+b?)$q|os\.(replace|rename)[[:space:]]*\(|shutil\.(copy|move)"
  write+="|(writeFile|appendFile|copyFile|rename)(Sync)?[[:space:]]*\(|createWriteStream|open[^;]*$q[[:space:]]*\+?>"
  py_write="subprocess|os\.(open|write|system|popen)[[:space:]]*\(|fileinput|(exec|eval|getattr|__import__)[[:space:]]*\("
  while [ "$i" -lt "${#HOOK_REDIRS[@]}" ]; do
    hook_redir "$i"
    i=$((i + 1))
    guarded "$REDIR_PATH" "$REDIR_DIR"
  done
  i=0
  while [ "$i" -lt "${#HOOK_SEGS[@]}" ]; do
    hook_seg "$i"
    i=$((i + 1))
    OPS=()
    case "${SEG_WORDS[0]##*/}" in
      tee) operands ;;
      sed | perl) for word in "${SEG_WORDS[@]:1}"; do
          if [[ $word =~ ^(-[nEprsuzlaw]*i|--in-place) ]]; then operands '-e|-f|--expression|--file'; break; fi
        done ;;
    esac
    for word in ${OPS[@]+"${OPS[@]}"}; do guarded "$word" "$SEG_DIR"; done
    case "${SEG_WORDS[0]##*/}" in python | python[0-9]* | node | nodejs | perl) ;; *) continue ;; esac
    snippet=$SEG_BODY
    j=1
    while [ "$j" -lt "${#SEG_WORDS[@]}" ]; do
      case "${SEG_WORDS[$j]}" in
        -c | -e | -E | -p | --eval | --print | -[A-Za-z]*[ce]) snippet+=$'\n'"${SEG_WORDS[$((j + 1))]:-}" ;;
      esac
      j=$((j + 1))
    done
    pattern=$write
    case "${SEG_WORDS[0]##*/}" in python*) pattern+="|$py_write" ;; esac
    if [ -z "$snippet" ] || ! grep -Eq -- "$pattern" <<<"$snippet"; then continue; fi
    parsed=0
    case "${SEG_WORDS[0]##*/}" in
      python*) candidates=$(python3 -I "$HOOK_LIB/py_write_targets.py" <<<"$snippet" 2>/dev/null) && parsed=1 ;;  # crew-lint: allow-swallow
    esac
    if [ "$parsed" -eq 0 ]; then
      candidates=$(grep -oE "\"[^\"]+\"|'[^']+'" <<<"$snippet" | sed -e 's/^.//' -e 's/.$//') || candidates=""
    fi
    while IFS= read -r candidate; do
      candidate=${candidate#"${candidate%%[!+<> ]*}"}
      [ -z "$candidate" ] || guarded "$candidate" "$SEG_DIR"
    done <<<"$candidates"
  done
}

# An `rm`, `unlink` or `find -delete` of a task record (SPEC.md, PROGRESS.md, `.task-id`, review
# evidence), a task directory or the tasks root; the path is decided by `lib/spec_guard.py --shell`.
rule_task_files() {
  case "$cmd:$HOOK_CWD/" in *.agent* | *:"$HOME/.agent/"*) ;; *) return 0 ;; esac
  local i=0 j word verdict cands=()
  while [ "$i" -lt "${#HOOK_SEGS[@]}" ]; do
    hook_seg "$i"
    i=$((i + 1))
    case "${SEG_WORDS[0]##*/}" in
      rm | unlink)
        operands
        for word in ${OPS[@]+"${OPS[@]}"}; do cands+=("$SEG_DIR" "$word"); done ;;
      find)
        case " ${SEG_WORDS[*]} " in *" -delete "*) ;; *) continue ;; esac
        j=1
        while [ "$j" -lt "${#SEG_WORDS[@]}" ]; do
          case "${SEG_WORDS[$j]}" in -* | "(" | "!") break ;; esac
          cands+=("$SEG_DIR" "${SEG_WORDS[$j]}")
          j=$((j + 1))
        done ;;
    esac
  done
  [ "${#cands[@]}" -gt 0 ] || return 0
  verdict=$(printf '%s\0' "${cands[@]}" | python3 -I "$HOOK_LIB/spec_guard.py" --shell "$TASKS_ROOT")
  case "$verdict" in "deny "*) deny "${verdict#deny }" ;; esac
}

# A secret in what `git commit` records (the index, the working tree with `-a`, what a `git add` in the same command
# stages), or in the commits `git push` and `gh pr create` publish (every branch's and tag's commits on no remote),
# scanned by gitleaks.
# Without gitleaks, or when a scan cannot run, only those commands are denied.
rule_credentials() {
  local i=0 k commits="" adds="" pushes="" added="" staged gitleaks rc
  while [ "$i" -lt "${#HOOK_SEGS[@]}" ]; do
    hook_seg "$i"
    i=$((i + 1))
    if hook_gh && [ "$GH_CMD $GH_SUB" = "pr create" ]; then pushes+=" $((i - 1))"; fi
    hook_git || continue
    case "$GIT_SUB" in commit) commits+=" $((i - 1))" ;; add) adds+=" $((i - 1))" ;; push) pushes+=" $((i - 1))" ;; esac
  done
  [ -n "$commits$pushes" ] || return 0
  gitleaks=$(command -v gitleaks || echo "$HOME/.agent/bin/gitleaks")
  [ -x "$gitleaks" ] || deny "Blocked: gitleaks is not installed, so this commit or push cannot be scanned for secrets. Run install.sh."
  # A gitleaks exit other than 0 or 3 ends the rule with an error, and `rule` denies the command. A commit whose index
  # git cannot read is not scanned (one stderr line): the push scan still runs before anything is published.
  for k in $pushes; do
    hook_seg "$k"
    if hook_git; then hook_repo "$GIT_TREE"; else hook_repo "$SEG_DIR"; fi
    [ -n "$REPO" ] || continue
    rc=0
    "$gitleaks" git --no-banner --exit-code 3 -l error --log-opts="--branches --tags --not --remotes" "$REPO" >/dev/null 2>&1 || rc=$?
    [ "$rc" != 3 ] || deny 'Push blocked: a commit not yet on any remote contains a credential-like token or private key (gitleaks). Remove it from history; rotate it if it was real.'
    [ "$rc" = 0 ] || return 1
  done
  [ -n "$commits" ] || return 0
  for k in $adds $commits; do
    hook_seg "$k"
    hook_git
    hook_repo "$GIT_TREE"
    [ -n "$REPO" ] || continue
    if [ "$GIT_SUB" = add ]; then added+=$'\n'$(hook_git_added "$REPO" yes ${GIT_ARGS[@]+"${GIT_ARGS[@]}"}); continue; fi
    if ! staged=$(git -C "$REPO" diff --cached -U0 2>/dev/null); then
      printf 'shell: credentials: cannot read the git index in %s; this commit is not scanned\n' "$REPO" >&3
      continue
    fi
    added+=$'\n'$(hook_plus_lines <<<"$staged")
    if hook_git_arg '^(--all|-[A-Za-z]*a[A-Za-z]*)$'; then added+=$'\n'$(hook_git_added "$REPO" no); fi
  done
  rc=0
  printf '%s\n' "$added" | "$gitleaks" stdin --no-banner --exit-code 3 -l error >/dev/null 2>&1 || rc=$?
  [ "$rc" != 3 ] || deny 'Commit blocked: changes being committed contain a credential-like token or private key (gitleaks). Remove it; rotate it if it was real.'
  [ "$rc" = 0 ] || return 1
}

# Run rule $1 in its own subshell unless its off switch is set ($2: the switch's suffix); deny on its objection.
# A rule that fails is skipped with one stderr line, except credentials, which only fails on a command it scans.
# A rule's own stderr is discarded; a line it means to show goes to fd 3. The substitution stands alone, not in an
# `||` list: bash 5.2 ignores `set -e` inside a substitution there, so errexit would hold on one platform only.
rule() {
  local out rc switch=EL_CAPITAN_GUARD_$2
  [ "${!switch:-}" != off ] || return 0
  out=$(set -e; "rule_${1//-/_}" 3>&2 2>/dev/null)
  rc=$?
  HOOK_NAME=$1
  [ -z "$out" ] || hook_deny "$out"
  [ "$rc" = 0 ] || [ "$1" != credentials ] || hook_deny "Blocked: the secret scan failed (exit $rc), so this commit or push was not checked."
  [ "$rc" = 0 ] || printf '%s: rule %s failed (exit %s); skipped\n' shell "$1" "$rc" >&2
}

HOOK_NAME=too-complex
hook_segments "$cmd"
[ -z "$HOOK_UNPARSED" ] || hook_deny "Blocked: the guard could not parse this command $HOOK_UNPARSED."
[ "$HOOK_OVERFLOW" = 0 ] || hook_deny "Blocked: command too complex for the guard (more than $HOOK_MAX_PAYLOADS nested commands to check). Split it into smaller commands."
rule owner-only OWNER_ONLY
rule worker-tree WORKER_TREE
rule destructive-git DESTRUCTIVE_GIT
rule task-files TASK_FILES
rule source-edit SOURCE_EDIT
if [ "$HOOK_DENY_RULES" = 0 ]; then
  for pair in $DEMOTED; do rule "${pair%:*}" "${pair#*:}"; done
fi
rule credentials CREDENTIALS
hook_allow
