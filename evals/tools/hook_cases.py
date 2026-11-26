"""The case tables `test_hook_cases.py` runs through every shell guard, in both payload shapes.

A case is `(command, cwd, by)`: `cwd` names a fixture tree from `test_hook_cases.fixture()`, and `by`
is the guard that must deny (deny table) or `None` (allow table). `{name}` in a command is replaced
by that fixture tree's path. `PAYLOADS` are raw envelopes for the cases a command cannot express.
"""
from __future__ import annotations

SECRET = "key=AKI" + "AABCDEFGHIJKLMNOP"

DENY = [
    # Quotes, escapes and wrappers no longer hide a destructive subcommand.
    ('git "reset" --hard', "clean", "destructive-git"),
    ('git reset "--hard"', "clean", "destructive-git"),
    ("git clean -d -f", "clean", "destructive-git"),
    ("git clean --force", "clean", "destructive-git"),
    ("git push --force-with-lease --force", "clean", "destructive-git"),
    ("bash -c 'git reset --hard'", "clean", "destructive-git"),
    ('zsh -lc "cd /tmp && git clean -fdx"', "clean", "destructive-git"),
    ("git re\\set --ha\\rd", "clean", "destructive-git"),
    ("git --no-pager -c core.pager=cat -C {clean} reset --hard", "nogit", "destructive-git"),
    ("echo ok && GIT_TRACE=0 git push origin +main", "clean", "destructive-git"),
    ('echo "$(git reset --hard)"', "clean", "destructive-git"),
    ("git reset --hard; # " + "x" * 70000, "clean", "destructive-git"),
    # A shell reading its script from a heredoc, a here-string or a pipe runs that text.
    ("bash <<'EOF'\ngit reset --hard\nEOF", "clean", "destructive-git"),
    ("bash <<< 'git reset --hard'", "clean", "destructive-git"),
    ("cat <<EOF | sh\ngit reset --hard\nEOF", "clean", "destructive-git"),
    ("echo 'git reset --hard' | bash", "clean", "destructive-git"),
    ("printf 'git reset --hard\\n' | sudo bash -s", "clean", "destructive-git"),
    ("cat setup.sh | bash", "clean", "destructive-git"),
    # git behind a runner, or behind a wrapper that takes an option value.
    ("timeout 10 git reset --hard", "clean", "destructive-git"),
    ("nice -n 5 git reset --hard", "clean", "destructive-git"),
    ("sudo -u me git reset --hard", "clean", "destructive-git"),
    ("echo . | xargs git clean -fdx", "clean", "destructive-git"),
    ("find . -exec git reset --hard \\;", "clean", "destructive-git"),
    ("timeout -s KILL 5 git checkout main", "locked", "worker-tree"),
    # Past the payload cap the command is too complex to judge, so it is denied.
    ("echo " + "$(:) " * 70, "clean", "destructive-git"),
    # A `cd` target the guard cannot resolve leaves the directory where it was.
    ('cd "$PWD" && git checkout main', "locked", "worker-tree"),
    ("cd \"$PWD\" && python3 -c \"open('tracked.txt','w')\"", "source", "source-edit"),
    # Each segment is judged in its own tree: `-C` on one segment does not move the next.
    ("git -C {clean} log; git checkout main", "locked", "worker-tree"),
    ("cd {locked} && git restore base.txt", "clean", "worker-tree"),
    ("git -C {clean} status && git switch -c x", "locked", "worker-tree"),
    ("sh -c 'git checkout main'", "locked", "worker-tree"),
    # PR refs, through escapes and global options.
    ("gh pr chec\\kout 12", "clean", "local-pr-ref"),
    ("git --no-pager fetch origin pull/7/head:pr7", "clean", "local-pr-ref"),
    ('git show "refs/pull/42/head:src/a.ts"', "clean", "local-pr-ref"),
    ("git log main..pull/42/head", "clean", "local-pr-ref"),
    ("git fetch origin 'pull/*/head:refs/remotes/pr/*'", "clean", "local-pr-ref"),
    # Snippets that write a tracked file, in both quoting styles and through a heredoc.
    ("python3 -c \"open('tracked.txt','w').write('x')\"", "source", "source-edit"),
    ("python3 -c 'open(\"tracked.txt\", \"w\").write(\"x\")'", "source", "source-edit"),
    ("node -e \"require('fs').writeFileSync('tracked.txt', 'x')\"", "source", "source-edit"),
    ("node -e 'require(\"fs\").writeFileSync(\"tracked.txt\", \"x\")'", "source", "source-edit"),
    ("perl -e 'open(my $f, \">\", \"tracked.txt\"); print $f 1'", "source", "source-edit"),
    ("perl -e \"open(F, '>tracked.txt'); print F 1\"", "source", "source-edit"),
    ("python3 <<PY\nopen('tracked.txt', 'w').write('x')\nPY", "source", "source-edit"),
    ("node - <<'JS'\nrequire('fs').writeFileSync(\"src/pull/handler.ts\", '')\nJS", "source", "source-edit"),
    ("cd src && python3 -c \"open('pull/handler.ts','w')\"", "source", "source-edit"),
    # A secret added in the same command, and a scan that cannot run.
    ("git add leak.txt && git commit -m add", "leaky", "credentials"),
    ("git add -A && git commit -m all", "leaky", "credentials"),
    ("git commit -am wip", "leaky", "credentials"),
    ("cd {leaky} && git add . && git commit -m dot", "clean", "credentials"),
    ("git commit -m x", "corrupt", "credentials"),
    ("gh pr create --draft", "clean", "credentials"),
    ("git add -A && git commit -m all", "loose", "credentials"),
    ("git push --force-if-includes origin feature", "clean", "destructive-git"),
]

