#!/usr/bin/env python3
"""`landed` in `crew ls`: a DONE task is `yes`, `no`, or `unknown`, from the PR record.

`DONE` means a draft PR was opened. Stacked PRs merged into their parents looked merged and never
reached the default branch, so the verdict reads the PR record (base, state, merge commit) and not
branch ancestry, which is false for squash merges. No test calls the real GitHub: the decision
functions take a stubbed reader, and the end-to-end cases put a fake `gh` first on PATH.
"""
from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TASK_TOOLS = ROOT / ".agent" / "tools" / "task"
sys.path.insert(0, str(TASK_TOOLS))
sys.path.insert(0, str(TASK_TOOLS.parent))

import ls_data  # noqa: E402

FAILED: list[str] = []
URL = "https://github.com/acme/widgets/pull/51"
SHA = "a" * 40


def check(name: str, condition: bool, detail: object = "") -> None:
    print(("pass: " if condition else "FAIL: ") + name + ("" if condition else f": {detail}"))
    if not condition:
        FAILED.append(name)


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


HERE = lambda: {"acme/widgets": "origin"}  # the current directory's remotes, for tasks whose PR is acme/widgets


def decide(tmp: Path, read, reach=lambda sha, default: True) -> dict:
    return ls_data.landed_row(task_with_pr(tmp), read, reach, local=HERE)


def foreign_repo_case(tmp: Path) -> None:
    """Reachability and `landing_bases` belong to the cwd repository: another repo's PR is unknown, never a wrong no."""
    never = lambda s, d: (_ for _ in ()).throw(AssertionError("reachability belongs to another repository"))
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


FORK = lambda: {"me/widgets": "origin", "acme/widgets": "upstream"}  # origin is the user's fork, the PR targets upstream


def fork_case(tmp: Path) -> None:
    """The fork workflow: a PR into upstream counts as local, and reachability reads `upstream/<default>`."""
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
    cwd = os.getcwd()
    os.chdir(repo)
    try:
        found = ls_data.local_remotes()
    finally:
        os.chdir(cwd)
    check("local_remotes maps origin and upstream to their owner/repo", found == {"me/widgets": "origin", "acme/widgets": "upstream"}, found)


def decision_cases(tmp: Path) -> None:
    parent = decide(tmp / "a", reader("MERGED", "feat/parent"), lambda s, d: False)
    check("merge into a parent branch is no", parent["landed"] == "no", parent)
    check("a parent-branch merge is flagged", "feat/parent" in parent["flag"] and "main" in parent["flag"], parent)
    direct = decide(tmp / "b", reader("MERGED", "main"), lambda s, d: (_ for _ in ()).throw(AssertionError("no ancestry needed")))
    check("merge commit into the default is yes", direct["landed"] == "yes", direct)
    check("a default-base merge is not flagged", direct["flag"] == "", direct)
    squash = decide(tmp / "c", reader("MERGED", "main", sha="c" * 40), lambda s, d: False)
    check("squash merge into default is yes via the PR record", squash["landed"] == "yes", squash)
    gone = decide(tmp / "d", reader("MERGED", "main", fail=True))
    check("PR record unavailable is unknown", gone["landed"] == "unknown" and gone["flag"] == "", gone)
    stale = decide(tmp / "e", reader("MERGED", "feat/parent"), lambda s, d: None)
    check("a default branch that cannot be refreshed is unknown", stale["landed"] == "unknown", stale)
    stacked_later = decide(tmp / "f", reader("MERGED", "feat/parent"), lambda s, d: True)
    check("a stack merged on afterwards is yes by reachability", stacked_later["landed"] == "yes", stacked_later)
    opened = decide(tmp / "g", reader("OPEN", "feat/parent"))
    check("an open PR is no", opened["landed"] == "no", opened)
    check("an open PR on a non-default base is flagged", "open into feat/parent" in opened["flag"], opened)
    open_default = decide(tmp / "h", reader("OPEN", "main"))
    check("an open PR on the default is no and not flagged", open_default == {"landed": "no", "flag": ""}, open_default)
    closed = decide(tmp / "i", reader("CLOSED", "feat/parent"))
    check("a closed PR is no and not flagged", closed == {"landed": "no", "flag": ""}, closed)
    nopr = ls_data.landed_row(task_with_pr(tmp / "j", None), reader("MERGED", "main"))
    check("a task with no recorded PR is unknown", nopr["landed"] == "unknown", nopr)
    nosha = decide(tmp / "k", reader("MERGED", "feat/parent", sha=None))
    check("merged into another base with no merge commit is no", nosha["landed"] == "no", nosha)


