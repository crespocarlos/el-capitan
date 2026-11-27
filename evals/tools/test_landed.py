#!/usr/bin/env python3
"""`crew ls`: `landed` from the PR record, and `--watch` redrawing the table read-only.

`ls_data` (shared with a TUI) is driven with stubbed readers, an injected sleep and clock; a real
`crew-ls.py --watch` is read until it has drawn twice, then interrupted. A DONE task is `yes`, `no`,
or `unknown`, from the PR record (base, state, merge commit), not from branch ancestry, which is false
for squash merges. No test calls the real GitHub: the decision functions take a stubbed reader, and
the end-to-end cases put a fake `gh` first on PATH.
"""
from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
TASK_TOOLS = ROOT / ".agent" / "tools" / "task"
sys.path.insert(0, str(TASK_TOOLS))
sys.path.insert(0, str(TASK_TOOLS.parent))

import ls_data  # noqa: E402

URL = "https://github.com/acme/widgets/pull/51"
SHA = "a" * 40
BACKPORT = [r"^\d+\.\d+$", r"^\d+\.x$"]
ANY = object()


def check(name: str, condition: bool, detail: object = "") -> None:
    assert condition, f"{name}: {detail}"


def task_with_pr(base: Path, url: str | None = URL) -> Path:
    task = base / "task"
    task.mkdir(parents=True, exist_ok=True)
    (task / "SPEC.md").write_text("# Probe\n\n## Status\nDONE\n\n- [x] one\n", encoding="utf-8")
    line = f"[2026-01-01 00:00:00] TRANSITION: IMPLEMENTING → DONE (PR opened: {url})\n" if url else ""
    (task / "PROGRESS.md").write_text(line, encoding="utf-8")
    return task


def reader(state: str, base: str, default: str = "main", sha: str | None = SHA, fail: bool = False):
    """A stand-in for `crew-pr-actions.py`: the PR record and the repository record."""
    def read(arguments: list[str]) -> tuple[int, str]:
        if fail:
            return 1, ""
        if arguments[0] == "view":
            return 0, json.dumps({"state": state, "baseRefName": base,
                                  "mergeCommit": {"oid": sha} if sha else None})
        return 0, json.dumps({"defaultBranchRef": {"name": default}})
    return read


def never(_sha: str, _ref: str) -> bool:
    raise AssertionError("no ancestry needed")


HERE = lambda: {"acme/widgets": "origin"}  # the current directory's remotes, for tasks whose PR is acme/widgets
FORK = lambda: {"me/widgets": "origin", "acme/widgets": "upstream"}  # origin is the user's fork, the PR targets upstream
REACH = {"yes": lambda s, d: True, "no": lambda s, d: False, "stale": lambda s, d: None, "never": never}

# (case, state, base, merge sha, reader fails, reachability, landing bases, landed, flag: "" exact or a fragment, note)
DECISIONS = [
    ("merge into a parent branch is no and flagged", "MERGED", "feat/parent", SHA, False, "no", [], "no", "feat/parent, not main", ANY),
    ("merge commit into the default is yes, not flagged", "MERGED", "main", SHA, False, "never", [], "yes", "", ANY),
    ("squash merge into default is yes via the PR record", "MERGED", "main", "c" * 40, False, "no", [], "yes", ANY, ANY),
    ("PR record unavailable is unknown", "MERGED", "main", SHA, True, "yes", [], "unknown", "", ANY),
    ("a default branch that cannot be refreshed is unknown", "MERGED", "feat/parent", SHA, False, "stale", [], "unknown", ANY, ANY),
    ("a stack merged on afterwards is yes by reachability", "MERGED", "feat/parent", SHA, False, "yes", [], "yes", ANY, ANY),
    ("an open PR on a non-default base is no and flagged", "OPEN", "feat/parent", SHA, False, "yes", [], "no", "open into feat/parent", ANY),
    ("an open PR on the default is no and not flagged", "OPEN", "main", SHA, False, "yes", [], "no", "", None),
    ("a closed PR is no and not flagged", "CLOSED", "feat/parent", SHA, False, "yes", [], "no", "", None),
    ("merged into another base with no merge commit is no", "MERGED", "feat/parent", None, False, "yes", [], "no", ANY, ANY),
    ("a merge into a landing base is yes, worded as a backport", "MERGED", "9.x", SHA, False, "never", BACKPORT, "yes", "", "backport to 9.x"),
    ("every landing base pattern counts", "MERGED", "9.1", SHA, False, "never", BACKPORT, "yes", ANY, ANY),
    ("landing bases leave a parent-branch merge no and flagged", "MERGED", "feat/parent", SHA, False, "no", BACKPORT, "no", "feat/parent", None),
    ("a landing base pattern matches the whole name", "MERGED", "feat/9.x-fix", SHA, False, "no", BACKPORT, "no", ANY, ANY),
    ("an open PR into a landing base is no and not flagged", "OPEN", "9.x", SHA, False, "never", BACKPORT, "no", "", None),
    ("without landing bases a release-branch merge is no and flagged", "MERGED", "9.x", SHA, False, "no", [], "no", "9.x", ANY),
    ("a merge into the default carries no backport note", "MERGED", "main", SHA, False, "never", BACKPORT, "yes", "", None),
]