# Ordinary work: every guard stays silent (Cursor's fail-closed credentials rule answers `{}`).
ALLOW = [
    ("git status", "clean"),
    ("git log --oneline -5 | head -3", "clean"),
    ("git diff main -- src/pull/handler.ts", "source"),
    ("git log main..HEAD -- src/pull/", "source"),
    ("git show HEAD:src/pull/handler.ts", "source"),
    ("git -C {clean} status", "locked"),
    ("git -C {clean} checkout main", "locked"),
    ("cd {clean} && git switch main", "locked"),
    ("git -c color.ui=never --no-pager log -3", "clean"),
    ("", "clean"),
    ("ls -la", "nogit"),
    ("git status", "nogit"),
    ("git log -1 && git rev-parse HEAD", "detached"),
    ("git commit -m 'large change'", "large"),
    ("git diff --cached --stat", "large"),
    ("cat <<'EOF' > /tmp/hook-case-notes.txt\ngit reset --hard is dangerous\nEOF", "clean"),
    ("cat <<-EOF\n\tgit push --force\n\tEOF\nls", "clean"),
    ("python3 - <<'PY'\nprint(\"a; b | c\")\nPY", "source"),
    ("cat > /tmp/hook-case.py <<'PY'\nopen('tracked.txt', 'w')\nPY", "source"),
    ('echo "a; git reset --hard | b"', "clean"),
    ("grep -n 'push --force' README.md | wc -l", "clean"),
    ('git commit -m "fix: never git push --force; use a lease"', "clean"),
    ("git push --force-with-lease origin feature", "clean"),
    ("git push origin HEAD", "clean"),
    ("git reset --soft HEAD~1", "clean"),
    ("git clean -n", "clean"),
    ("gh pr diff 12", "clean"),
    ("gh pr view 12 --json headRefOid --jq .headRefOid", "clean"),
    ("git fetch upstream main", "clean"),
    ("git log --grep=pull/123", "clean"),
    ("bash -c 'echo hi; ls'", "clean"),
    ('sh -c "git status && git log -1"', "clean"),
    ("cd /tmp && ls", "clean"),
    ("npm test 2>&1 | tail -20", "clean"),
    ("python3 -c \"print(open('tracked.txt').read()[:10])\"", "source"),
    ("python3 -c 'import json; json.dump({}, open(\"/tmp/hook-case.json\", \"w\"))'", "source"),
    ("node -e \"console.log(require('fs').readFileSync('tracked.txt', 'utf8'))\"", "source"),
    ("perl -ne 'print if /x/' tracked.txt", "source"),
    ("jq -r '.a | .b' file.json", "clean"),
    ('rg -n "foo|bar;baz" src', "clean"),
    ("find . -name '*.py' -exec wc -l {} +", "clean"),
    ("git add notes.txt && git commit -m notes", "addable"),
    ("git commit -am wip", "source"),
    ("gh pr create --draft --repo example/upstream", "clean"),
    ("CREW_WORKER_TASK=T-1 git checkout main", "locked"),
    ("git checkout main", "stale"),
    ("echo =", "clean"),
    ("printf '%s\\n' \"a|b;c\" | tr '|' ' '", "clean"),
    ('make -j4 build && ./bin/run --flag "x;y"', "clean"),
    ("docker ps --format '{{.Names}}' | grep api", "clean"),
    ("git worktree list && git stash list", "clean"),
    ('echo "$(git rev-parse --short HEAD)"', "clean"),
    ("while read -r f; do echo \"$f\"; done < files.txt", "clean"),
    ('for f in *.md; do wc -l "$f"; done', "clean"),
    ("export FOO=bar && echo $FOO", "clean"),
    ('"" && true', "clean"),
    ("git commit -m ''", "clean"),
    ("echo 'ls -la' | bash", "clean"),
    ("printf 'y\\n' | bash ./setup.sh", "clean"),
    ('grep -rn "git" checkout', "locked"),
    ("python3 -c \"import sys; open('/tmp/o','w').write('.'.join(sys.argv))\"", "source"),
    ("python3 -c \"import os; open('/tmp/o','w').write(str(os.listdir('src')))\"", "source"),
    ("git add -u && git commit -m x", "loose"),
    ("git add --update . && git commit -m x", "loose"),
    ("git push --force-with-lease --force-if-includes origin feature", "clean"),
]