def git(root: Path, *arguments: str) -> str:
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
           "GIT_COMMITTER_EMAIL": "t@t", "GIT_CONFIG_GLOBAL": "/dev/null"}
    done = subprocess.run(["git", "-C", str(root), *arguments], capture_output=True, text=True, env=env)
    if done.returncode:
        raise RuntimeError(done.stderr)
    return done.stdout.strip()


def fake_gh(directory: Path) -> Path:
    """A `gh` that fails everything, so a stale-origin fetch cannot reach the real GitHub."""
    directory.mkdir(parents=True, exist_ok=True)
    script = directory / "gh"
    script.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return directory


def stale_origin_case(tmp: Path) -> None:
    """`origin/main` is behind the server: reachability fetches first, and an unfetchable origin is None."""
    remote, clone, other = tmp / "remote.git", tmp / "clone", tmp / "other"
    subprocess.run(["git", "init", "--bare", "-b", "main", str(remote)], capture_output=True, check=True)
    subprocess.run(["git", "clone", str(remote), str(clone)], capture_output=True, check=True)
    git(clone, "commit", "--allow-empty", "-m", "one")
    git(clone, "push", "origin", "HEAD:main")
    subprocess.run(["git", "clone", str(remote), str(other)], capture_output=True, check=True)
    git(other, "commit", "--allow-empty", "-m", "merged work")
    merged = git(other, "rev-parse", "HEAD")
    git(other, "push", "origin", "HEAD:main")
    previous, cwd = os.environ["PATH"], os.getcwd()
    os.environ["PATH"] = f"{fake_gh(tmp / 'bin')}{os.pathsep}{previous}"
    os.chdir(clone)
    try:
        check("the stale clone does not hold the merge commit yet",
              subprocess.run(["git", "cat-file", "-e", merged], capture_output=True).returncode != 0)
        check("the listing never fetches: a stale origin/main is unknown, not no",
              ls_data.reachable_from(merged, "origin/main") is None)
        check("the listing left the stale clone as it was (no fetch)",
              subprocess.run(["git", "cat-file", "-e", merged], capture_output=True).returncode != 0)
        git(clone, "fetch", "-q", "origin")
        check("a commit already in origin/main is reachable", ls_data.reachable_from(merged, "origin/main") is True)
    finally:
        os.chdir(cwd)
        os.environ["PATH"] = previous


def end_to_end_case(tmp: Path) -> None:
    """`crew-ls.py --all` with a fake gh on PATH: the table line, the JSON field, and the argv gh saw."""
    tasks = tmp / "tasks"
    done = tasks / "11111111-1111-1111-1111-111111111111"
    task_with_pr(tmp / "e2e")
    done.mkdir(parents=True)
    for name in ("SPEC.md", "PROGRESS.md"):
        (done / name).write_text((tmp / "e2e" / "task" / name).read_text(encoding="utf-8"), encoding="utf-8")
    (done / ".task-id").write_text(json.dumps({"slug": "stacked", "branch": "feat/x"}), encoding="utf-8")
    bin_dir, log = tmp / "gh-bin", tmp / "gh.log"
    bin_dir.mkdir()
    script = bin_dir / "gh"
    script.write_text(
        "#!/bin/sh\n" f'echo "$@" >> "{log}"\n'
        'case "$1 $2" in\n'
        '  "pr view") echo \'{"state":"MERGED","baseRefName":"feat/parent","mergeCommit":{"oid":"' + SHA + '"}}\' ;;\n'
        '  "repo view") echo \'{"defaultBranchRef":{"name":"main"}}\' ;;\n'
        "  *) exit 1 ;;\nesac\n", encoding="utf-8")
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    env = {**os.environ, "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}"}
    # The merge commit is not in this scratch repository, so reachability cannot confirm it: unknown or no,
    # never yes. The flag line is the point of this case.
    run = lambda *extra: subprocess.run([sys.executable, str(TASK_TOOLS / "crew-ls.py"), "--tasks-dir", str(tasks), "--all", *extra],
                                        capture_output=True, text=True, env=env, cwd=tmp)
    table = run()
    check("crew ls --all prints a landed line for a DONE task", "stacked  landed:" in table.stdout, table)
    check("the non-default base is flagged in the listing", "merged into feat/parent, not main" in table.stdout, table.stdout)
    check("the merged-into-a-parent task is never yes", "landed: yes" not in table.stdout, table.stdout)
    data = json.loads(run("--json").stdout)
    check("--json carries landed and flag for the DONE task",
          data[0].get("landed") in ("no", "unknown") and "feat/parent" in data[0].get("flag", ""), data)
    calls = log.read_text(encoding="utf-8")
    check("gh saw `pr view 51 --repo acme/widgets`", "pr view 51 --repo acme/widgets --json state,baseRefName,mergeCommit" in calls, calls)
    check("gh saw the repository positionally", "repo view acme/widgets --json defaultBranchRef" in calls, calls)
    plain = subprocess.run([sys.executable, str(TASK_TOOLS / "crew-ls.py"), "--tasks-dir", str(tasks)],
                           capture_output=True, text=True, env=env, cwd=tmp)
    check("without --all the listing makes no landed read", "landed" not in plain.stdout, plain.stdout)