@pytest.mark.parametrize("case,state,base,sha,fail,reach,patterns,landed,flag,note", DECISIONS, ids=[row[0] for row in DECISIONS])
def test_landed_decision(case: str, state: str, base: str, sha: str | None, fail: bool, reach: str, patterns: list[str], landed: str,
                         flag: object, note: object, tmp: Path) -> None:
    row = ls_data.landed_row(task_with_pr(tmp), reader(state, base, sha=sha, fail=fail), REACH[reach], patterns, local=HERE)
    assert row["landed"] == landed, row
    assert flag is ANY or (flag in row["flag"] if flag else row["flag"] == ""), row
    assert note is ANY or row.get("note") == note, row


def test_a_task_with_no_recorded_pr_is_unknown(tmp: Path) -> None:
    assert ls_data.landed_row(task_with_pr(tmp, None), reader("MERGED", "main"))["landed"] == "unknown"


def test_another_repositorys_pr(tmp: Path) -> None:
    """Reachability and `landing_bases` belong to the cwd repository: another repo's PR is unknown, never a wrong no."""
    elsewhere = lambda: {"someone/else": "origin", "someone/upstream": "upstream"}
    other = ls_data.landed_row(task_with_pr(tmp / "a"), reader("MERGED", "feat/parent"), never, BACKPORT, local=elsewhere)
    check("a merge into a non-default base of another repo is unknown", other["landed"] == "unknown", other)
    backport = ls_data.landed_row(task_with_pr(tmp / "b"), reader("MERGED", "9.x"), never, BACKPORT, local=elsewhere)
    check("another repo's landing_bases are not borrowed from the cwd repo", backport["landed"] == "unknown" and "note" not in backport, backport)
    plain = ls_data.landed_row(task_with_pr(tmp / "c"), reader("MERGED", "main"), never, BACKPORT, local=elsewhere)
    check("a merge into the default branch is still yes (the PR record is the answer)", plain["landed"] == "yes", plain)
    check("no origin at all counts as another repo", ls_data.landed_row(task_with_pr(tmp / "d"), reader("MERGED", "feat/parent"), never,
                                                                          [], local=lambda: {})["landed"] == "unknown")
    check("a matching origin keeps the old answer", ls_data.landed_row(task_with_pr(tmp / "e"), reader("MERGED", "feat/parent"),
                                                                         lambda s, d: False, [], local=HERE)["landed"] == "no")
    slugs = [ls_data.repo_slug(u) for u in ("https://github.com/Acme/Widgets.git", "git@github.com:acme/widgets.git", "ssh://git@github.com/acme/widgets")]
    check("origin URLs normalise to owner/repo", slugs == ["acme/widgets"] * 3, slugs)


