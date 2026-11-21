"""Git and GitHub helpers: one runner, and one answer per question.

`run_git` is the only place a git argv is built, so every caller gets one error shape. Local reads —
root, branch, HEAD, ancestry, status, the index, a blob — use git alone. Network reads — a remote's
default branch, a remote tip, a fetch, how far behind — try `gh` first, because gh carries the
authentication and answers where git has no credential, then fall back to the equivalent git
command; when both fail the error names both. No helper reads empty output as an answer: one that
cannot answer raises `GitError`, except the documented booleans, which return False only for git's
own negative exit. A helper that must know which remote it is talking about reads the remote URL
from local config first; that read is not a network call.
"""
from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

NETWORK_TIMEOUT = 20


class GitError(RuntimeError):
    """git could not answer; the payload is git's own stderr or its exit status."""


def _env() -> dict[str, str]:
    """A child environment that cannot block on a credential prompt and parses in one locale."""
    return {**os.environ, "GIT_TERMINAL_PROMPT": "0", "LC_ALL": "C"}


def run_git(
    root: Path | None, arguments: list[str], check: bool = True, timeout: float | None = None
) -> subprocess.CompletedProcess[str]:
    """Run git in `root`, or in the current directory when `root` is None."""
    command = ["git", *(["-C", str(root)] if root is not None else []), *arguments]
    return subprocess.run(command, text=True, capture_output=True, check=check, env=_env(),
                          timeout=timeout)


def gh(*arguments: str, timeout: float = NETWORK_TIMEOUT) -> subprocess.CompletedProcess[str]:
    """Run gh with both streams captured, so a caller surfaces its own error text."""
    return subprocess.run(["gh", *arguments], text=True, stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, env=_env(), timeout=timeout)


def output(root: Path | None, arguments: list[str]) -> str:
    """Stdout of a git command that must succeed, or GitError carrying git's own stderr."""
    try:
        result = run_git(root, arguments, check=False)
    except (OSError, subprocess.SubprocessError) as error:
        raise GitError(f"git unavailable: {error}") from error
    if result.returncode:
        raise GitError(result.stderr.strip() or f"git {' '.join(arguments)} exit {result.returncode}")
    return result.stdout


def rev_parse(root: Path | None, ref: str) -> str:
    """The object `ref` names; raises when it does not resolve."""
    return output(root, ["rev-parse", ref]).strip()


def toplevel(root: Path | None) -> Path:
    """The repository root, following worktrees and symlinks to a real directory."""
    return Path(output(root, ["rev-parse", "--show-toplevel"]).strip()).resolve()


def current_branch(root: Path | None) -> str:
    """The checked-out branch name; a detached HEAD raises rather than answering ""."""
    name = output(root, ["branch", "--show-current"]).strip()
    if not name:
        raise GitError("HEAD is detached; there is no current branch")
    return name


def remotes(root: Path | None) -> list[str]:
    """Every configured remote name; empty inside a repository that has none."""
    return output(root, ["remote"]).split()


def remote_url(root: Path | None, name: str = "origin") -> str | None:
    """The URL of remote `name`, or None only when that remote is not configured.

    `git remote get-url` answers exit 2 for an unconfigured remote and 128 outside a repository,
    which is the distinction that keeps "no such remote" from hiding "not a checkout at all".
    """
    try:
        result = run_git(root, ["remote", "get-url", name], check=False)
    except (OSError, subprocess.SubprocessError) as error:
        raise GitError(f"git unavailable: {error}") from error
    if result.returncode == 0:
        return result.stdout.strip()
    if result.returncode == 2:
        return None
    raise GitError(result.stderr.strip() or f"git exit {result.returncode}")


def repo_slug(root: Path | None, remote: str = "origin") -> str:
    """The `owner/repo` a remote points at, which is the path segment `gh api` takes."""
    url = remote_url(root, remote)
    if not url:
        raise GitError(f"no '{remote}' remote is configured")
    match = re.search(r"[:/]([^/:]+)/([^/]+?)(?:\.git)?/*$", url)
    if not match:
        raise GitError(f"cannot derive owner/repo from {url!r}")
    return f"{match.group(1)}/{match.group(2)}"


def dirty_files(root: Path | None) -> list[str]:
    """Every path git reports as changed, including untracked files."""
    return [line for line in output(root, ["status", "--porcelain"]).splitlines() if line]


def conflicted_paths(root: Path | None) -> list[str]:
    """Conflicted paths, or GitError when git cannot answer.

    A failed `git diff` (broken index, missing repo, held lock) is not "no conflicts":
    reporting clean would let a caller adopt conflict markers as a resolution.
    """
    result = run_git(root, ["diff", "--name-only", "--diff-filter=U"], check=False)
    if result.returncode:
        raise GitError(result.stderr.strip() or f"git exit {result.returncode}")
    return [line for line in result.stdout.splitlines() if line.strip()]


