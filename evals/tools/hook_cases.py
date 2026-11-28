"""The case tables `test_harness_parity.py` runs through `crew-hook.py`, in every adapter's payload shape.

A shell case is `(command, cwd, by)`: `cwd` names a fixture tree from `test_hook_cases.fixture()`, and
`by` is the guard that must deny (deny table) or `None` (allow table). `{name}` in a command is
replaced by that fixture tree's path. A file case is `(fields, cwd, by)` sent to the `Write|Edit`
hooks; `{home}`, `{tmp}`, `{tasks}` and `{review}` are filled in as well. `PAYLOADS` are raw
envelopes for the cases a command cannot express.
"""
from __future__ import annotations

SECRET = "key=AKI" + "AABCDEFGHIJKLMNOP"
WRITE_TRACKED = "python3 - <<'PY'\nfrom pathlib import Path\nPath(\"tracked.txt\").write_text(\"x\")\nPY"

DENY = [
    # Quotes, escapes and wrappers no longer hide a destructive subcommand.
    ('git "reset" --hard', "clean", "destructive-git"),
    ('git reset "--hard"', "clean", "destructive-git"),
    ("git clean -d -f", "clean", "destructive-git"),
    ("git clean --force", "clean", "destructive-git"),
    ("git push -f origin main", "clean", "destructive-git"),
    ("git push --force-with-lease --force", "clean", "destructive-git"),
    ("bash -c 'git reset --hard'", "clean", "destructive-git"),
    ('zsh -lc "cd /tmp && git clean -fdx"', "clean", "destructive-git"),
    ("git re\\set --ha\\rd", "clean", "destructive-git"),
    ("git --no-pager -c core.pager=cat -C {clean} reset --hard", "nogit", "destructive-git"),
    ("git --git-dir=/tmp/a/.git --work-tree=/tmp/x reset --hard", "clean", "destructive-git"),
    ("echo ok && GIT_TRACE=0 git push origin +main", "clean", "destructive-git"),
    ('echo "$(git reset --hard)"', "clean", "destructive-git"),
    ("git reset --hard; # " + "x" * 70000, "clean", "destructive-git"),
    ("git push --force-if-includes origin feature", "clean", "destructive-git"),
    # A shell reading its script from a heredoc, a here-string or an echo, printf or heredoc pipe runs that text.
    ("bash <<'EOF'\ngit reset --hard\nEOF", "clean", "destructive-git"),
    ("bash <<< 'git reset --hard'", "clean", "destructive-git"),
    ("cat <<EOF | sh\ngit reset --hard\nEOF", "clean", "destructive-git"),
    ("echo 'git reset --hard' | bash", "clean", "destructive-git"),
    ("printf 'git reset --hard\\n' | sudo bash -s", "clean", "destructive-git"),
    # git behind a runner, or behind a wrapper that takes an option value.
    ("timeout 10 git reset --hard", "clean", "destructive-git"),
    ("nice -n 5 git reset --hard", "clean", "destructive-git"),
    ("sudo -u me git reset --hard", "clean", "destructive-git"),
    ("echo . | xargs git clean -fdx", "clean", "destructive-git"),
    ("find . -exec git reset --hard \\;", "clean", "destructive-git"),
    # Compound commands: the shfmt path walks the tree, the awk path splits on their keywords.
    ("case x in a) git reset --hard;; esac", "clean", "destructive-git"),
    ("f() { git clean -fdx; }; f", "clean", "destructive-git"),
    ("export A=$(git reset --hard)", "clean", "destructive-git"),
    ("for i in $(git reset --hard); do :; done", "clean", "destructive-git"),
    ("[[ -n $(git push -f) ]] && echo é", "clean", "destructive-git"),
    ("echo 'git reset --hard' | cat | bash", "clean", "destructive-git"),
    # What shfmt cannot parse, at the top or in a payload, is read by awk, never allowed for it.
    ("git reset --hard; fi", "clean", "destructive-git"),
    ("bash -c 'git reset --hard; fi'", "clean", "destructive-git"),
    # Past the payload cap the command is too complex to judge, so it is denied.
    ("echo " + "$(:) " * 70, "clean", "too-complex"),
    # A `cd` into a name with a control character leaves the directory where it was, and a control
    # character inside a word or a directory never shifts the record's fields.
    ("mkdir -p $'\\037' && cd $'\\037' && git reset --hard", "clean", "destructive-git"),
    ("cd $'\\037'; git clean -fdx", "clean", "destructive-git"),
    ("mkdir -p $'q\\nq' && cd $'q\\nq' && sh -c 'git push -f'", "clean", "destructive-git"),
    ("cd $'\\037' && git commit -m x", "ctrlleak", "credentials"),
    ("git -C $'\\037' reset --hard", "clean", "destructive-git"),
    # An unquoted expansion may be empty, so a word is also read without it.
    ("${NOPE}git reset --hard", "clean", "destructive-git"),
    ("$(true)git reset --hard", "clean", "destructive-git"),
    ("`true`git reset --hard", "clean", "destructive-git"),
    ("g${NOPE}it reset --hard", "clean", "destructive-git"),
    ("git ${NOPE}reset --hard", "clean", "destructive-git"),
    ("git reset ${NOPE}--hard", "clean", "destructive-git"),
    # A shell's script: the first word after `-c` that is not an option, or stdin by name.
    ("bash -c -- 'git reset --hard'", "clean", "destructive-git"),
    ("bash -c -e 'git reset --hard'", "clean", "destructive-git"),
    ("echo 'git reset --hard' | bash /dev/stdin", "clean", "destructive-git"),
    # A fresh worker lock: a tree change in that tree, named by cwd, `git -C`, a leading `cd` or a runner.
    ("git checkout main", "locked", "worker-tree"),
    ("git restore base.txt", "locked", "worker-tree"),
    ("git -C {locked} checkout main", "clean", "worker-tree"),
    ("cd {locked} && git restore base.txt", "clean", "worker-tree"),
    ("timeout -s KILL 5 git checkout main", "locked", "worker-tree"),
    ("CREW_WORKER_TASK=T-2 git checkout main", "locked", "worker-tree"),
    ("CREW_WORKER_TASK= git checkout main", "locked", "worker-tree"),
    # A `cd` target the guard cannot resolve leaves the directory where it was.
    ('cd "$PWD" && git checkout main', "locked", "worker-tree"),
    ("cd \"$PWD\" && python3 -c \"open('tracked.txt','w')\"", "source", "source-edit"),
    # Each segment is judged in its own tree: `-C` on one segment does not move the next.
    ("git -C {clean} log; git checkout main", "locked", "worker-tree"),
    ("git -C {clean} status && git switch -c x", "locked", "worker-tree"),
    ("sh -c 'git checkout main'", "locked", "worker-tree"),
    # `gh pr checkout`, plain and through escapes, aliases and global options.
    ("gh pr checkout 12", "clean", "local-pr-ref"),
    ("gh pr chec\\kout 12", "clean", "local-pr-ref"),
    ("g\\h pr 'check'out 12", "clean", "local-pr-ref"),
    ("gh pr -R owner/repo checkout 12", "clean", "local-pr-ref"),
    ("gh pr --repo=owner/repo chec\\kout 12", "clean", "local-pr-ref"),
    ("echo 12 | xargs gh pr co", "clean", "local-pr-ref"),
    ("bash -c 'gh pr chec\\kout 12'", "clean", "local-pr-ref"),
    # Snippets that write a tracked file: both quoting styles, a heredoc, an absolute interpreter, a subdirectory cwd.
    ("python3 -c \"open('tracked.txt','w').write('x')\"", "source", "source-edit"),
    ("python3 -c 'open(\"tracked.txt\", \"w\").write(\"x\")'", "source", "source-edit"),
    ("node -e \"require('fs').writeFileSync('tracked.txt', 'x')\"", "source", "source-edit"),
    ("node -e 'require(\"fs\").writeFileSync(\"tracked.txt\", \"x\")'", "source", "source-edit"),
    ("perl -e 'open(my $f, \">\", \"tracked.txt\"); print $f 1'", "source", "source-edit"),
    ("perl -e \"open(F, '>tracked.txt'); print F 1\"", "source", "source-edit"),
    ("python3 <<PY\nopen('tracked.txt', 'w').write('x')\nPY", "source", "source-edit"),
    (WRITE_TRACKED, "source", "source-edit"),
    (WRITE_TRACKED.replace("python3", "/usr/bin/python3"), "source", "source-edit"),
    ("node - <<'JS'\nrequire('fs').writeFileSync(\"src/pull/handler.ts\", '')\nJS", "source", "source-edit"),
    ("cd src && python3 -c \"open('pull/handler.ts','w')\"", "source", "source-edit"),
    ("python3 -c \"open('handler.ts','w')\"", "source-sub", "source-edit"),
    # A parsed Python write target: a keyword mode, a copy's destination, a name bound to the literal; and a
    # snippet that does not parse, which keeps the broader rule (any literal naming a tracked file).
    ("python3 -c 'open(\"tracked.txt\", mode=\"a\").write(\"x\")'", "source", "source-edit"),
    ("python3 -c \"import shutil; shutil.copy('/tmp/hook-case.txt', 'tracked.txt')\"", "source", "source-edit"),
    ("python3 - <<'PY'\np = 'tracked.txt'\nopen(p, 'w').write('x')\nPY", "source", "source-edit"),
    ("python3 -c \"x = open('tracked.txt').read(); open('/tmp/hook-case-o','w').write(x\"", "source", "source-edit"),
    # Writes the parser cannot resolve fall back to the broader rule too: a loop variable, an f-string, a name
    # bound twice, and a copy run as a process.
    ("python3 -c \"for f in ['tracked.txt']: open(f, 'w')\"", "source", "source-edit"),
    ("python3 -c \"p = 'tracked.txt'; open(f'{p}', 'w')\"", "source", "source-edit"),
    ("python3 - <<'PY'\np = '/tmp/hook-case-o'\np = 'tracked.txt'\nopen(p, 'w')\nPY", "source", "source-edit"),
    ("python3 -c \"import subprocess; subprocess.run(['cp', '/tmp/hook-case.txt', 'tracked.txt'])\"", "source",
     "source-edit"),
    # Every write form, in every harness, onto a tracked file and onto a task record (also through a symlink).
    ("python3 -c \"open('{tasks}/DDD-status/SPEC.md','w')\"", "clean", "source-edit"),
    ("python3 - <<'PY'\nfrom pathlib import Path\np = Path('{tasks}/DDD-status/SPEC.md')\n"
     "p.write_text(p.read_text().replace('- [ ] T1', '- [x] T1'))\nPY", "clean", "source-edit"),
    ("node -e \"require('fs').appendFileSync('{tasks}/DDD-status/.task-id', 'x')\"", "clean", "source-edit"),
    ("perl -e \"open(F, '>>{home}/linked-task/SPEC.md'); print F 1\"", "clean", "source-edit"),
    ("sed -i '' 's/one/two/' tracked.txt", "source", "source-edit"),
    ("sed -i.bak -e 's/T1/T9/' {tasks}/DDD-status/SPEC.md", "clean", "source-edit"),
    ("sed --in-place 's/one/two/' src/pull/handler.ts", "source", "source-edit"),
    ("perl -pi -e 's/one/two/' tracked.txt", "source", "source-edit"),
    ("perl -i -pe 's/T1/T9/' {tasks}/DDD-status/SPEC.md", "clean", "source-edit"),
    ("echo x > tracked.txt", "source", "source-edit"),
    ("printf x >> {tasks}/DDD-status/SPEC.md", "clean", "source-edit"),
    ("cat > {tasks}/DDD-status/.task-id <<'EOF'\n{}\nEOF", "clean", "source-edit"),
    ("bash -c 'echo x >> src/pull/handler.ts'", "source", "source-edit"),
    ("echo x | tee tracked.txt", "source", "source-edit"),
    ("echo x | tee -a {tasks}/DDD-status/SPEC.md >/dev/null", "clean", "source-edit"),
    # A secret staged or added in the same command, and a large diff with the secret first;
    # the kept rules through `bash -c`, an interpreter path, a wrapper and `$(...)`; a secret in a commit a push or a PR
    # would publish.
    ("bash -c 'git commit -m leak'", "staged", "credentials"),
    ("/usr/bin/git commit -m leak", "staged", "credentials"),
    ("timeout 10 git commit -m leak", "staged", "credentials"),
    ('echo "$(git commit -m leak)"', "staged", "credentials"),
    ("git push origin main", "pushleak", "credentials"),
    ("gh pr create --draft --repo example/upstream", "pushleak", "credentials"),
    ('echo "$(git checkout main)"', "locked", "worker-tree"),
    ("/usr/bin/git checkout main", "locked", "worker-tree"),
    ('echo "$(~/.agent/bin/crew-task.py restore-status /x --accept ok)"', "clean", "owner-only"),
    ("timeout 5 ~/.agent/bin/crew-task.py restore-status /x --accept ok", "clean", "owner-only"),
    ("gh pr create --draft", "clean", "pr-repo"),
    # Deny rules match a command's prefix and miss `git -C <tree>` and a removal resolved against the cwd: both rules
    # run in every harness, so these rows deny in Claude Code's payload too.
    ("git -C {clean} reset --hard", "nogit", "destructive-git"),
    ("git -C {clean} clean -fdx", "nogit", "destructive-git"),
    ("git -C {clean} push --force", "nogit", "destructive-git"),
    ('cd {tasks}/DDD-status && rm -rf "$VAR"', "clean", "task-files"),
    ("cd {tasks}/DDD-status && rm PROGRESS.md", "clean", "task-files"),
    ("git add leak.txt && git commit -m add", "leaky", "credentials"),
    ("git add -A && git commit -m all", "leaky", "credentials"),
    ("git commit -am wip", "leaky", "credentials"),
    ("cd {leaky} && git add . && git commit -m dot", "clean", "credentials"),
    ("git commit -m leak", "staged", "credentials"),
    ("git -C {staged} commit -m leak", "clean", "credentials"),
    ('git commit -m "restore cd /tmp behavior"', "staged", "credentials"),
    ("git commit -m big", "bigleak", "credentials"),
    ("git add -A && git commit -m all", "loose", "credentials"),
    # A removal of a task record, a task directory or the tasks root, by `rm`, `unlink` or `find -delete`.
    ("rm {tasks}/DDD-status/PROGRESS.md", "clean", "task-files"),
    ("rm -f {tasks}/DDD-status/SPEC.md", "clean", "task-files"),
    ("rm -rf {tasks}/DDD-status", "clean", "task-files"),
    ("rm -rf ~/.agent/tasks", "clean", "task-files"),
    ("unlink {tasks}/DDD-status/.task-id", "clean", "task-files"),
    ("find {tasks}/DDD-status -name PROGRESS.md -delete", "clean", "task-files"),
    # Only the owner, in their own terminal, keeps a Status written outside the gates; an abbreviation is the same word.
    ("~/.agent/bin/crew-task.py restore-status {tasks}/DDD-status --acc 'owner ok'", "clean", "owner-only"),
    ("~/.agent/bin/crew-task.py restore-status {tasks}/DDD-status --accept 'owner approved'", "clean", "owner-only"),
    ("python3 ~/.agent/bin/crew-task.py restore-status {tasks}/DDD-status --accept=ok", "clean", "owner-only"),
    ("bash -c '~/.agent/bin/crew-task.py restore-status /x --accept ok'", "clean", "owner-only"),
]

