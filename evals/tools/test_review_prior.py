#!/usr/bin/env python3
"""The prior-round machinery: content identity, earlier-round discovery, and the reviewed-file collapse.

A review of uncommitted work has no commit id to name what it read — two measured rounds at the same
`HEAD` recorded the same `Reviewed at:` and differed only by the working tree, 131 KB against 235 KB.
So identity is the file's bytes, and these tests pin the three things that can silently rot:

- the blob id must equal git's own, or two rounds compare unequal for a file nobody touched;
- discovery must find the earlier run without reading a directory that is not a review;
- the collapse must keep every hunk id citable, because the coverage gate re-checks them.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / ".agent" / "tools"), str(ROOT / ".agent" / "tools" / "review"),
                str(ROOT / ".agent" / "tools" / "lib")]

import review_manifest as manifest  # noqa: E402
from review_parse import parse  # noqa: E402

DIFF = """diff --git a/a.ts b/a.ts
index 1111111..2222222 100644
--- a/a.ts
+++ b/a.ts
@@ -1,2 +1,3 @@
 keep
+added
 tail
diff --git a/b.ts b/b.ts
index 3333333..4444444 100644
--- a/b.ts
+++ b/b.ts
@@ -10,2 +10,2 @@
-old
+new
 tail
"""


def test_the_blob_id_equals_gits_own(tmp: Path) -> None:
    """A wrong formula compares nothing equal, and the failure is silent: every round looks new."""
    target = tmp / "sample.ts"
    target.write_text("export const x = 1;\n")
    expected = hashlib.sha1(b"blob %d\0" % len(target.read_bytes()) + target.read_bytes()).hexdigest()
    assert manifest.blob_id(target) == expected
    git = subprocess.run(["git", "hash-object", "--", str(target)],
                         capture_output=True, text=True)
    if git.returncode == 0:
        assert manifest.blob_id(target) == git.stdout.strip(), "blob id disagrees with git"


def test_a_missing_file_has_no_id(tmp: Path) -> None:
    """Deleted-since must not compare equal to unchanged, so absence is None rather than empty."""
    assert manifest.blob_id(tmp / "gone.ts") is None


def test_a_manifest_records_only_the_paths_that_exist(tmp: Path) -> None:
    (tmp / "a.ts").write_text("one\n")
    payload = manifest.manifest(tmp, ["a.ts", "missing.ts"])
    assert list(payload["files"]) == ["a.ts"]


def test_reading_accepts_a_run_directory_or_the_manifest_file(tmp: Path) -> None:
    """`--reviewed` names the file and `prior-review` names the directory; both must find it.

    Reading the file as a directory resolves `<manifest.json>/manifest.json`, which does not exist,
    so the collapse would silently disable itself and report a successful run.
    """
    (tmp / "a.ts").write_text("one\n")
    run = tmp / "review" / "20260101000000"
    run.mkdir(parents=True)
    manifest.write(run, manifest.manifest(tmp, ["a.ts"]))
    assert manifest.read(run) is not None, "a run directory must resolve"
    assert manifest.read(run / manifest.MANIFEST_FILE) is not None, "the file itself must resolve"
    assert manifest.read(tmp / "absent") is None


def test_unchanged_requires_the_same_id_on_both_sides(tmp: Path) -> None:
    """A file in only one manifest is new or deleted, and neither is 'already reviewed'."""
    (tmp / "a.ts").write_text("one\n")
    (tmp / "b.ts").write_text("two\n")
    first = manifest.manifest(tmp, ["a.ts", "b.ts"])
    (tmp / "b.ts").write_text("changed\n")
    (tmp / "c.ts").write_text("three\n")
    second = manifest.manifest(tmp, ["a.ts", "b.ts", "c.ts"])
    assert manifest.unchanged_since(tmp, second, first) == {"a.ts"}


def test_discovery_skips_this_run_and_non_review_directories(tmp: Path) -> None:
    review = tmp / "review"
    for name in ("20260101000000", "20260102000000", "20260103000000"):
        (review / name).mkdir(parents=True)
        (review / name / "run.json").write_text("{}")
    (review / "notes").mkdir()
    (review / "notes" / "run.json").write_text("{}")
    current = review / "20260103000000"
    assert manifest.prior_review_dir(current) == review / "20260102000000"


def test_a_first_review_has_no_prior(tmp: Path) -> None:
    review = tmp / "review"
    (review / "20260101000000").mkdir(parents=True)
    (review / "20260101000000" / "run.json").write_text("{}")
    assert manifest.prior_review_dir(review / "20260101000000") is None


def test_a_directory_outside_a_review_dir_has_no_prior(tmp: Path) -> None:
    """A PR review's temp path is not under `review/`, so there is no round to compare against."""
    elsewhere = tmp / "runs" / "20260101000000"
    elsewhere.mkdir(parents=True)
    assert manifest.prior_review_dir(elsewhere) is None


def test_the_collapse_names_the_ids_of_every_omitted_file(tmp: Path) -> None:
    """The coverage gate re-checks ids, and an omitted file's ids are citable only from its note.

    Ids live in `hunks.index.md`, which every package carries, so the collapse cannot remove one.
    What it must not do is omit a file's body without naming the ids a finding there would cite.
    """
    parsed = parse(DIFF)
    collapsed = manifest.collapse_reviewed(DIFF, parsed, {"a.ts"}, "20260101000000")
    note = next(line for line in collapsed.splitlines() if "already reviewed at" in line)
    assert "h1" in note, f"the omitted file's id is not citable from its note: {note}"
    assert "b.ts" in collapsed and "+new" in collapsed, "an unreviewed file must be sent whole"


def test_the_collapse_does_nothing_without_a_reviewed_file(tmp: Path) -> None:
    parsed = parse(DIFF)
    assert manifest.collapse_reviewed(DIFF, parsed, set(), "20260101000000") == DIFF


def test_the_collapse_omits_the_body_of_a_reviewed_file(tmp: Path) -> None:
    parsed = parse(DIFF)
    collapsed = manifest.collapse_reviewed(DIFF, parsed, {"a.ts"}, "20260101000000")
    assert "+added" not in collapsed, "the reviewed file's body should be omitted"


def main() -> int:
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_")]
    failed = 0
    for test in tests:
        with tempfile.TemporaryDirectory() as directory:
            try:
                test(Path(directory))
                print(f"pass: {test.__name__}")
            except AssertionError as error:
                failed += 1
                print(f"FAIL: {test.__name__}: {error}")
    print(f"{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
