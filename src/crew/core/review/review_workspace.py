"""Where a review writes its artifacts, and what it read, identified by content.

The task directory when writable, `/tmp` otherwise, chosen by trying the write. Each changed file is
hashed as a git blob id in Python, so two rounds at the same `HEAD` still differ by content; a missing
file records `None`, which equals only `None`.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
from datetime import datetime
from pathlib import Path


def _timestamp() -> str:
    return datetime.now().strftime("%Y%m%d%H%M%S")


def _try(path: Path) -> Path | None:
    """The directory when it can be created and written, else None."""
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".write-probe"
        probe.write_text("", encoding="utf-8")
        probe.unlink()
    except OSError:
        return None
    return path


def review_dir(task_dir: str | None, repo: str | None = None, mode: str = "self") -> Path:
    """Create and return the review directory for this run.

    A PR review always uses the temp form, because it must not depend on a task directory at all.
    Everything else prefers the task directory and falls back to a temp path that names the
    repository, so two reviews of different repos cannot collide.
    """
    stamp = _timestamp()
    if mode != "pr" and task_dir:
        chosen = _try(Path(task_dir) / "review" / stamp)
        if chosen is not None:
            return chosen
    name = repo or "review"
    base = Path(tempfile.gettempdir()) / f"crew-review-{name}" / "review"
    chosen = _try(base / stamp)
    if chosen is None:
        raise OSError(f"no writable review directory: tried {base / stamp}")
    return chosen


def record_task_review(task_dir: str | Path | None, review_dir_path: Path, mode: str = "") -> None:
    """Point the task at the directory holding its review, so a gate can find it later.

    `persist` writes `REVIEW.md` beside the spec in every mode but PR, and a task reviewed in PR
    mode would otherwise have no readable review at all once the temp directory is the only copy.
    The record is additive: a task with no `SPEC.md` is not a task and is left alone.
    """
    if not task_dir:
        return
    task = Path(task_dir)
    if not (task / "SPEC.md").is_file():
        return
    record = {"review_dir": str(Path(review_dir_path).resolve())}
    if mode:
        record["review_mode"] = mode
    try:
        existing = json.loads((task / "run.json").read_text(encoding="utf-8"))
        if isinstance(existing, dict):
            record = {**existing, **record}
    except (OSError, ValueError):
        pass
    (task / "run.json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")


def claim(path: Path, mode: str, repo: str | None, task_dir: str | None) -> None:
    """Write `run.json` so a run identifies itself without anyone guessing from a timestamp.

    The directory name is a timestamp, which says when but not what: two reviews of different
    repositories or modes look identical in a `/tmp` listing. `run.json` records what the directory
    is for, so a person or an agent can pick the right one instead of taking the newest by mtime.
    """
    record = {
        "mode": mode,
        "repo": repo or None,
        "task_dir": task_dir or None,
        "created": datetime.now().isoformat(timespec="seconds"),
        "tool": "crew-review-findings.py review-dir",
    }
    (path / "run.json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    record_task_review(task_dir, path, mode)


def report(path: Path, task_dir: str | None) -> int:
    """Print the chosen path, and say so on stderr when it is not the task directory.

    The fallback is not an error, but a silent switch would hide why a later `crew commit` cannot
    find the review, so the reason goes to stderr where it stays out of a `$(...)` capture.
    """
    print(path)
    if task_dir and str(path).startswith(str(task_dir)):
        return 0
    reason = "PR review uses a temp directory" if task_dir is None or task_dir == "" else (f"{task_dir} is not writable in this sandbox")
    print(f"review-dir: using {path} ({reason})", file=sys.stderr)
    return 0


def cleanup_stale(base: Path, keep: Path, limit: int = 10) -> list[Path]:
    """Remove older sibling review directories beyond `limit`, newest kept.

    A temp fallback accumulates one directory per review and nothing else prunes them; the task
    path does not need this because it lives with the task that will be committed or discarded.
    """
    removed: list[Path] = []
    if not base.is_dir():
        return removed
    siblings = sorted((p for p in base.iterdir() if p.is_dir() and p != keep), reverse=True)
    for stale in siblings[limit:]:
        for child in stale.rglob("*"):
            if child.is_file():
                try:
                    child.unlink()
                except OSError:
                    break
        try:
            os.removedirs(stale)
        except OSError:
            continue
        removed.append(stale)
    return removed


MANIFEST_FILE = "manifest.json"


def blob_id(path: Path) -> str | None:
    """The git blob id of a file's current bytes, or None when it is not there to hash.

    The formula is git's own: `sha1(b"blob <len>\\0" + bytes)`. Not a content hash of the project's
    choosing — an id a reader can check against `git hash-object` costs nothing and avoids a second
    identity vocabulary in the artifacts.
    """
    try:
        raw = path.read_bytes()
    except OSError:
        return None
    header = b"blob %d\0" % len(raw)
    return hashlib.sha1(header + raw).hexdigest()


def manifest(root: Path, paths: list[str]) -> dict:
    """The per-file ids for `paths`, plus the revision they were read at.

    `paths` is the review's own changed-path list, so a file that did not change is absent rather
    than recorded as unchanged: the manifest describes what was in the diff, not the repository.
    """
    files = {}
    for path in paths:
        identifier = blob_id(root / path)
        if identifier is not None:
            files[path] = identifier
    return {"root": str(root.resolve()), "files": files}


def write(review_dir: Path, payload: dict) -> Path:
    """Persist the manifest beside the run's other artifacts."""
    target = review_dir / MANIFEST_FILE
    target.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return target


