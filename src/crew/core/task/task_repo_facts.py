"""The repository facts a prompt asks for, each read only when asked: one `git status` answers the tree, one
`git remote -v` the remotes. `default_branch` is the local symref unless `network` (gh, then git). The diff
fields say where a branch's review diff starts (`diff_base`, `fork_point`) and what it holds, always the fork
point against the working tree, so committed and pending work are both reviewed; `diff_source` names which.
"""

from __future__ import annotations

from functools import cached_property
from pathlib import Path

from crew.lib import git

STATUS = ("branch", "head", "upstream", "staged", "changed", "staged_dirty", "untracked", "dirty")
REMOTE = ("remote", "remote_url", "remotes", "repo", "repo_name", "origin_repo")
DIFF = ("diff_base", "fork_point", "diff_source", "changed_files", "diff_stat", "diff")
DEFAULT = ("root", *STATUS, "head_short", *REMOTE, "default_branch")
FIELDS = (*DEFAULT, *DIFF)


class NothingToReview(git.GitError):
    """The fork point and the working tree agree: no commit since it, nothing staged or edited."""


def primary_remote(names: list[str]) -> str:
    """`upstream` when it exists (a fork's PR targets it), then `origin`, then the first remote."""
    for preferred in ("upstream", "origin"):
        if preferred in names:
            return preferred
    return names[0] if names else ""


class Facts:
    """The facts of the checkout at `at`, computed on first read; a git failure raises `GitError`."""

    def __init__(self, at: Path | None = None, remote: str = "", network: bool = False, files: list[str] | None = None) -> None:
        self.at, self.asked_remote, self.network, self.files = at, remote, network, files or []

    def get(self, name: str) -> object:
        return self.status[name] if name in STATUS else getattr(self, name)

    def record(self, names: tuple[str, ...] = DEFAULT) -> dict:
        return {name: self.get(name) for name in names}

    @cached_property
    def root(self) -> str:
        return str(git.toplevel(self.at))

    @cached_property
    def status(self) -> dict:
        return git.status(self.at)

    @cached_property
    def head_short(self) -> str | None:
        return git.head_sha(self.at, short=True) if self.status["head"] else None

    @cached_property
    def remotes(self) -> dict[str, str]:
        return git.remote_urls(self.at)

    @cached_property
    def remote(self) -> str:
        return self.asked_remote or primary_remote(list(self.remotes))

    @cached_property
    def remote_url(self) -> str | None:
        return self.remotes.get(self.remote)

    @cached_property
    def repo(self) -> str | None:
        return git.slug_from_url(self.remote_url)

    @cached_property
    def repo_name(self) -> str | None:
        return git.repo_name_from_url(self.remote_url)

    @cached_property
    def origin_repo(self) -> str | None:
        return git.slug_from_url(self.remotes.get("origin"))

    @cached_property
    def default_branch(self) -> str | None:
        if not self.remote:
            return None
        return git.default_branch(self.at, self.remote) if self.network else git.symref_default(self.at, self.remote)

    @cached_property
    def diff_base(self) -> str:
        return git.base_ref(self.at)

    @cached_property
    def fork_point(self) -> str:
        return git.fork_point(self.at, self.diff_base)

    @cached_property
    def changed_files(self) -> list[str]:
        return git.diff(self.at, self.fork_point, "--name-only", self.files).splitlines()

    @cached_property
    def diff_source(self) -> str:
        """`branch`, `worktree` or `branch+worktree`: which halves of the fork-to-tree diff hold changes."""
        if not self.changed_files:
            raise NothingToReview("no commit since the fork point, and nothing staged or modified")
        committed = bool(git.diff(self.at, f"{self.fork_point}...HEAD", "--name-only", self.files).strip())
        pending = bool(git.diff(self.at, "HEAD", "--name-only", self.files).strip())
        return "+".join(name for name, present in (("branch", committed), ("worktree", pending)) if present) or "branch"

    @cached_property
    def diff_stat(self) -> str:
        return git.diff(self.at, self.fork_point, "--stat", self.files)

    @cached_property
    def diff(self) -> str:
        return git.diff(self.at, self.fork_point, "", self.files)