def is_clean(root: Path | None) -> bool:
    """True when nothing is staged, modified, or untracked."""
    return not dirty_files(root)


def staged_paths(root: Path | None) -> list[str]:
    """Paths staged against HEAD; before the first commit that is the whole index."""
    return [line for line in output(root, ["diff", "--cached", "--name-only"]).splitlines() if line]


def unstaged_paths(root: Path | None, paths: list[str] | None = None) -> list[str]:
    """Paths with working-tree edits, optionally narrowed to `paths`.

    Answers the question `crew commit`'s fast path asks: are the files I just checked
    still edited on disk after being staged? An edited-and-restaged file keeps the same
    staged name set, so the name list alone cannot prove the review still applies.
    """
    arguments = ["diff", "--name-only", "--"]
    arguments.extend(paths or [])
    return [line for line in output(root, arguments).splitlines() if line]


def blob_at(root: Path | None, ref_and_path: str) -> str:
    """The content at `<ref>:<path>`, or `:<path>` for the index; raises when there is none."""
    return output(root, ["show", ref_and_path])


def commit_time(root: Path | None, ref: str = "HEAD") -> int:
    """`ref`'s committer date as a Unix timestamp, for comparing a build against its source."""
    text = output(root, ["log", "-1", "--format=%ct", ref]).strip()
    if not text.isdigit():
        raise GitError(f"no commit time for {ref}")
    return int(text)


def head_sha(root: Path | None, short: bool = False) -> str:
    """HEAD's commit id, abbreviated to git's own short form when asked."""
    return output(root, ["rev-parse", "--short", "HEAD"] if short else ["rev-parse", "HEAD"]).strip()


def is_ancestor(root: Path | None, older: str, newer: str) -> bool:
    """True when `older` is an ancestor of `newer`; any other git failure raises."""
    try:
        result = run_git(root, ["merge-base", "--is-ancestor", older, newer], check=False)
    except (OSError, subprocess.SubprocessError) as error:
        raise GitError(f"git unavailable: {error}") from error
    if result.returncode in (0, 1):
        return result.returncode == 0
    raise GitError(result.stderr.strip() or f"git exit {result.returncode}")


def fork_point(root: Path | None, base: str, ref: str = "HEAD") -> str:
    """Where `ref` left `base`; the fork-point form first, then a plain merge base, else raise."""
    for arguments in (["merge-base", "--fork-point", base, ref], ["merge-base", base, ref]):
        result = run_git(root, arguments, check=False)
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    raise GitError(f"no fork point between {base} and {ref}")


def gh_answer(arguments: list[str]) -> tuple[str, str]:
    """(stdout, error) for one gh call; error carries gh's own text so a caller can name both."""
    try:
        result = gh(*arguments)
    except (OSError, subprocess.SubprocessError) as error:
        return "", f"gh unavailable: {error}"
    if result.returncode:
        return "", (result.stderr.strip() or result.stdout.strip() or f"gh exit {result.returncode}")
    return result.stdout.strip(), ""


def local_default_branch(root: Path | None, remote: str) -> tuple[str, str]:
    """(branch, error) from git alone: the local symref, then `ls-remote --symref`, then remote show."""
    try:
        local = run_git(root, ["symbolic-ref", "--quiet", "--short", f"refs/remotes/{remote}/HEAD"],
                        check=False)
        if local.returncode == 0 and local.stdout.strip():
            return local.stdout.strip().removeprefix(f"{remote}/"), ""
        lsremote = run_git(root, ["ls-remote", "--symref", remote, "HEAD"], check=False,
                           timeout=NETWORK_TIMEOUT)
    except (OSError, subprocess.SubprocessError) as error:
        return "", f"git unavailable: {error}"
    for line in lsremote.stdout.splitlines():
        match = re.match(r"^ref:\s+refs/heads/(\S+)\s+HEAD$", line.strip())
        if match:
            return match.group(1), ""
    shown = run_git(root, ["remote", "show", remote], check=False, timeout=NETWORK_TIMEOUT)
    for line in shown.stdout.splitlines():
        label, _, value = line.strip().partition(": ")
        if label == "HEAD branch" and value not in {"", "(unknown)", "(not queried)"}:
            return value, ""
    return "", (lsremote.stderr.strip() or shown.stderr.strip() or "git named no remote HEAD")