def closing_text_case() -> None:
    """The close of `crew open pr` (data, not an always-on rule) names merged-but-not-landed."""
    rules = json.loads((TASK_TOOLS / "next-steps.json").read_text(encoding="utf-8"))["rules"]
    why = rules["build.open-pr.opened"]["why"]
    check("the open-pr close mentions merged but not landed", "merged but not landed" in why and "landed: no" in why, why)
    router = (ROOT / "rules" / "crew-orchestrator.mdc").read_text(encoding="utf-8")
    check("the always-on session line is unchanged", "Active task: **<slug>** (<STATE>). Next:" in router)


BACKPORT = [r"^\d+\.\d+$", r"^\d+\.x$"]


def backport_cases(tmp: Path) -> None:
    """`landing_bases`: release branches are normal bases for a repo that says so (Kibana: 8.x, 9.x, 9.1)."""
    fixed = lambda s, d: (_ for _ in ()).throw(AssertionError("no ancestry needed"))
    merged = decide_with(tmp / "a", reader("MERGED", "9.x"), BACKPORT, fixed)
    check("a merged PR into a landing base is yes", merged["landed"] == "yes", merged)
    check("it is worded as a backport", merged.get("note") == "backport to 9.x", merged)
    check("a landing base is not flagged", merged["flag"] == "", merged)
    check("the version-number form matches too", decide_with(tmp / "b", reader("MERGED", "9.1"), BACKPORT, fixed)["landed"] == "yes")
    stacked = decide_with(tmp / "c", reader("MERGED", "feat/parent"), BACKPORT, lambda s, d: False)
    check("a stacked PR into any other base is still no", stacked["landed"] == "no" and "note" not in stacked, stacked)
    check("and still flagged", "feat/parent" in stacked["flag"], stacked)
    check("a name that only contains a pattern is not a landing base",
          decide_with(tmp / "d", reader("MERGED", "feat/9.x-fix"), BACKPORT, lambda s, d: False)["landed"] == "no")
    opened = decide_with(tmp / "e", reader("OPEN", "9.x"), BACKPORT, fixed)
    check("an open PR into a landing base is no and not flagged", opened == {"landed": "no", "flag": ""}, opened)
    unset = decide_with(tmp / "f", reader("MERGED", "9.x"), [], lambda s, d: False)
    check("with no landing_bases the default branch is the only normal base", unset["landed"] == "no" and "9.x" in unset["flag"], unset)
    default = decide_with(tmp / "g", reader("MERGED", "main"), BACKPORT, fixed)
    check("a default-base merge is plain yes, no backport note", default == {"landed": "yes", "flag": ""}, default)
    line = ls_data.landed_lines([("fix-it", task_with_pr(tmp / "h"))], reader("MERGED", "9.x"), lambda s, d: False, BACKPORT, HERE)
    check("the listing line reads `landed: yes (backport to 9.x)`", line == ["  fix-it  landed: yes (backport to 9.x)"], line)


def decide_with(tmp: Path, read, patterns: list[str], reach) -> dict:
    return ls_data.landed_row(task_with_pr(tmp), read, reach, patterns, local=HERE)