# Ordinary work: both guards stay silent (the harness's empty answer).
ALLOW = [
    ("git status", "clean"),
    ("git log --oneline -5 | head -3", "clean"),
    ("git diff main -- src/pull/handler.ts", "source"),
    ("git log main..HEAD -- src/pull/", "source"),
    ("git show HEAD:src/pull/handler.ts", "source"),
    ("git -C {clean} status", "locked"),
    ("git -C {clean} checkout main", "locked"),
    ("cd {clean} && git switch main", "locked"),
    ("git status", "locked"),
    ("git reset --soft HEAD~1", "locked"),
    ('git commit -m "git checkout main"', "locked"),
    ("CREW_WORKER_TASK=T-1 git checkout main", "locked"),
    ("export CREW_WORKER_TASK=T-1 && git switch -c next", "locked"),
    ("git checkout main", "stale"),
    ("git checkout main", "clean"),
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
    ("python3 - <<'PY'\nfrom pathlib import Path\nPath(\"/tmp/hook-case.json\").write_text(\"{}\")\nPY", "source"),
    ("cat > /tmp/hook-case.py <<'PY'\nopen('tracked.txt', 'w')\nPY", "source"),
    ('echo "a; git reset --hard | b"', "clean"),
    ("grep -n 'push --force' README.md | wc -l", "clean"),
    ('git commit -m "fix: never git push --force; use a lease"', "clean"),
    ("git push --force-with-lease origin feature", "clean"),
    ("git push --force-with-lease --force-if-includes origin feature", "clean"),
    ("git push origin HEAD", "clean"),
    ("git reset --soft HEAD~1", "clean"),
    ("git clean -n", "clean"),
    ("gh pr diff 12", "clean"),
    ("gh pr -R owner/repo view 12", "clean"),
    ('grep -n "gh" README.md', "clean"),
    ("gh pr view 12 --json headRefOid --jq .headRefOid", "clean"),
    # A jq filter with escapes inside quotes is read-only data.
    ("""gh pr view --json url,number,state --jq '"#\\(.number) (\\(.state)): \\(.url)"'""", "clean"),
    ('gh pr view --json number --jq "#\\(.number)"', "clean"),
    ("""gh pr view --json number --jq '"#" + (.number|tostring)'""", "clean"),
    ("git fetch upstream main", "clean"),
    ("git log --grep=pull/123", "clean"),
    ("bash -c 'echo hi; ls'", "clean"),
    ('sh -c "git status && git log -1"', "clean"),
    ("cd /tmp && ls", "clean"),
    ("npm test 2>&1 | tail -20", "clean"),
    ("python3 -c \"print(open('tracked.txt').read()[:10])\"", "source"),
    # A Python snippet that reads a tracked file and writes a scratch one: only the write's target counts.
    ("python3 - <<'PY'\nimport json\ndata = json.load(open(\"tracked.txt\"))\n"
     "open(\"/tmp/hook-case-out.json\", \"w\").write(json.dumps(data))\nPY", "source"),
    ("python3 -c 'import json; json.dump({}, open(\"/tmp/hook-case.json\", \"w\"))'", "source"),
    ("node -e \"console.log(require('fs').readFileSync('tracked.txt', 'utf8'))\"", "source"),
    ("perl -ne 'print if /x/' tracked.txt", "source"),
    ("jq -r '.a | .b' file.json", "clean"),
    ('rg -n "foo|bar;baz" src', "clean"),
    ("find . -name '*.py' -exec wc -l {} +", "clean"),
    ("git add notes.txt && git commit -m notes", "addable"),
    ("git commit -am wip", "source"),
    ("cd '{addable}' && git commit -m clean", "staged"),
    ('git -C "{addable}" commit -m clean', "staged"),
    ("gh pr create --draft --repo example/upstream", "clean"),
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
    # A task file read, copied elsewhere or moved by crew-task.py, and a task's first SPEC.md; a scratch file beside it.
    ("~/.agent/bin/crew-task.py mark-approved {tasks}/DDD-status", "clean"),
    ("cat {tasks}/DDD-status/SPEC.md", "clean"),
    ("sed -n 1,5p {tasks}/DDD-status/SPEC.md", "clean"),
    ("perl -Ilib -ne 'print' {tasks}/DDD-status/SPEC.md", "clean"),
    ("grep -n Status {tasks}/DDD-status/SPEC.md > /tmp/hook-case-status.txt", "clean"),
    ("cp {tasks}/DDD-status/SPEC.md /tmp/hook-case-spec.md", "clean"),
    ("python3 -c \"print(open('{tasks}/DDD-status/SPEC.md').read())\"", "clean"),
    ("cat > {tasks}/BBB-new/SPEC.md <<'EOF'\n# Spec: x\nEOF", "clean"),
    ("echo brief > {tasks}/DDD-status/review/1/adversarial.in.md", "clean"),
    ("rsync -a {tasks}/DDD-status/ /tmp/hook-case-backup/", "clean"),
    ("dd if={tasks}/DDD-status/SPEC.md of=/tmp/hook-case-spec.md", "clean"),
    ("cat {tasks}/DDD-status/PROGRESS.md | tail -3", "clean"),
    ("~/.agent/bin/crew-task.py restore-status {tasks}/DDD-status", "clean"),
    ("~/.agent/bin/crew-task.py mark-done {tasks}/DDD-status --force --pr-url 'closed: stale'", "clean"),
    ("grep -n -- --accept README.md", "clean"),
    ("rm -f /tmp/hook-case-x ~/.agent/state/hook-case.log", "clean"),
    ("rm -rf {tasks}/DDD-status/artifacts/old", "clean"),
    ("python3 -c \"import json; print(json.load(open('{tasks}/DDD-status/.task-id')))\"", "clean"),
    ("python3 -c \"import task_state; print(task_state.BORN)\"", "clean"),
    # Shell writes to scratch (temp dirs, a task's artifacts and review dirs), to a new or untracked file, and reads.
    ("echo x > {tmp}/hook-case.txt && sed -i '' 's/x/y/' {tmp}/hook-case.txt", "source"),
    ("echo x | tee /tmp/hook-case-tee.txt", "source"),
    ("printf x > {tasks}/DDD-status/artifacts/e1.txt", "clean"),
    ("cat > {tasks}/DDD-status/review/1/findings.json <<'EOF'\n{\"path\": \"tracked.txt\"}\nEOF", "source"),
    ("echo x > new-file.txt && echo y | tee -a new-file.txt", "source"),
    ("echo more >> notes.txt", "addable"),
    ("sed -n 1p tracked.txt > /dev/null 2>&1", "source"),
    # Review JSON naming a tracked file, and a scratch script reading one, each writing a path the parser cannot name.
    ("python3 - <<'PY'\nimport json, os\njson.dump([{\"path\": \"tracked.txt\"}], open(os.path.join(os.environ[\"TMPDIR\"], "
     "\"f.json\"), \"w\"))\nPY", "source"),
    ("python3 - <<'PY'\nimport os\nout = os.environ['TMPDIR'] + '/x.txt'\nopen(out, 'w').write(open('tracked.txt').read())\nPY", "source"),
]

