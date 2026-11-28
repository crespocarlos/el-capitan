#!/usr/bin/env python3
"""Hermetic checks for `src/crew/lib/git.py`: every helper's success and failure path.

Each helper is exercised against a throwaway repository, so a caller's real state is never touched:
a bare `origin` and `upstream` on disk stand in for the network, and `gh` is replaced by a stub, so
no request leaves the machine. The three cases each network helper must survive are checked by
name — gh failing while git answers, both failing with an error naming both, and gh answering with
no network git call made — because a gh-first helper that quietly dropped its git fallback would
still pass a test that only looked at the happy path.
"""
from __future__ import annotations

import importlib.util
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

ROOT =Path(__file__).resolve().parents[2]
GIT_MODULE = ROOT / "src" / "crew" / "lib" / "git.py"
DEFAULT_BRANCH_SH = ROOT / "src" / "crew" / "task" / "crew-default-branch.sh"

GIT_ENV = {"GIT_TERMINAL_PROMPT": "0", "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@e.invalid",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@e.invalid"}


def check(name: str, condition: bool, detail: object = "") -> None:
    assert condition, f"{name}: {detail}"


def load_module():
    """The library imported by path, so the stub can be installed on the module it calls."""
    spec = importlib.util.spec_from_file_location("crew_git_lib", GIT_MODULE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def git(cwd: Path, *arguments: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *arguments], cwd=str(cwd), text=True,
                          capture_output=True, env={**GIT_ENV, "PATH": "/usr/bin:/bin:/usr/local/bin"})


def make_repo(base: Path) -> tuple[Path, Path, Path]:
    """A repository with a commit, plus bare `origin` and `upstream` remotes holding it."""
    repo = base / "repo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    (repo / "tracked.txt").write_text("one\n")
    git(repo, "add", "tracked.txt")
    git(repo, "commit", "-qm", "first")
    origin = base / "origin.git"
    upstream = base / "upstream.git"
    for bare in (origin, upstream):
        bare.mkdir()
        git(bare, "init", "-q", "--bare", "-b", "main")
        git(repo, "push", "-q", str(bare), "main")
    git(repo, "remote", "add", "origin", str(origin))
    git(repo, "remote", "add", "upstream", str(upstream))
    for remote in ("origin", "upstream"):
        git(repo, "fetch", "-q", remote)
        git(repo, "remote", "set-head", remote, "main")
    return repo, origin, upstream


class GhStub:
    """Answers chosen `gh api` calls and records them; anything else fails like a blocked network."""

    def __init__(self) -> None:
        self.answers: dict[str, str] = {}
        self.calls: list[tuple[str, ...]] = []

    def __call__(self, *arguments: str, timeout: float = 20) -> subprocess.CompletedProcess:
        self.calls.append(arguments)
        joined = " ".join(arguments)
        for fragment, answer in self.answers.items():
            if fragment in joined:
                return subprocess.CompletedProcess(["gh", *arguments], 0, f"{answer}\n", "")
        return subprocess.CompletedProcess(["gh", *arguments], 1, "",
                                           'Get "https://api.github.com": Forbidden\n')

    def reset(self) -> None:
        self.calls.clear()
        self.answers.clear()


class GitRecorder:
    """Wraps `run_git` so a test can prove which git commands a helper issued."""

    def __init__(self, module) -> None:
        self.module = module
        self.original = module.run_git
        self.calls: list[tuple[str, ...]] = []

    def __call__(self, root, arguments, check=True, timeout=None):
        self.calls.append(tuple(arguments))
        return self.original(root, arguments, check=check, timeout=timeout)

    def __enter__(self) -> GitRecorder:
        self.module.run_git = self
        return self

    def __exit__(self, *_exc) -> None:
        self.module.run_git = self.original

    def network_calls(self) -> list[tuple[str, ...]]:
        """Only the calls that reach a remote: ls-remote, fetch, and the `remote show` query."""
        return [call for call in self.calls
                if call[:1] in {("ls-remote",), ("fetch",)} or call[:2] == ("remote", "show")]


def expect_error(name: str, call, fragment: str = "") -> None:
    """Assert the call raises GitError whose text carries `fragment`."""
    try:
        result = call()
    except TypeError as error:  # a helper imported from a stale module shape
        check(name, False, f"TypeError: {error}")
        return
    except Exception as error:
        module_error = type(error).__name__
        check(name, module_error == "GitError", f"raised {module_error}: {error}")
        if module_error == "GitError" and fragment:
            check(f"{name} names {fragment}", fragment in str(error), str(error))
        return
    check(name, False, f"returned {result!r} instead of raising")


def slug_cases(module, repo: Path) -> None:
    expect_error("repo_slug on a local-path remote raises", lambda: module.repo_slug(repo, "origin"))
    git(repo, "remote", "add", "hub", "git@github.com:acme/widgets.git")
    check("repo_slug derives owner/repo", module.repo_slug(repo, "hub") == "acme/widgets")
    git(repo, "remote", "remove", "hub")


def local_cases(module, repo: Path, outside: Path, base: Path) -> None:
    """Every local read: the answer in a real checkout, and GitError where git cannot answer."""
    check("toplevel resolves the root", module.toplevel(repo) == repo.resolve(),
          module.toplevel(repo))
    expect_error("toplevel outside a repository raises", lambda: module.toplevel(outside))
    check("current_branch names the branch", module.current_branch(repo) == "main",
          module.current_branch(repo))
    check("rev_parse resolves HEAD", len(module.rev_parse(repo, "HEAD")) == 40)
    expect_error("rev_parse on an unknown ref raises", lambda: module.rev_parse(repo, "no-such-ref"))
    check("head_sha shortens on request", len(module.head_sha(repo, short=True)) < 40)
    check("remote_url answers the origin URL", module.remote_url(repo, "origin") is not None)
    check("remote_url returns None for an absent remote", module.remote_url(repo, "nowhere") is None)
    check("remote_url raises outside a repository",
          _raises(module, lambda: module.remote_url(outside, "origin")))
    check("remotes lists both", sorted(module.remotes(repo)) == ["origin", "upstream"],
          module.remotes(repo))
    slug_cases(module, repo)
    expect_error("repo_slug on an absent remote raises", lambda: module.repo_slug(repo, "nowhere"))
    detached = repo.parent / "detached"
    shutil.copytree(repo, detached)
    sha = module.rev_parse(detached, "HEAD")
    git(detached, "checkout", "-q", "--detach", sha)
    expect_error("current_branch on a detached HEAD raises", lambda: module.current_branch(detached),
                 "detached")
    check("is_ancestor sees HEAD as its own ancestor",
          module.is_ancestor(repo, sha, "HEAD") is True)
    (repo / "tracked.txt").write_text("two\n")
    git(repo, "commit", "-qam", "second")
    check("is_ancestor sees the parent as an ancestor",
          module.is_ancestor(repo, sha, "HEAD") is True)
    check("is_ancestor refuses the reverse direction", module.is_ancestor(repo, "HEAD", sha) is False)
    expect_error("is_ancestor with an unknown sha raises",
                 lambda: module.is_ancestor(repo, "0" * 40, "HEAD"))
    check("commit_time is a timestamp", module.commit_time(repo) > 0)
    check("is_clean on a fresh commit", module.is_clean(repo) is True)
    (repo / "untracked.txt").write_text("x\n")
    check("is_clean sees an untracked file", module.is_clean(repo) is False)
    check("dirty_files names it", any("untracked.txt" in entry for entry in module.dirty_files(repo)))
    check("staged_paths is empty before staging", module.staged_paths(repo) == [])
    git(repo, "add", "untracked.txt")
    check("staged_paths names the staged file", module.staged_paths(repo) == ["untracked.txt"],
          module.staged_paths(repo))
    check("unstaged_paths ignores a cleanly staged file",
          module.unstaged_paths(repo, module.staged_paths(repo)) == [])
    (repo / "untracked.txt").write_text("edited after staging\n")
    check("unstaged_paths names a file edited after staging",
          module.unstaged_paths(repo, module.staged_paths(repo)) == ["untracked.txt"],
          module.unstaged_paths(repo, module.staged_paths(repo)))
    check("unstaged_paths without a path list reports every working edit",
          module.unstaged_paths(repo) == ["untracked.txt"])
    expect_error("unstaged_paths outside a repository raises",
                 lambda: module.unstaged_paths(outside))
    check("blob_at reads the index", module.blob_at(repo, ":tracked.txt") == "two\n",
          module.blob_at(repo, ":tracked.txt"))
    expect_error("blob_at on a missing path raises", lambda: module.blob_at(repo, ":absent.txt"))
    check("conflicted_paths is empty when nothing conflicts", module.conflicted_paths(repo) == [])
    expect_error("conflicted_paths outside a repository raises",
                 lambda: module.conflicted_paths(outside))
    expect_error("a failing diff inside a valid repo raises", lambda: failing_diff(module, repo, base))
    expect_error("dirty_files outside a repository raises", lambda: module.dirty_files(outside))
    expect_error("staged_paths outside a repository raises", lambda: module.staged_paths(outside))
    check("fork_point resolves from the initial commit",
          module.fork_point(repo, sha) == sha)
    expect_error("fork_point from an unknown base raises",
                 lambda: module.fork_point(repo, "no-such-ref"))
    check("base_ref prefers the local upstream symref",
          module.base_ref(repo) in {"upstream/main", "origin/main"}, module.base_ref(repo))
    git(repo, "reset", "-q")
    (repo / "untracked.txt").unlink()


def _raises(module, call) -> bool:
    try:
        call()
    except module.GitError:
        return True
    return False


def failing_diff(module, repo: Path, base: Path) -> list[str]:
    """Run `conflicted_paths` against a repository whose index is unreadable.

    A failing `git diff` inside an otherwise valid checkout is the case the helper's docstring
    names: reporting "no conflicts" there would let a caller treat conflict markers as resolved.
    """
    broken = Path(tempfile.mkdtemp(dir=str(base))) / "bad-index"
    shutil.copytree(repo, broken)
    index = broken / ".git" / "index"
    index.write_text("not an index\n")
    return module.conflicted_paths(broken)


def broken_copy(repo: Path, base: Path) -> Path:
    """A copy whose remotes point nowhere and whose `origin/HEAD` symref is gone.

    Both-failure cases need the local symref absent, or `default_branch` answers from a local
    branch name and never reaches either network path.
    """
    copy = Path(tempfile.mkdtemp(dir=str(base))) / "broken-copy"
    shutil.copytree(repo, copy)
    for remote in ("origin", "upstream"):
        git(copy, "remote", "set-head", remote, "-d")
        git(copy, "remote", "set-url", remote, str(base / "missing.git"))
    return copy


def default_branch_cases(module, stub: GhStub, repo: Path, base: Path) -> None:
    """default_branch: gh wins when it answers, git answers when gh cannot, both named when neither."""
    stub.reset()
    stub.answers["api repos/"] = "main"
    with GitRecorder(module) as recorder:
        check("default_branch prefers gh", module.default_branch(repo, "origin") == "main")
        check("gh-first issues no network git call", recorder.network_calls() == [],
              recorder.network_calls())

    stub.reset()
    with GitRecorder(module) as recorder:
        check("default_branch falls back to git when gh fails",
              module.default_branch(repo, "origin") == "main", recorder.network_calls())
        check("the fallback still consulted gh first",
              any("api" in call for call in stub.calls), stub.calls)

    stub.reset()
    expect_error("default_branch names both failures",
                 lambda: module.default_branch(broken_copy(repo, base), "origin"), "gh:")
    try:
        module.default_branch(broken_copy(repo, base), "origin")
    except module.GitError as error:
        check("the both-fail message carries the git error too", "git:" in str(error), str(error))


def remote_tip_cases(module, stub: GhStub, repo: Path, base: Path) -> None:
    """remote_tip: the gh answer, then ls-remote, then an error naming both."""
    tip = module.rev_parse(repo, "refs/remotes/origin/main")
    stub.reset()
    stub.answers["/git/ref/heads/main"] = "a" * 40
    with GitRecorder(module) as recorder:
        check("remote_tip prefers gh", module.remote_tip(repo, "origin", "main") == "a" * 40)
        check("remote_tip gh answer makes no network git call", recorder.network_calls() == [])

    stub.reset()
    check("remote_tip falls back to ls-remote",
          module.remote_tip(repo, "origin", "main") == tip,
          module.remote_tip(repo, "origin", "main"))
    stub.reset()
    expect_error("remote_tip names both failures",
                 lambda: module.remote_tip(broken_copy(repo, base), "origin", "main"), "gh:")


def ahead_on_origin(repo: Path, base: Path) -> str:
    """Push one commit to the bare origin, so the local tracking ref is behind it (each call clones afresh)."""
    ahead = Path(tempfile.mkdtemp(dir=str(base))) / "ahead"
    git(base, "clone", "-q", str(base / "origin.git"), str(ahead))
    (ahead / "tracked.txt").write_text(f"{ahead.parent.name}\n")
    git(ahead, "commit", "-qam", "ahead")
    git(ahead, "push", "-q", "origin", "main")
    return module_tip(ahead)


def module_tip(repo: Path) -> str:
    return git(repo, "rev-parse", "HEAD").stdout.strip()


def fetch_remote_cases(module, stub: GhStub, repo: Path, base: Path) -> None:
    """fetch_remote: git transports when gh cannot, and skips transport when gh proves the tip."""
    current = module.rev_parse(repo, "refs/remotes/origin/main")
    stub.reset()
    stub.answers["/git/ref/heads/main"] = current
    with GitRecorder(module) as recorder:
        check("fetch_remote returns gh's tip", module.fetch_remote(repo, "origin", "main") == current)
        check("fetch_remote skips the fetch when gh reports the local tip",
              not any(call[:1] == ("fetch",) for call in recorder.calls), recorder.calls)

    tip = ahead_on_origin(repo, base)
    stub.reset()
    with GitRecorder(module) as recorder:
        module.fetch_remote(repo, "origin", "main")
        check("fetch_remote falls back to git fetch",
              any(call[:1] == ("fetch",) for call in recorder.calls), recorder.calls)
        check("fetch_remote updated the tracking ref",
              module.rev_parse(repo, "refs/remotes/origin/main") == tip,
              module.rev_parse(repo, "refs/remotes/origin/main"))

    stub.reset()
    expect_error("fetch_remote names both failures",
                 lambda: module.fetch_remote(broken_copy(repo, base), "origin", "main"), "gh:")


def behind_cases(module, stub: GhStub, repo: Path, base: Path) -> None:
    """behind_count: gh's count, git's count with the same answer, and both failures named."""
    stub.reset()
    stub.answers["/compare/"] = "2"
    with GitRecorder(module) as recorder:
        check("behind_count prefers gh", module.behind_count(repo, "origin", "main") == 2)
        check("behind_count gh answer makes no network git call", recorder.network_calls() == [],
              recorder.network_calls())
    head = module.rev_parse(repo, "HEAD")
    ahead_on_origin(repo, base)
    behind = git(base / "origin.git", "rev-list", "--count", f"{head}..main").stdout.strip()
    stub.reset()
    check("behind_count falls back to git (it fetches, then counts)",
          str(module.behind_count(repo, "origin", "main")) == behind != "0", f"origin is {behind} ahead of HEAD")
    stub.reset()
    expect_error("behind_count names both failures",
                 lambda: module.behind_count(broken_copy(repo, base), "origin", "main"), "gh:")


def script_agreement(module, repo: Path) -> None:
    """The shell command and the helper answer the same branch, which is the one-definition rule."""
    for remote in ("origin", "upstream"):
        result = subprocess.run(["bash", str(DEFAULT_BRANCH_SH), remote], cwd=str(repo), text=True,
                                capture_output=True)
        check(f"crew-default-branch.sh answers for {remote}", result.returncode == 0, result.stderr)
        check(f"script and helper agree for {remote}",
              result.stdout.strip() == module.default_branch(repo, remote),
              f"{result.stdout.strip()!r} vs {module.default_branch(repo, remote)!r}")


def test_local_reads(tmp: Path) -> None:
    repo, _origin, _upstream = make_repo(tmp)
    outside = tmp / "outside"
    outside.mkdir()
    local_cases(load_module(), repo, outside, tmp)


@pytest.fixture(scope="module")
def network(tmp_path_factory: pytest.TempPathFactory) -> tuple:
    """One repository with its remotes and one gh stub, shared by the network groups below; each group
    resets the stub and makes the remote state it needs, so they pass in any order or alone."""
    base = tmp_path_factory.mktemp("git-lib")
    module, stub = load_module(), GhStub()
    module.gh = stub
    repo, _origin, _upstream = make_repo(base)
    # The remotes are local bare repositories, which name no owner/repo; the network helpers
    # are asked as if they were on GitHub (`slug_from_url` has its own cases in test_task_progress).
    module.slug_from_url = lambda url: "acme/widgets" if url else None
    return module, stub, repo, base


@pytest.mark.parametrize("group", [default_branch_cases, remote_tip_cases, fetch_remote_cases, behind_cases],
                         ids=["default_branch", "remote_tip", "fetch_remote", "behind_count"])
def test_network_helpers_fall_back_from_gh_to_git(group, network: tuple) -> None:
    group(*network)


def test_the_script_and_the_helper_agree(network: tuple) -> None:
    module, stub, repo, _ = network
    stub.reset()
    script_agreement(module, repo)