def landing_bases_parse(tmp: Path) -> None:
    line = "# Repo\n\nlanding_bases: ^\\d+\\.\\d+$ `^\\d+\\.x$`\n"
    check("a landing_bases line lists patterns separated by spaces", ls_data.parse(line) == BACKPORT, ls_data.parse(line))
    block = "# Repo\n\n```landing_bases\n^\\d+\\.\\d+$\n# release lines\n^\\d+\\.x$\n```\n"
    check("a fenced landing_bases block lists one pattern per line", ls_data.parse(block) == BACKPORT, ls_data.parse(block))
    check("no setting means no patterns", ls_data.parse("# Repo\nnothing\n") == [])
    check("a broken regex is dropped, not fatal", ls_data.parse("landing_bases: ( ^ok$\n") == ["^ok$"])
    check("matching is a full match", ls_data.matches("9.x", BACKPORT) and not ls_data.matches("v9.x", BACKPORT))
    root = tmp / "repo"
    root.mkdir(parents=True)
    git(root, "init", "-q", "-b", "main")
    (root / "AGENTS.md").write_text(line, encoding="utf-8")
    check("the repo's AGENTS.md is read from its root", ls_data.load_bases(root) == BACKPORT, ls_data.load_bases(root))
    check("a directory with no repo has no patterns", ls_data.load_bases(tmp / "nowhere") == [])


def backport_end_to_end(tmp: Path) -> None:
    """`crew-ls.py --all` run inside a repo whose AGENTS.md declares the landing bases, gh faked."""
    repo, tasks = tmp / "repo", tmp / "tasks"
    repo.mkdir(parents=True)
    git(repo, "init", "-q", "-b", "main")
    git(repo, "remote", "add", "origin", "https://github.com/acme/widgets.git")
    (repo / "AGENTS.md").write_text("landing_bases: ^\\d+\\.x$\n", encoding="utf-8")
    task = tasks / "22222222-2222-2222-2222-222222222222"
    task_with_pr(tmp / "src")
    task.mkdir(parents=True)
    for name in ("SPEC.md", "PROGRESS.md"):
        (task / name).write_text((tmp / "src" / "task" / name).read_text(encoding="utf-8"), encoding="utf-8")
    (task / ".task-id").write_text(json.dumps({"slug": "backport", "branch": "fix/x"}), encoding="utf-8")
    bin_dir = tmp / "bin"
    bin_dir.mkdir()
    script = bin_dir / "gh"
    script.write_text(
        "#!/bin/sh\n"
        'case "$1 $2" in\n'
        '  "pr view") echo \'{"state":"MERGED","baseRefName":"9.x","mergeCommit":{"oid":"' + SHA + '"}}\' ;;\n'
        '  "repo view") echo \'{"defaultBranchRef":{"name":"main"}}\' ;;\n'
        "  *) exit 1 ;;\nesac\n", encoding="utf-8")
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    env = {**os.environ, "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}"}
    shown = subprocess.run([sys.executable, str(TASK_TOOLS / "crew-ls.py"), "--tasks-dir", str(tasks), "--all"],
                           capture_output=True, text=True, env=env, cwd=repo)
    check("crew ls --all prints `landed: yes (backport to 9.x)`", "backport  landed: yes (backport to 9.x)" in shown.stdout, shown)
    check("a backport is not flagged as a non-default base", "not main" not in shown.stdout, shown.stdout)
    data = json.loads(subprocess.run([sys.executable, str(TASK_TOOLS / "crew-ls.py"), "--tasks-dir", str(tasks), "--all", "--json"],
                                     capture_output=True, text=True, env=env, cwd=repo).stdout)
    check("--json carries landed yes and the note", data[0].get("landed") == "yes" and data[0].get("note") == "backport to 9.x", data)


def main() -> int:
    closing_text_case()
    with tempfile.TemporaryDirectory() as raw:
        tmp = Path(raw)
        backport_cases(tmp / "backport")
        landing_bases_parse(tmp / "bases")
        backport_end_to_end(tmp / "backport-e2e")
        decision_cases(tmp / "decide")
        foreign_repo_case(tmp / "foreign")
        try:
            fork_case(tmp / "fork")
        except (AttributeError, TypeError, RuntimeError) as error:
            check("fork case", False, f"{type(error).__name__}: {error}")
        try:
            stale_origin_case(tmp / "stale")
        except (RuntimeError, subprocess.SubprocessError, OSError) as error:
            check("stale origin fixture", False, error)
        end_to_end_case(tmp / "e2e-run")
    for name in FAILED:
        print(f"failed: {name}", file=sys.stderr)
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