# Every row above runs through both parsers of `hook_segments` (shfmt on PATH, and PATH without it)
# and must get the same verdict from each. These rows are the listed exceptions, `(command, cwd, by
# with shfmt, by with awk, reason)`: the commands the awk normaliser misreads and the shfmt tree gets
# right, so shfmt's verdict is the correct one.
PARSERS_DIFFER = [
    ('echo $(echo ")"; git reset --hard)', "clean", "destructive-git", None,
     "awk's `$(...)` matcher skips single quotes only: the quoted `)` ends the payload, the rest reads as quoted text"),
    ("cat <<EOF\n$(git reset --hard)\nEOF", "clean", "destructive-git", None,
     "bash expands `$(...)` in an unquoted heredoc body; awk keeps every heredoc body as data"),
    ('echo "$(echo "a)") git reset --hard"', "clean", None, "destructive-git",
     "the same quoted `)`: awk ends the payload early and reads the quoted tail as an unquoted `git` word"),
]

# `(command, cwd, tool, env, by)` with `tool` missing from PATH. Without gitleaks the credentials rule denies only the
# commands it scans (a commit, a push, `gh pr create`); a failure before any rule runs (no `awk` for the normaliser, no
# `jq` for the input) lets the command through with exactly one line on stderr.
MISSING = [
    ("git commit -m x", "clean", "gitleaks", {}, "credentials"),
    ("git push origin main", "clean", "gitleaks", {}, "credentials"),
    ("gh pr create --draft --repo example/upstream", "clean", "gitleaks", {}, "credentials"),
    ("ls -la", "clean", "gitleaks", {}, None),
    ("git status && gh pr view 1", "clean", "gitleaks", {}, None),
    ("ls -la", "clean", "awk", {}, None),
]