def default_branch(root: Path | None, remote: str = "origin") -> str:
    """A remote's default branch, gh first and git as the fallback.

    gh goes first because it carries the authentication and answers where git has no credential;
    git answers with the local symref, then `ls-remote --symref`, then `remote show`. Both failures
    are named, because either one alone misleads — a blocked api.github.com and an absent SSH key
    are different problems with the same symptom.
    """
    gh_error = ""
    answer = ""
    try:
        answer, gh_error = gh_answer(
            ["api", f"repos/{repo_slug(root, remote)}", "--jq", ".default_branch"])
    except GitError as error:
        gh_error = str(error)
    if answer:
        return answer
    fallback, git_error = local_default_branch(root, remote)
    if fallback:
        return fallback
    raise GitError(f"default branch of '{remote}' unknown; gh: {gh_error}; git: {git_error}")


def remote_tip(root: Path | None, remote: str, ref: str) -> str:
    """The commit `remote/ref` points at: `gh api` first, `git ls-remote` as the fallback."""
    gh_error = ""
    answer = ""
    try:
        answer, gh_error = gh_answer(
            ["api", f"repos/{repo_slug(root, remote)}/git/ref/heads/{ref}", "--jq", ".object.sha"])
    except GitError as error:
        gh_error = str(error)
    if answer:
        return answer
    try:
        listing = run_git(root, ["ls-remote", remote, f"refs/heads/{ref}"], check=False,
                          timeout=NETWORK_TIMEOUT)
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
    raise GitError(f"cannot read {remote}/{ref}; gh: {gh_error}; git: {git_error}")


def fetch_remote(root: Path | None, remote: str = "origin", ref: str = "") -> str:
    """Make `<remote>/<ref>` current and return the tip gh reported, when it reported one.

    gh answers the tip first; when the local tracking ref already holds it there is nothing to
    transfer and no transport runs. Objects only ever arrive over git, so a real update is a
    `git fetch`, and its failure names gh's error beside its own.
    """
    tip, gh_error = "", ""
    if ref:
        try:
            tip = remote_tip(root, remote, ref)
        except GitError as error:
            gh_error = str(error)
        if tip:
            try:
                if rev_parse(root, f"refs/remotes/{remote}/{ref}") == tip:
                    return tip
            except GitError:
                pass
    arguments = ["fetch", remote, *([ref] if ref else [])]
    result = run_git(root, arguments, check=False, timeout=NETWORK_TIMEOUT)
    if result.returncode:
        detail = result.stderr.strip() or f"git exit {result.returncode}"
        label = f"{remote} {ref}".strip()
        raise GitError(f"cannot fetch {label}; git: {detail}"
                       + (f"; gh: {gh_error}" if gh_error else ""))
    return tip


def behind_count(root: Path | None, remote: str, branch: str) -> int:
    """Commits `remote/branch` has that HEAD does not, gh first and git as the fallback.

    gh's compare endpoint answers straight from the server, so it needs no objects locally; the head
    side is HEAD's own SHA, because `HEAD` is not a name the API resolves. git answers by fetching
    and counting, which is the path a machine without api.github.com uses.
    """
    gh_error = ""
    try:
        head = rev_parse(root, "HEAD")
        answer, gh_error = gh_answer(
            ["api", f"repos/{repo_slug(root, remote)}/compare/{branch}...{head}",
             "--jq", ".behind_by"])
    except GitError as error:
        answer, gh_error = "", str(error)
    if answer.strip().isdigit():
        return int(answer.strip())
    try:
        fetch_remote(root, remote, branch)
        text = output(root, ["rev-list", "--count", f"HEAD..{remote}/{branch}"]).strip()
    except GitError as error:
        raise GitError(f"cannot compare with {remote}/{branch}; gh: {gh_error}; "
                       f"git: {error}") from error
    if not text.isdigit():
        raise GitError(f"cannot compare with {remote}/{branch}: {text!r}")
    return int(text)


def base_ref(root: Path | None) -> str:
    """The ref a branch's diff starts from, resolved from local refs and never over the network.

    A fork's `upstream` default comes first, then `origin`'s, matching what review already treats as
    the branch point; `HEAD~1` is the last resort for a checkout with no remote. Each remote's
    default is read from its local `HEAD` symref first, because a review must not wait on a network
    round trip to know where its own diff begins.
    """
    for remote in ("upstream", "origin"):
        if remote_url(root, remote) is None:
            continue
        names = []
        symref = run_git(root, ["symbolic-ref", "--quiet", "--short", f"refs/remotes/{remote}/HEAD"],
                         check=False)
        if symref.returncode == 0 and symref.stdout.strip():
            names.append(symref.stdout.strip().removeprefix(f"{remote}/"))
        names += ["main", "master"]
        for name in names:
            candidate = f"{remote}/{name}"
            if run_git(root, ["rev-parse", "--verify", "--quiet", candidate], check=False).returncode == 0:
                return candidate
    return "HEAD~1"