def test_the_fork_workflow(tmp: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A PR into upstream counts as local, and reachability reads `upstream/<default>`."""
    asked: list[str] = []
    reach = lambda sha, ref: asked.append(ref) or True
    stacked = ls_data.landed_row(task_with_pr(tmp / "a"), reader("MERGED", "feat/parent"), reach, [], local=FORK)
    check("a stacked PR into upstream merged on afterwards is yes", stacked["landed"] == "yes", stacked)
    check("reachability is asked of upstream/main, not origin/main", asked == ["upstream/main"], asked)
    backport = ls_data.landed_row(task_with_pr(tmp / "b"), reader("MERGED", "9.x"), reach, BACKPORT, local=FORK)
    check("a backport into upstream's landing base is yes with its note, not flagged",
          backport == {"landed": "yes", "flag": "", "note": "backport to 9.x"}, backport)
    rows = ls_data.landed_rows([task_with_pr(tmp / "c")], reader("MERGED", "feat/parent"), lambda s, r: None, [], FORK)
    check("not reachable in local refs stays unknown, never no", rows[0]["landed"] == "unknown", rows)
    repo = tmp / "repo"
    repo.mkdir(parents=True)
    git(repo, "init", "-q", "-b", "main")
    git(repo, "remote", "add", "origin", "git@github.com:me/widgets.git")
    git(repo, "remote", "add", "upstream", "https://github.com/acme/widgets.git")
    monkeypatch.chdir(repo)
    found = ls_data.local_remotes()
    check("local_remotes maps origin and upstream to their owner/repo", found == {"me/widgets": "origin", "acme/widgets": "upstream"}, found)


def git(root: Path, *arguments: str) -> str:
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
           "GIT_COMMITTER_EMAIL": "t@t", "GIT_CONFIG_GLOBAL": "/dev/null"}
    done = subprocess.run(["git", "-C", str(root), *arguments], capture_output=True, text=True, env=env)
    if done.returncode:
        raise RuntimeError(done.stderr)
    return done.stdout.strip()


def fake_gh(directory: Path, body: str = "  *) exit 1 ;;\n", log: Path | None = None) -> Path:
    """A `gh` that answers `pr view` and `repo view` from `body` (a case list) and fails everything else."""
    directory.mkdir(parents=True, exist_ok=True)
    script = directory / "gh"
    record = f'echo "$@" >> "{log}"\n' if log else ""
    script.write_text(f'#!/bin/sh\n{record}case "$1 $2" in\n{body}esac\n', encoding="utf-8")
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return directory


def merged_into(base: str) -> str:
    return ('  "pr view") echo \'{"state":"MERGED","baseRefName":"' + base + '","mergeCommit":{"oid":"' + SHA + '"}}\' ;;\n'
            '  "repo view") echo \'{"defaultBranchRef":{"name":"main"}}\' ;;\n'
            "  *) exit 1 ;;\n")


def test_a_stale_origin_is_unknown_and_never_fetched(tmp: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """`origin/main` is behind the server: the listing never fetches, so the answer is unknown, not no."""
    remote, clone, other = tmp / "remote.git", tmp / "clone", tmp / "other"
    subprocess.run(["git", "init", "--bare", "-b", "main", str(remote)], capture_output=True, check=True)
    subprocess.run(["git", "clone", str(remote), str(clone)], capture_output=True, check=True)
    git(clone, "commit", "--allow-empty", "-m", "one")
    git(clone, "push", "origin", "HEAD:main")
    subprocess.run(["git", "clone", str(remote), str(other)], capture_output=True, check=True)
    git(other, "commit", "--allow-empty", "-m", "merged work")
    merged = git(other, "rev-parse", "HEAD")
    git(other, "push", "origin", "HEAD:main")
    monkeypatch.setenv("PATH", f"{fake_gh(tmp / 'bin')}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.chdir(clone)
    check("the listing never fetches: a stale origin/main is unknown, not no",
          ls_data.reachable_from(merged, "origin/main") is None)
    check("the listing left the stale clone as it was (no fetch)",
          subprocess.run(["git", "cat-file", "-e", merged], capture_output=True).returncode != 0)
    git(clone, "fetch", "-q", "origin")
    check("a commit already in origin/main is reachable", ls_data.reachable_from(merged, "origin/main") is True)


def copy_task(source: Path, task: Path, slug: str, branch: str) -> None:
    task.mkdir(parents=True)
    for name in ("SPEC.md", "PROGRESS.md"):
        (task / name).write_text((source / name).read_text(encoding="utf-8"), encoding="utf-8")
    (task / ".task-id").write_text(json.dumps({"slug": slug, "branch": branch}), encoding="utf-8")


def test_crew_ls_all_with_a_fake_gh(tmp: Path) -> None:
    """`crew-ls.py --all`: the table line, the JSON field, and the argv gh saw."""
    tasks, log = tmp / "tasks", tmp / "gh.log"
    copy_task(task_with_pr(tmp / "e2e"), tasks / "11111111-1111-1111-1111-111111111111", "stacked", "feat/x")
    env = {**os.environ, "PATH": f"{fake_gh(tmp / 'gh-bin', merged_into('feat/parent'), log)}{os.pathsep}{os.environ['PATH']}"}
    # The merge commit is not in this scratch repository, so reachability cannot confirm it: unknown or no,
    # never yes. The flag line is the point of this case.
    run = lambda *extra: subprocess.run([sys.executable, str(TASK_TOOLS / "crew-ls.py"), "--tasks-dir", str(tasks), *extra],
                                        capture_output=True, text=True, env=env, cwd=tmp)
    table = run("--all")
    check("crew ls --all prints a landed line for a DONE task", "stacked  landed:" in table.stdout, table)
    check("the non-default base is flagged in the listing", "merged into feat/parent, not main" in table.stdout, table.stdout)
    check("the merged-into-a-parent task is never yes", "landed: yes" not in table.stdout, table.stdout)
    data = json.loads(run("--all", "--json").stdout)
    check("--json carries landed and flag for the DONE task",
          data[0].get("landed") in ("no", "unknown") and "feat/parent" in data[0].get("flag", ""), data)
    calls = log.read_text(encoding="utf-8")
    check("gh saw `pr view 51 --repo acme/widgets`", "pr view 51 --repo acme/widgets --json state,baseRefName,mergeCommit" in calls, calls)
    check("gh saw the repository positionally", "repo view acme/widgets --json defaultBranchRef" in calls, calls)
    check("without --all the listing makes no landed read", "landed" not in run().stdout)


def test_landing_bases_are_read_from_the_repository(tmp: Path) -> None:
    line = "# Repo\n\nlanding_bases: ^\\d+\\.\\d+$ `^\\d+\\.x$`\n"
    check("a landing_bases line lists patterns separated by spaces", ls_data.parse(line) == BACKPORT, ls_data.parse(line))
    block = "# Repo\n\n```landing_bases\n^\\d+\\.\\d+$\n# release lines\n^\\d+\\.x$\n```\n"
    check("a fenced landing_bases block lists one pattern per line", ls_data.parse(block) == BACKPORT, ls_data.parse(block))
    check("no setting means no patterns", ls_data.parse("# Repo\nnothing\n") == [])
    check("a broken regex is dropped, not fatal", ls_data.parse("landing_bases: ( ^ok$\n") == ["^ok$"])
    check("matching is a full match", ls_data.matches("9.x", BACKPORT) and not ls_data.matches("v9.x", BACKPORT))
    line_out = ls_data.landed_lines([("fix-it", task_with_pr(tmp / "h"))], reader("MERGED", "9.x"), lambda s, d: False, BACKPORT, HERE)
    check("the listing line reads `landed: yes (backport to 9.x)`", line_out == ["  fix-it  landed: yes (backport to 9.x)"], line_out)
    root = tmp / "repo"
    root.mkdir(parents=True)
    git(root, "init", "-q", "-b", "main")
    (root / "AGENTS.md").write_text(line, encoding="utf-8")
    check("the repo's AGENTS.md is read from its root", ls_data.load_bases(root) == BACKPORT, ls_data.load_bases(root))
    check("a directory with no repo has no patterns", ls_data.load_bases(tmp / "nowhere") == [])


def test_crew_ls_all_reads_the_landing_bases_of_its_repository(tmp: Path) -> None:
    """`crew-ls.py --all` run inside a repo whose AGENTS.md declares the landing bases, gh faked."""
    repo, tasks = tmp / "repo", tmp / "tasks"
    repo.mkdir(parents=True)
    git(repo, "init", "-q", "-b", "main")
    git(repo, "remote", "add", "origin", "https://github.com/acme/widgets.git")
    (repo / "AGENTS.md").write_text("landing_bases: ^\\d+\\.x$\n", encoding="utf-8")
    copy_task(task_with_pr(tmp / "src"), tasks / "22222222-2222-2222-2222-222222222222", "backport", "fix/x")
    env = {**os.environ, "PATH": f"{fake_gh(tmp / 'bin', merged_into('9.x'))}{os.pathsep}{os.environ['PATH']}"}
    shown = subprocess.run([sys.executable, str(TASK_TOOLS / "crew-ls.py"), "--tasks-dir", str(tasks), "--all"],
                           capture_output=True, text=True, env=env, cwd=repo)
    check("crew ls --all prints `landed: yes (backport to 9.x)`", "backport  landed: yes (backport to 9.x)" in shown.stdout, shown)
    check("a backport is not flagged as a non-default base", "not main" not in shown.stdout, shown.stdout)
    data = json.loads(subprocess.run([sys.executable, str(TASK_TOOLS / "crew-ls.py"), "--tasks-dir", str(tasks), "--all", "--json"],
                                     capture_output=True, text=True, env=env, cwd=repo).stdout)
    check("--json carries landed yes and the note", data[0].get("landed") == "yes" and data[0].get("note") == "backport to 9.x", data)


# --- crew ls --watch: the table redrawn every N seconds, read-only -------------------------------

CLEAR = "\x1b[2J\x1b[H"


def make_tasks(base: Path) -> Path:
    tasks = base / "tasks"
    for uuid, slug, status in (("11111111-1111-1111-1111-111111111111", "shipped", "DONE"),
                               ("22222222-2222-2222-2222-222222222222", "building", "IMPLEMENTING")):
        task = tasks / uuid
        task.mkdir(parents=True)
        (task / "SPEC.md").write_text(f"# Spec: {slug}\n\n## Status\n{status}\n\n- [x] one\n- [ ] two\n", encoding="utf-8")
        (task / ".task-id").write_text(json.dumps({"slug": slug, "branch": f"feat/{slug}"}), encoding="utf-8")
        (task / "PROGRESS.md").write_text("BLOCKED: waiting\n" if slug == "building" else "", encoding="utf-8")
    return tasks


def digest(tasks: Path) -> str:
    return "".join(f"{path}:{path.read_bytes()!r}" for path in sorted(tasks.rglob("*")) if path.is_file())


def test_gather(tmp: Path) -> None:
    """`ls_data.gather`, shared with a TUI: every row, the BLOCKED lines, landed reads only for shown DONE tasks."""
    tasks = make_tasks(tmp)
    snapshot = ls_data.gather(tasks, show_done=False)
    check("gather returns every task row and the open tasks' BLOCKED lines, and reads no landed state",
          sorted(r.task.name[:8] for r in snapshot.rows) == ["11111111", "22222222"]
          and any("BLOCKED: waiting" in line for line in snapshot.blocked) and snapshot.landed == [], snapshot)
    seen: list[list[str]] = []
    shown = ls_data.gather(tasks, show_done=True, landed=lambda rows: seen.append([n for n, _ in rows]) or ["  shipped  landed: unknown"])
    check("with done tasks shown, only DONE tasks are read for landed", seen == [["shipped"]] and shown.landed == ["  shipped  landed: unknown"], seen)
    check("a directory with no tasks gathers nothing", ls_data.gather(tmp / "empty", False).rows == [])


def test_limit_and_cache(tmp: Path) -> None:
    """`--limit` bounds the landed reads, a repository is asked once, and a watch loop re-reads on a TTL."""
    tasks = tmp / "tasks"
    for index in range(4):
        task = tasks / f"{index:08d}-1111-1111-1111-111111111111"
        task.mkdir(parents=True)
        (task / "SPEC.md").write_text(f"# Spec: d{index}\n\n## Status\nDONE\n\n- [x] one\n", encoding="utf-8")
        (task / ".task-id").write_text(json.dumps({"slug": f"d{index}", "branch": f"feat/d{index}"}), encoding="utf-8")
        (task / "PROGRESS.md").write_text(f"[2026-01-01 00:00:00] TRANSITION: IMPLEMENTING → DONE (PR opened: https://github.com/acme/w/pull/{index + 1})\n",
                                          encoding="utf-8")
    seen: list[list[str]] = []

    def stub(rows: list) -> list[str]:
        seen.append([n for n, _ in rows])
        return [f"  {n}  landed: no" for n, _ in rows]

    ls_data.gather(tasks, show_done=True, landed=stub, limit=2)
    ls_data.gather(tasks, show_done=True, landed=stub)
    check("--limit is applied before the landed reads; without one every DONE task is read", [len(s) for s in seen] == [2, 4], seen)
    calls: list[list[str]] = []

    def read(arguments: list[str]) -> tuple[int, str]:
        calls.append(arguments)
        if arguments[0] == "view":
            return 0, json.dumps({"state": "OPEN", "baseRefName": "main", "mergeCommit": None})
        return 0, json.dumps({"defaultBranchRef": {"name": "main"}})

    pairs = [(f"d{i}", t) for i, t in enumerate(sorted(tasks.iterdir()))]
    ls_data.landed_lines(pairs, read, lambda s, d: None, [], lambda: {"acme/w": "origin"})
    check("`repo view` is asked once per repository in one snapshot", [c[0] for c in calls].count("repo") == 1 and [c[0] for c in calls].count("view") == 4, calls)
    now, reads = [0.0], []
    cache = ls_data.LandedCache(ttl=60.0, clock=lambda: now[0], landed=lambda rows: reads.append([n for n, _ in rows]) or [f"  {n}  landed: no" for n, _ in rows])
    first = cache.lines(pairs)
    now[0] = 30.0
    cache.lines(pairs)
    check("inside the TTL the cached lines are reused, in order", len(reads) == 1 and first == [f"  d{i}  landed: no" for i in range(4)], reads)
    now[0] = 61.0
    cache.lines(pairs[:2])
    check("past the TTL only the stale tasks are read again", len(reads) == 2 and reads[1] == ["d0", "d1"], reads)


def test_the_watch_loop() -> None:
    """`ls_data.watch` with an injected sleep and clear: render into a buffer, clear, sleep; Ctrl-C is exit 0."""
    events: list[str] = []
    code = ls_data.watch(lambda: events.append("render"), interval=2.5, sleep=lambda s: events.append(f"sleep {s}"),
                         clear=lambda: events.append("clear"), max_iterations=3)
    check("the loop renders, clears only when ready, sleeps, and stops at max_iterations; the default interval is 3 s",
          events == ["render", "clear", "sleep 2.5"] * 2 + ["render", "clear"] and code == 0 and ls_data.DEFAULT_INTERVAL == 3.0, events)

    def interrupted(_seconds: float) -> None:
        raise KeyboardInterrupt

    def raising() -> None:
        raise KeyboardInterrupt

    events.clear()
    check("Ctrl-C during the wait or a render ends the loop with exit 0",
          ls_data.watch(lambda: events.append("render"), sleep=interrupted, clear=lambda: None) == 0 and events == ["render"]
          and ls_data.watch(raising, sleep=lambda s: None, clear=lambda: None) == 0)
    check("zero iterations draw nothing", ls_data.watch(lambda: events.append("x"), max_iterations=0, clear=lambda: events.append("c")) == 0
          and "x" not in events)


def test_the_watch_command(tmp: Path) -> None:
    """A real `crew-ls.py --watch` draws twice, takes a SIGINT, exits 0, and leaves the task files alone."""
    import selectors
    import signal

    tasks = make_tasks(tmp)
    before = digest(tasks)
    command = [sys.executable, str(TASK_TOOLS / "crew-ls.py"), "--tasks-dir", str(tasks)]
    child = subprocess.Popen([*command, "--watch", "--interval", "0.05"], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    drawn, selector = b"", selectors.DefaultSelector()
    selector.register(child.stdout, selectors.EVENT_READ)
    while drawn.count(CLEAR.encode()) < 2 and selector.select(timeout=20):
        drawn += os.read(child.stdout.fileno(), 65536)
    child.send_signal(signal.SIGINT)
    try:
        out, err = child.communicate(timeout=20)
    except subprocess.TimeoutExpired:
        child.kill()
        out, err = child.communicate()
    text = (drawn + out).decode()
    check("Ctrl-C exits 0 with no traceback, after clearing before each draw of the same table",
          child.returncode == 0 and b"Traceback" not in err and text.count(CLEAR) >= 2 and "building" in text and "BLOCKED: waiting" in text,
          (child.returncode, err[-300:], text[:300]))
    check("watching is read-only", digest(tasks) == before)
    plain = subprocess.run(command, capture_output=True, text=True)
    check("without --watch nothing is cleared", "\x1b[2J" not in plain.stdout and "building" in plain.stdout, plain.stdout)
    missing = subprocess.run([sys.executable, str(TASK_TOOLS / "crew-ls.py"), "--cost", "--tasks-dir", str(tmp / "nowhere")], capture_output=True, text=True)
    check("--cost with no tasks directory prints the error on stderr, exit 2",
          missing.returncode == 2 and missing.stdout == "" and "no tasks directory" in missing.stderr, missing)
    for bad in (["--watch", "--interval", "0"], ["--watch", "--json"], ["--interval", "5"]):
        check(f"{' '.join(bad)} is refused", subprocess.run([*command, *bad], capture_output=True, text=True).returncode == 2)
