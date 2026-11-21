"""Remote questions: a remote's default branch, its tip, a fetch, and how far behind HEAD is.

Every helper here asks about a remote rather than about the local checkout, so each one tries `gh`
first, because gh carries the authentication and answers where git has no credential, and falls
back to the equivalent git command. When both fail the error names both: a blocked api.github.com
and an absent SSH key are different problems with the same symptom, and naming one alone misleads.
No helper reads empty output as an answer — one that cannot answer raises `GitError`.

The runner, `GitError`, and the timeout belong to `lib.git`, which re-exports these names so a
caller imports one module. They are read through a live view of that module's globals, not copied,
so a caller that replaces `run_git` or `gh` — a test stub, a wrapper — is the one these helpers
call, and `lib.git` can import this file without a cycle.
"""
from __future__ import annotations

import re
import subprocess
from typing import Any

URL_PATH = re.compile(r"[:/]([^/:]+)/([^/]+?)(?:\.git)?/*$")


class _Library:
    """Live attribute view of the library that owns the runner, error type, and timeout."""

    def __init__(self) -> None:
        self.namespace: dict[str, Any] = {}

    def __getattr__(self, name: str) -> Any:
        try:
            return self.namespace[name]
        except KeyError:
            raise AttributeError(name) from None


LIB = _Library()
EXPORTS = ("behind_count", "default_branch", "fetch_remote", "local_default_branch",
           "remote_tip", "repo_slug")


def install(library_globals: dict[str, Any]) -> None:
    """Bind this module to `lib.git`'s globals and put its remote helpers into that namespace.

    Binding is by reference, not by copy, so a caller that later replaces `run_git` or `gh` is the
    one these helpers call. The helpers are installed rather than re-exported by hand so `from
    lib.git import default_branch` keeps working after the split, with no list to keep in step.
    """
    LIB.namespace = library_globals
    for name in EXPORTS:
        library_globals[name] = globals()[name]


def gh_answer(arguments: list[str]) -> tuple[str, str]:
    """(stdout, error) for one gh call; error carries gh's own text so a caller can name both."""
    try:
        result = LIB.gh(*arguments)
    except (OSError, subprocess.SubprocessError) as error:
        return "", f"gh unavailable: {error}"
    if result.returncode:
        return "", (result.stderr.strip() or result.stdout.strip() or f"gh exit {result.returncode}")
    return result.stdout.strip(), ""


def repo_slug(root: Any, remote: str = "origin") -> str:
    """The `owner/repo` a remote points at, which is the path segment `gh api` takes."""
    url = LIB.remote_url(root, remote)
    if not url:
        raise LIB.GitError(f"no '{remote}' remote is configured")
    match = URL_PATH.search(url)
    if not match:
        raise LIB.GitError(f"cannot derive owner/repo from {url!r}")
    return f"{match.group(1)}/{match.group(2)}"


def local_default_branch(root: Any, remote: str) -> tuple[str, str]:
    """(branch, error) from git alone: the local symref, then `ls-remote --symref`, then remote show."""
    try:
        local = LIB.run_git(root, ["symbolic-ref", "--quiet", "--short",
                                   f"refs/remotes/{remote}/HEAD"], check=False)
        if local.returncode == 0 and local.stdout.strip():
            return local.stdout.strip().removeprefix(f"{remote}/"), ""
        lsremote = LIB.run_git(root, ["ls-remote", "--symref", remote, "HEAD"], check=False,
                               timeout=LIB.NETWORK_TIMEOUT)
    except (OSError, subprocess.SubprocessError) as error:
        return "", f"git unavailable: {error}"
    for line in lsremote.stdout.splitlines():
        match = re.match(r"^ref:\s+refs/heads/(\S+)\s+HEAD$", line.strip())
        if match:
            return match.group(1), ""
    shown = LIB.run_git(root, ["remote", "show", remote], check=False, timeout=LIB.NETWORK_TIMEOUT)
    for line in shown.stdout.splitlines():
        label, _, value = line.strip().partition(": ")
        if label == "HEAD branch" and value not in {"", "(unknown)", "(not queried)"}:
            return value, ""
    return "", (lsremote.stderr.strip() or shown.stderr.strip() or "git named no remote HEAD")