# `(command, cwd, env, by)` with the hook's environment changed: the documented off switches
# (`EL_CAPITAN_GUARDS=off` silences every guard, `EL_CAPITAN_GUARD_<NAME>=off` one and no other), the
# worker's own task id (only the lock's id is exempt).
ENV = [
    ("git reset --hard", "clean", {"EL_CAPITAN_GUARDS": "off"}, None),
    ("git reset --hard", "clean", {"EL_CAPITAN_GUARD_DESTRUCTIVE_GIT": "off"}, None),
    ("git reset --hard", "clean", {"EL_CAPITAN_GUARDS": "on"}, "destructive-git"),
    ("git checkout main", "locked", {"EL_CAPITAN_GUARD_WORKER_TREE": "off"}, None),
    ("git checkout main", "locked", {"EL_CAPITAN_GUARD_DESTRUCTIVE_GIT": "off"}, "worker-tree"),
    ("gh pr checkout 12", "clean", {"EL_CAPITAN_GUARD_LOCAL_PR_REF": "off"}, None),
    ("python3 -c \"open('tracked.txt','w')\"", "source", {"EL_CAPITAN_GUARD_SOURCE_EDIT": "off"}, None),
    ("git add leak.txt && git commit -m add", "leaky", {"EL_CAPITAN_GUARD_CREDENTIALS": "off"}, None),
    ("rm {tasks}/DDD-status/SPEC.md", "clean", {"EL_CAPITAN_GUARD_TASK_FILES": "off"}, None),
    ("~/.agent/bin/crew-task.py restore-status /x --accept ok", "clean", {"EL_CAPITAN_GUARD_OWNER_ONLY": "off"}, None),
    ("git checkout main", "locked", {"CREW_WORKER_TASK": "T-1"}, None),
    ("git -C {locked} checkout main", "clean", {"CREW_WORKER_TASK": "T-1"}, None),
    ("git checkout main", "locked", {"CREW_WORKER_TASK": "T-2"}, "worker-tree"),
    ("git checkout main", "locked", {"CREW_WORKER_TASK": ""}, "worker-tree"),
]

