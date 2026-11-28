"""Every changed file of a PR at its head SHA, in one GraphQL call per `BATCH` paths, under `head/`.

`fetch_head` asks `repository.object(expression: "<sha>:<path>")` for all paths at once and writes each text
blob to `head/files/<path>`; `head/index.json` records each path's status: `ok`, `absent` (deleted at the head),
`binary`, `oversized` (over `MAX_FILE_BYTES`) or `truncated`, the last two with the single `gh api` read that
fetches one file by hand. GraphQL, not the head tarball: it is bounded to the changed paths.
"""

from __future__ import annotations

import json
from pathlib import Path, PurePosixPath

from crew.lib.git import gh

BATCH = 100
MAX_FILE_BYTES = 256 * 1024
FETCH_TIMEOUT = 120
BLOB_FIELDS = "... on Blob { byteSize isBinary isTruncated text }"
INDEX = "index.json"
FILES = "files"  # blobs live apart from the index, so a PR's own root `index.json` cannot overwrite it


def query_text(count: int) -> str:
    """One query with `count` aliased blob lookups; the expressions travel as variables, never inlined."""
    variables = "".join(f", $e{i}: String!" for i in range(count))
    lookups = "\n".join(f"    f{i}: object(expression: $e{i}) {{ {BLOB_FIELDS} }}" for i in range(count))
    return f"query($owner: String!, $name: String!{variables}) {{\n  repository(owner: $owner, name: $name) {{\n{lookups}\n  }}\n}}"


def safe_relative(path: str) -> PurePosixPath:
    """The path as a relative POSIX path inside `head/`; ValueError for an absolute path or a `..` part."""
    relative = PurePosixPath(path)
    if not path or relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"refusing to write {path!r} outside head/")
    return relative


def manual_read(repo: str, sha: str, path: str) -> str:
    """The one-file read the PR-mode rules allow, quoted for zsh."""
    return f'gh api "repos/{repo}/contents/{path}?ref={sha}" --jq .content | base64 --decode'


def ask(repo: str, sha: str, paths: list[str]) -> dict:
    """One `gh api graphql` call for `paths`; the `repository` object, or RuntimeError with gh's message."""
    owner, _, name = repo.partition("/")
    argv = ["api", "graphql", "-f", f"query={query_text(len(paths))}", "-f", f"owner={owner}", "-f", f"name={name}"]
    for index, path in enumerate(paths):
        argv += ["-f", f"e{index}={sha}:{path}"]
    result = gh(*argv, timeout=FETCH_TIMEOUT)
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or f"gh exit {result.returncode}")
    try:
        payload = json.loads(result.stdout)
    except ValueError as error:
        raise RuntimeError(f"gh returned no JSON ({error})") from error
    if payload.get("errors") and not (payload.get("data") or {}).get("repository"):
        raise RuntimeError(json.dumps(payload["errors"])[:500])
    repository = (payload.get("data") or {}).get("repository")
    if not isinstance(repository, dict):
        raise RuntimeError(f"no repository {repo} in gh's answer")
    return repository


def classify(blob: object) -> str:
    """The status of one answered lookup."""
    if not isinstance(blob, dict) or "byteSize" not in blob:
        return "absent"
    if blob.get("isBinary"):
        return "binary"
    if int(blob.get("byteSize") or 0) > MAX_FILE_BYTES:
        return "oversized"
    if blob.get("isTruncated") or blob.get("text") is None:
        return "truncated"
    return "ok"


def fetch_head(repo: str, sha: str, paths: list[str], out: Path) -> dict:
    """Write every text file of `paths` at `sha` under `out/files` and return the index (also `out/index.json`)."""
    wanted = list(dict.fromkeys(p for p in paths if p))
    for path in wanted:
        safe_relative(path)
    out.mkdir(parents=True, exist_ok=True)
    files: dict[str, dict] = {}
    calls = 0
    for start in range(0, len(wanted), BATCH):
        chunk = wanted[start : start + BATCH]
        repository = ask(repo, sha, chunk)
        calls += 1
        for index, path in enumerate(chunk):
            blob = repository.get(f"f{index}")
            status = classify(blob)
            entry: dict = {"status": status}
            if isinstance(blob, dict) and "byteSize" in blob:
                entry["bytes"] = int(blob.get("byteSize") or 0)
            if status == "ok":
                target = out / FILES / safe_relative(path)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(blob["text"], encoding="utf-8")
            elif status in ("oversized", "truncated"):
                entry["read"] = manual_read(repo, sha, path)
            files[path] = entry
    index = {"repo": repo, "head": sha, "calls": calls, "files": files}
    (out / INDEX).write_text(json.dumps(index, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return index


def changed_paths(repo: str, pr: int) -> list[str]:
    """The PR's changed paths from `gh pr diff --name-only`, the same source `prepare` parses its paths from."""
    result = gh("pr", "diff", str(pr), "--repo", repo, "--name-only")
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or f"gh exit {result.returncode}")
    return [line for line in result.stdout.splitlines() if line.strip()]


def pr_head(repo: str, pr: int) -> dict:
    """`{"sha", "head_repo"}` from one `gh pr view`: the immutable head and the repository holding it (a fork's
    own). RuntimeError with gh's message when the read fails."""
    result = gh("pr", "view", str(pr), "--repo", repo, "--json", "headRefOid,headRepository,headRepositoryOwner")
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or f"gh exit {result.returncode}")
    try:
        record = json.loads(result.stdout)
    except ValueError as error:
        raise RuntimeError(f"gh pr view returned no JSON ({error})") from error
    sha = str(record.get("headRefOid") or "")
    if not sha:
        raise RuntimeError(f"PR {pr} of {repo} has no headRefOid")
    owner = (record.get("headRepositoryOwner") or {}).get("login")
    name = (record.get("headRepository") or {}).get("name")
    return {"sha": sha, "head_repo": f"{owner}/{name}" if owner and name else repo}


def summary(index: dict) -> str:
    """`5 files at abc1234 in 1 call (4 ok, 1 absent)`."""
    counts: dict[str, int] = {}
    for entry in index["files"].values():
        counts[entry["status"]] = counts.get(entry["status"], 0) + 1
    detail = ", ".join(f"{n} {status}" for status, n in sorted(counts.items()))
    calls = index["calls"]
    return f"{len(index['files'])} files at {index['head'][:7]} in {calls} call{'s' if calls != 1 else ''}" + (f" ({detail})" if detail else "")