def default_branch(root: Any, remote: str = "origin") -> str:
    """A remote's default branch, gh first and git as the fallback.

    gh goes first because it carries the authentication and answers where git has no credential;
    git answers with the local symref, then `ls-remote --symref`, then `remote show`. Both failures
    are named, because either one alone misleads.
    """
    gh_error = ""
    try:
        answer, gh_error = gh_answer(
            ["api", f"repos/{repo_slug(root, remote)}", "--jq", ".default_branch"])
    except LIB.GitError as error:
        answer, gh_error = "", str(error)
    if answer:
        return answer
    fallback, git_error = local_default_branch(root, remote)
    if fallback:
        return fallback
    raise LIB.GitError(f"default branch of '{remote}' unknown; gh: {gh_error}; git: {git_error}")


def remote_tip(root: Any, remote: str, ref: str) -> str:
    """The commit `remote/ref` points at: `gh api` first, `git ls-remote` as the fallback."""
    gh_error = ""
    try:
        answer, gh_error = gh_answer(
            ["api", f"repos/{repo_slug(root, remote)}/git/ref/heads/{ref}", "--jq", ".object.sha"])
    except LIB.GitError as error:
        answer, gh_error = "", str(error)
    if answer:
        return answer
    try:
        listing = LIB.run_git(root, ["ls-remote", remote, f"refs/heads/{ref}"], check=False,
                             timeout=LIB.NETWORK_TIMEOUT)
    except (OSError, subprocess.SubprocessError) as error:
        listing = None
        git_error = f"git unavailable: {error}"
    else:
        git_error = listing.stderr.strip()
    if listing is not None and listing.returncode == 0:
        for line in listing.stdout.splitlines():
            sha, _, name = line.partition("\t")
            if name.strip() == f"refs/heads/{ref}" and sha.strip():
                return sha.strip()
        git_error = f"{remote} has no branch {ref}"
    raise LIB.GitError(f"cannot read {remote}/{ref}; gh: {gh_error}; git: {git_error}")


def fetch_remote(root: Any, remote: str = "origin", ref: str = "") -> str:
    """Make `<remote>/<ref>` current and return the tip gh reported, when it reported one.

    gh answers the tip first; when the local tracking ref already holds it there is nothing to
    transfer and no transport runs. Objects only ever arrive over git, so a real update is a
    `git fetch`, and its failure names gh's error beside its own.
    """
    tip, gh_error = "", ""
    if ref:
        try:
            tip = remote_tip(root, remote, ref)
        except LIB.GitError as error:
            gh_error = str(error)
        if tip:
            try:
                if LIB.rev_parse(root, f"refs/remotes/{remote}/{ref}") == tip:
                    return tip
            except LIB.GitError:
                pass
    arguments = ["fetch", remote, *([ref] if ref else [])]
    result = LIB.run_git(root, arguments, check=False, timeout=LIB.NETWORK_TIMEOUT)
    if result.returncode:
        detail = result.stderr.strip() or f"git exit {result.returncode}"
        label = f"{remote} {ref}".strip()
        raise LIB.GitError(f"cannot fetch {label}; git: {detail}"
                           + (f"; gh: {gh_error}" if gh_error else ""))
    return tip


def behind_count(root: Any, remote: str, branch: str) -> int:
    """Commits `remote/branch` has that HEAD does not, gh first and git as the fallback.

    gh's compare endpoint answers straight from the server, so it needs no objects locally; the head
    side is HEAD's own SHA, because `HEAD` is not a name the API resolves. git answers by fetching
    and counting, which is the path a machine without api.github.com uses.
    """
    gh_error = ""
    try:
        head = LIB.rev_parse(root, "HEAD")
        answer, gh_error = gh_answer(
            ["api", f"repos/{repo_slug(root, remote)}/compare/{branch}...{head}",
             "--jq", ".behind_by"])
    except LIB.GitError as error:
        answer, gh_error = "", str(error)
    if answer.strip().isdigit():
        return int(answer.strip())
    try:
        fetch_remote(root, remote, branch)
        text = LIB.output(root, ["rev-list", "--count", f"HEAD..{remote}/{branch}"]).strip()
    except LIB.GitError as error:
        raise LIB.GitError(f"cannot compare with {remote}/{branch}; gh: {gh_error}; "
                           f"git: {error}") from error
    if not text.isdigit():
        raise LIB.GitError(f"cannot compare with {remote}/{branch}: {text!r}")
    return int(text)