def read(target: Path) -> dict | None:
    """The manifest at a run directory or at a `manifest.json` path, or None when there is none.

    Accepts either spelling because two callers arrive with different ones: `prior-review` names the
    run directory, and `--reviewed` on the hunk build is documented as the manifest file itself.
    Treating the file as a directory reads `<file>/manifest.json` and silently reports "no earlier
    review", which would disable the collapse while looking like a successful run.
    """
    path = target if target.name == MANIFEST_FILE else target / MANIFEST_FILE
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def unchanged_since(root: Path, current: dict, previous: dict) -> set[str]:
    """Paths whose bytes are identical in both manifests.

    A path in only one of them is not unchanged: added files are unreviewed, removed files are not
    there to review. Both sides must name the same id.
    """
    old = previous.get("files") or {}
    new = current.get("files") or {}
    return {path for path, identifier in new.items() if old.get(path) == identifier}


def prior_review_dir(review_dir: Path) -> Path | None:
    """The newest sibling run directory older than this one, or None for a first review.

    Siblings are the `<task>/review/<timestamp>` directories `review-dir` creates. The name is a
    timestamp, so ordering is lexical and no file is opened to decide; `run.json` is read only to
    skip a directory that is not a review.
    """
    parent = review_dir.parent
    if parent.name != "review" or not parent.is_dir():
        return None
    names = sorted((entry for entry in parent.iterdir() if entry.is_dir() and entry.name.isdigit() and entry != review_dir), reverse=True)
    for candidate in names:
        if candidate.name < review_dir.name and (candidate / "run.json").is_file():
            return candidate
    return None


def collapse_reviewed(diff: str, parsed: dict, reviewed: set[str], stamp: str) -> str:
    """`package.diff` with every file whose bytes an earlier round already read collapsed to a note.

    File granularity, not hunk granularity: the manifest compares whole files, so a file whose id
    matches the earlier round contributes exactly the hunks that round saw, and matching them again
    by body would only add a way to get it wrong. Every id stays citable and the coverage gate still
    passes, which is what the generated-file collapse already established.

    The note names the round, because a persona cannot judge whether an omission is safe without
    knowing how old it is. This is opt-in through `--since-last-review`: a hunk unchanged since the
    last round can still be newly wrong because a change elsewhere invalidated it, and only the
    caller knows whether cross-file context matters more than the saved reading.
    """
    by_file: dict[str, list[str]] = {}
    for entry in parsed["files"]:
        if entry["path"] in reviewed and entry.get("hunkIds"):
            by_file[entry["path"]] = entry["hunkIds"]
    if not by_file:
        return diff
    additions = {hunk["id"]: (hunk["additions"], hunk["deletions"]) for hunk in parsed["hunks"]}
    out: list[str] = []
    current = ""
    skipping = False
    for line in diff.split("\n"):
        if line.startswith("diff --git "):
            current = _header_new_path(line)
            skipping = current in by_file
            if skipping:
                ids = by_file[current]
                added = sum(additions.get(i, (0, 0))[0] for i in ids)
                removed = sum(additions.get(i, (0, 0))[1] for i in ids)
                out.append(
                    f"# {current}: already reviewed at {stamp}, +{added}/-{removed} lines omitted ({', '.join(ids)}); unchanged since, so read it only if a finding here would depend on it"
                )
        if not skipping:
            out.append(line)
    return "\n".join(out)


def _header_new_path(line: str) -> str:
    """The new-side path from a `diff --git` header, quoted form included."""
    from crew.core.review.review_parse import header_paths

    return header_paths(line)[1]


def prior_review(args: argparse.Namespace) -> int:
    """The `prior-review` subcommand: write this run's manifest, print what the previous round covered.

    One JSON object: `prior` (the earlier run directory, or null on a first review), `unchanged` (files
    whose bytes match what that round saw) and `files`; a first review is a success.
    """
    review_dir = args.review_dir.resolve()
    previous = prior_review_dir(review_dir)
    current = manifest(args.repo.resolve(), args.paths)
    kept = (read(review_dir) or {}).get("personas")
    write(review_dir, {**current, **({"personas": kept} if kept else {})})
    unchanged = set()
    if previous is not None:
        earlier = read(previous)
        if earlier is not None:
            unchanged = unchanged_since(args.repo.resolve(), current, earlier)
    print(
        json.dumps({"prior": str(previous) if previous is not None else None, "unchanged": sorted(unchanged), "files": len(current["files"])}, sort_keys=True)
    )
    return 0