# `(command, cwd, tool, env, by)` run through `credentials.sh` alone with `tool` missing from PATH.
# Without `grep` the secret scan cannot run, so a commit blocks while a command that needs no scan
# passes. A failure before the scan starts (no `awk` for the normaliser, no `jq` for the input) lets
# the command through with at most one line on stderr, and so does any failure under an off switch.
MISSING = [
    ("git commit -m x", "clean", "grep", {}, "credentials"),
    ("git add notes.txt && git commit -m notes", "addable", "grep", {}, "credentials"),
    ("ls -la", "clean", "grep", {}, None),
    ("git status && gh pr view 1", "clean", "grep", {}, None),
    ("ls -la", "clean", "awk", {}, None),
    ("ls -la", "clean", "jq", {"EL_CAPITAN_GUARDS": "off"}, None),
    ("git commit -m x", "clean", "jq", {"EL_CAPITAN_GUARD_CREDENTIALS": "off"}, None),
]

# The documented off switches, read from the hook's environment: `EL_CAPITAN_GUARDS=off` silences
# every guard, `EL_CAPITAN_GUARD_<NAME>=off` one guard and no other.
OFF = [
    ("git reset --hard", "clean", {"EL_CAPITAN_GUARDS": "off"}, None),
    ("git reset --hard", "clean", {"EL_CAPITAN_GUARD_DESTRUCTIVE_GIT": "off"}, None),
    ("git reset --hard", "clean", {"EL_CAPITAN_GUARDS": "on"}, "destructive-git"),
    ("git checkout main", "locked", {"EL_CAPITAN_GUARD_WORKER_TREE": "off"}, None),
    ("git checkout main", "locked", {"EL_CAPITAN_GUARD_DESTRUCTIVE_GIT": "off"}, "worker-tree"),
    ("gh pr checkout 12", "clean", {"EL_CAPITAN_GUARD_LOCAL_PR_REF": "off"}, None),
    ("python3 -c \"open('tracked.txt','w')\"", "source", {"EL_CAPITAN_GUARD_SOURCE_EDIT": "off"}, None),
    ("git add leak.txt && git commit -m add", "leaky", {"EL_CAPITAN_GUARD_CREDENTIALS": "off"}, None),
    ("echo =====", "clean", {"EL_CAPITAN_GUARD_ZSH_EQUALS": "off"}, None),
    ("echo =====", "clean", {"EL_CAPITAN_GUARDS": "off"}, None),
]

# Raw envelopes `(label, claude payload, cursor payload)` with no usable command.
PAYLOADS = [
    ("non-Bash tool",
     {"hook_event_name": "PreToolUse", "tool_name": "Write",
      "tool_input": {"file_path": "/tmp/x", "content": "git reset --hard"}},
     {"hook_event_name": "preToolUse", "tool_name": "Write", "tool_input": {"file_path": "/tmp/x"}}),
    ("no tool input", {"hook_event_name": "PreToolUse", "tool_name": "Bash"},
     {"hook_event_name": "beforeShellExecution"}),
    ("null command", {"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {"command": None}},
     {"hook_event_name": "beforeShellExecution", "command": None}),
    ("no cwd", {"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {"command": "git status"}},
     {"hook_event_name": "beforeShellExecution", "command": "git status"}),
]