# A denial a row expects from these guards must say (first) and must not say (second) these words.
MESSAGES = {
    # The denied agent cannot tell a live worker from a crashed one: no task id, no removal command.
    # The age grows while the suite runs (slow runners pass a minute), so only its presence is checked.
    "worker-tree": (("ask the user before removing the lock", " min old)"), ("T-1", "lock remove")),
    "owner-only": (("Owner only", "own terminal"), ()),
}

# The SPEC.md on disk in the fixture's `DDD-status` task.
STATUS_SPEC = "# Spec: Status guard\n\n## Status\nDRAFTING\n\n## Tasks\n- [ ] T1: a\n- [ ] T2: b\n"
SPEC = "{tasks}/DDD-status/SPEC.md"
TICK = {"old_string": "- [ ] T1: a", "new_string": "- [x] T1: a"}
APPROVE = {"old_string": "DRAFTING", "new_string": "APPROVED"}

# `(fields, cwd, by)` sent to the `Write|Edit` hook: a spec titled for one task is never written over another task's
# spec past DRAFTING, while a DRAFTING spec's own title may change.
FILES = [
    ({"file_path": "{clean}/new.md"}, "clean", None),
    ({"file_path": "{home}/outside.md"}, "clean", None),
    ({"file_path": "{tasks}/AAA-other/SPEC.md", "content": "# Spec: Reviewer finding kind axis and confidence"},
     "clean", "spec-owner"),
    ({"file_path": "{tasks}/AAA-other/SPEC.md", "content": "# Spec: Align agent"}, "clean", "spec-owner"),
    ({"file_path": "{tasks}/AAA-other/SPEC.md", "content": "# Spec: Alignment agent tool frontmatter"},
     "clean", "spec-owner"),
    ({"file_path": "{tasks}/AAA-other/SPEC.md", "content": "# Spec: Align agent tool frontmatter with the harness"},
     "clean", None),
    ({"file_path": "{tasks}/AAA-other/SPEC.md", "content": "# Spec: Align agent tool frontmatter"}, "clean", None),
    ({"file_path": "{tasks}/AAA-other/REPORT.md", "content": "# Spec: Reviewer finding kind axis"}, "clean", None),
    ({"file_path": "{tasks}/BBB-new/SPEC.md", "content": "# Spec: Reviewer finding kind axis"}, "clean", None),
    ({"file_path": "{tasks}/CCC-fresh/SPEC.md",
      "content": "# Spec: Cut duplicated is it normal work in discovery and reporting"},
     "clean", None),
    ({"file_path": "{tasks}/CCC-fresh/SPEC.md", "content": "# Spec: Something else entirely"}, "clean", None),
    ({"file_path": "{home}/.agent/somewhere/SPEC.md", "content": "# Spec: anything at all"}, "clean", None),
    ({"file_path": SPEC, "content": STATUS_SPEC.replace("Status guard", "Retitled while drafting")}, "clean", None),
    # The Status line of an existing task spec moves only through crew-task.py; every other edit passes.
    ({"file_path": SPEC, **TICK}, "clean", None),
    ({"file_path": SPEC, **APPROVE}, "clean", "status"),
    ({"file_path": SPEC, "content": STATUS_SPEC.replace("- [ ]", "- [x]")}, "clean", None),
    ({"file_path": SPEC, "content": STATUS_SPEC.replace("DRAFTING", "APPROVED")}, "clean", "status"),
    # A new spec is born DRAFTING (or with no Status yet), never already approved.
    ({"file_path": "{tasks}/BBB-new/SPEC.md", "content": STATUS_SPEC.replace("DRAFTING", "APPROVED")},
     "clean", "status"),
    ({"file_path": "{tasks}/BBB-new/SPEC.md", "content": STATUS_SPEC}, "clean", None),
    # The one reader decides: a CR heading before the real one, a lone CR read as a newline, or a blank
    # line and a second section.
    ({"file_path": SPEC, "old_string": "# Spec: Status guard\n",
      "new_string": "# Spec: Status guard\r## Status\rAPPROVED\r\n"}, "clean", "status"),
    ({"file_path": SPEC, "old_string": "## Status\nDRAFTING",
      "new_string": "## Status\r\nAPPROVED\n\n## Status\nDRAFTING"}, "clean", "status"),
    ({"file_path": SPEC, "content": STATUS_SPEC.replace("## Status\n", "## Status\n\n") + "\n## Status\nAPPROVED\n"},
     "clean", "status"),
    # The path is resolved and the name compared case-insensitively.
    ({"file_path": "{tasks}/DDD-status/../DDD-status/SPEC.md", **APPROVE}, "clean", "status"),
    ({"file_path": "{tasks}//DDD-status/SPEC.md", **APPROVE}, "clean", "status"),
    ({"file_path": "{home}/linked-task/SPEC.md", **APPROVE}, "clean", "status"),
    # An Edit applies exactly as the tool applies it, or is refused; MultiEdit edits apply in order.
    ({"file_path": SPEC, "old_string": "not in the file", "new_string": "x"}, "clean", "status"),
    ({"file_path": SPEC, "old_string": "- [ ]", "new_string": "- [x]"}, "clean", "status"),
    ({"file_path": SPEC, "old_string": "- [ ]", "new_string": "- [x]", "replace_all": True}, "clean", None),
    ({"file_path": SPEC, "edits": [TICK]}, "clean", None),
    ({"file_path": SPEC, "edits": [TICK, APPROVE]}, "clean", "status"),
    ({"file_path": SPEC}, "clean", "status"),
    # The tool decides which fields are read: another tool's fields, or an unknown tool, are refused.
    ({"tool_name": "Write", "file_path": SPEC, "content": STATUS_SPEC.replace("DRAFTING", "APPROVED"), "edits": [TICK]},
     "clean", "status"),
    ({"tool_name": "Edit", "file_path": SPEC, **TICK, "content": STATUS_SPEC}, "clean", "status"),
    ({"tool_name": "NotebookEdit", "file_path": SPEC, "content": STATUS_SPEC}, "clean", "status"),
    # A Delete of a task record (Cursor's `preToolUse` matcher names it; its path key is undocumented).
    ({"tool_name": "Delete", "file_path": SPEC}, "clean", "task-files"),
    ({"tool_name": "Delete", "path": "{tasks}/DDD-status/PROGRESS.md"}, "clean", "task-files"),
    ({"tool_name": "Delete", "target_file": "{tasks}/DDD-status/.task-id"}, "clean", "task-files"),
    # Evidence files are the TAMPERED check's: an edit passes.
    ({"file_path": "{tasks}/DDD-status/PROGRESS.md", "content": "x\n"}, "clean", None),
    ({"file_path": "{tasks}/DDD-status/review/1/adversarial.in.md", "content": "brief"}, "clean", None),
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

# Rule scripts whose stdout is their product: only their failure handling is checked here.
SILENT = ("mode-anchor.sh", "memory-context.sh", "notify-idle.sh", "log-tool-use.sh", "memory-capture-prompt.sh",
          "spec-status-reconcile.sh", "record-pr.sh", "capture-reply.sh", "agents-refresh.sh", "usage.sh")

# `notify-idle.sh` under a stub `osascript`: `(label, env, seconds since this session's last banner or None, calls)`.
NOTIFY = [
    ("a background job", {"CLAUDE_JOB_DIR": "/tmp/job"}, None, 0),
    ("the off switch", {"EL_CAPITAN_NOTIFY": "off"}, None, 0),
    ("a first idle in a session", {}, None, 1),
    ("a second idle within 10 minutes", {}, 60, 0),
    ("an idle 10 minutes after the last banner", {}, 600, 1),
]
