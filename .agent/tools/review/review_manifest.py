#!/usr/bin/env python3
"""What a review read, identified by content, so a later round can tell what is new.

A review of uncommitted work has no commit id to name: two rounds at the same `HEAD` differ only by
the working tree, and both recorded the same `Reviewed at:`. The manifest answers the question the
commit cannot — which files, at which bytes, this round actually saw — by hashing each changed file
the way git would, so an id here compares directly with `git ls-tree` or `hash-object`.

The ids are computed in Python rather than by asking git. `hash-object -w` and a temp-index `add`
both fail in a read-only sandbox, and a module outside `lib/git.py` may not build a git argv, so the
blob-id formula is the one read-only route that stays inside both rules. A test pins it against git
itself, because a wrong formula would silently compare nothing equal.

A missing file hashes nothing: `None` is recorded and compares equal only to `None`, so "deleted
since the last review" never matches "unchanged".
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

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
    names = sorted((entry for entry in parent.iterdir()
                    if entry.is_dir() and entry.name.isdigit() and entry != review_dir),
                   reverse=True)
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
                out.append(f"# {current}: already reviewed at {stamp}, +{added}/-{removed} lines "
                           f"omitted ({', '.join(ids)}); unchanged since, so read it only if a "
                           "finding here would depend on it")
        if not skipping:
            out.append(line)
    return "\n".join(out)


def _header_new_path(line: str) -> str:
    """The new-side path from a `diff --git` header, quoted form included."""
    from review_parse import header_paths

    return header_paths(line)[1]
