#!/usr/bin/env python3
"""Contract checks for review-hunks.py: hunk ids, statuses, and markdown shape.

The parser owns the ids every layer map and coverage gate refers to, so these tests pin the
exact shapes: one id per textual hunk in diff order, plus one synthetic id for a file with no
textual change. That is what keeps a crew review and any other consumer citing the same `h1`.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

TOOL = Path(__file__).resolve().parents[2] / ".agent" / "tools" / "review" / "review-hunks.py"

SIMPLE = """diff --git a/src/a.ts b/src/a.ts
index 1111111..2222222 100644
--- a/src/a.ts
+++ b/src/a.ts
@@ -10,3 +10,4 @@ function demo() {
 const a = 1;
-const b = 2;
+const b = 3;
+const c = 4;
 export { a, b, c };
"""

# Every non-textual case at once: a second file with two hunks keeps ids in diff order, and a
# binary, a pure rename, and an added file each get their own synthetic id.
MIXED = SIMPLE + """@@ -40,2 +41,2 @@ function other() {
-return 1;
+return 2;
diff --git a/img/logo.png b/img/logo.png
new file mode 100644
index 0000000..3333333
Binary files /dev/null and b/img/logo.png differ
diff --git a/old/name.ts b/new/name.ts
similarity index 100%
rename from old/name.ts
rename to new/name.ts
diff --git a/src/new.ts b/src/new.ts
new file mode 100644
index 0000000..4444444
--- /dev/null
+++ b/src/new.ts
@@ -0,0 +1,2 @@
+export const x = 1;
+export const y = 2;
\\ No newline at end of file
"""

GENERATED = """diff --git a/package-lock.json b/package-lock.json
new file mode 100644
--- /dev/null
+++ b/package-lock.json
@@ -0,0 +1,2 @@
+{"name": "x"}
+{"lock": true}
"""


class Skip(Exception):
    """A test that could not run here; reported as a skip, never counted as passed."""


def run(args: list[str], stdin: str | None = None) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(TOOL), *args], capture_output=True, text=True,
                          input=stdin)


def parse(diff: str, tmp: Path) -> dict:
    source = tmp / "x.diff"
    source.write_text(diff)
    out = tmp / "out"
    result = run([str(source), "--out", str(out)])
    assert result.returncode == 0, result.stderr
    return {"json": json.loads((out / "hunks.json").read_text()),
            "md": (out / "hunks.md").read_text(),
            "index": (out / "hunks.index.md").read_text()}


def test_numbered_ids_in_diff_order(tmp: Path) -> None:
    result = parse(MIXED, tmp)
    assert [h["id"] for h in result["json"]["hunks"]] == ["h1", "h2", "h3", "h4", "h5"]


def test_every_changed_file_gets_at_least_one_hunk(tmp: Path) -> None:
    """A file with no textual hunk must still be placeable in a layer, or coverage cannot pass."""
    files = {f["path"]: f for f in parse(MIXED, tmp)["json"]["files"]}
    assert set(files) == {"src/a.ts", "img/logo.png", "new/name.ts", "src/new.ts"}
    assert files["img/logo.png"]["status"] == "binary" and files["img/logo.png"]["hunkIds"] == ["h4"]
    assert files["new/name.ts"]["status"] == "renamed" and files["new/name.ts"]["hunkIds"] == ["h5"]
    assert files["new/name.ts"]["oldPath"] == "old/name.ts"
    assert files["src/new.ts"]["status"] == "added" and files["src/new.ts"]["hunkIds"] == ["h3"]
    assert files["src/a.ts"]["hunkIds"] == ["h1", "h2"]


def test_hunk_bodies_carry_line_numbers_and_order(tmp: Path) -> None:
    first = parse(SIMPLE, tmp)["json"]["hunks"][0]
    assert (first["additions"], first["deletions"]) == (2, 1)
    assert first["newStart"] == 10 and first["context"] == "function demo() {"
    assert [(line["t"], line["s"]) for line in first["lines"]] == [
        (" ", "const a = 1;"), ("-", "const b = 2;"), ("+", "const b = 3;"),
        ("+", "const c = 4;"), (" ", "export { a, b, c };"),
    ]
    assert first["lines"][1]["o"] == 11 and first["lines"][3]["n"] == 12


def test_markdown_indexes_every_hunk(tmp: Path) -> None:
    text = parse(MIXED, tmp)["md"]
    assert "# Hunk index (5 hunks in 4 files)" in text
    assert "- `src/a.ts`: h1 @10(+2/-1), h2 @41(+1/-1)" in text
    # A binary file is called out by status, not mislabeled as generated.
    assert "- `img/logo.png` [binary]: h4 @0(+0/-0)" in text
    assert "### h4 — (binary file)" in text
    assert "### h5 — (renamed, no content change)" in text
    assert "## FILE new/name.ts (renamed from old/name.ts)" in text
    for hunk_id in ("h1", "h2", "h3", "h4", "h5"):
        assert f"### {hunk_id} —" in text, hunk_id


def test_generated_file_is_flagged(tmp: Path) -> None:
    entry = parse(GENERATED, tmp)["json"]["files"][0]
    assert entry["generated"] is True
    assert "likely-generated" in parse(GENERATED, tmp)["md"]


def test_package_diff_collapses_generated_files_only(tmp: Path) -> None:
    """A lockfile's lines cost every persona and carry no intent; a source file must survive intact."""
    source = tmp / "x.diff"
    source.write_text(SIMPLE + GENERATED)
    result = run([str(source), "--out", str(tmp / "out")])
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["omitted"] == ["package-lock.json"]
    package = (tmp / "out" / "package.diff").read_text()
    assert package.startswith(SIMPLE), "a non-generated file must be embedded byte for byte"
    assert "diff --git a/package-lock.json b/package-lock.json" in package
    assert "# package-lock.json: likely generated, +2/-0 lines omitted (h2)" in package
    assert '+{"lock": true}' not in package and "@@ -0,0 +1,2 @@" not in package


def test_package_diff_keeps_source_files_the_content_heuristic_flags(tmp: Path) -> None:
    """Long-lined prompts and TS constants trip the content heuristic; a review must still read them."""
    long_line = "x" * 3000
    diff = ("diff --git a/src/constants.ts b/src/constants.ts\n--- a/src/constants.ts\n"
            f"+++ b/src/constants.ts\n@@ -1 +1 @@\n-old\n+{long_line}\n")
    source = tmp / "x.diff"
    source.write_text(diff)
    result = run([str(source), "--out", str(tmp / "out")])
    payload = json.loads(result.stdout)
    assert payload["omitted"] == [] and payload["keptDespiteContentFlag"] == ["src/constants.ts"]
    assert (tmp / "out" / "package.diff").read_text() == diff


def test_index_is_the_hunk_list_without_diff_bodies(tmp: Path) -> None:
    """A persona package already holds the diff; re-quoting it doubles the package for no gain."""
    result = parse(MIXED, tmp)
    index = result["index"]
    # Identity, not containment: the standalone index must be exactly the head of hunks.md, so the
    # two renderers cannot drift while a length heuristic still holds.
    assert index.rstrip("\n") == result["md"].split("\n# Hunks\n")[0].rstrip("\n")
    assert index.startswith("# Hunk index (5 hunks in 4 files)")
    # ...and it carries no hunk bodies and none of the diff's own lines.
    assert "```diff" not in index
    assert "### h" not in index
    assert "+const b = 3;" not in index
    assert "-const b = 2;" not in index


def test_stdin_and_empty_input(tmp: Path) -> None:
    ok = run(["-", "--out", str(tmp / "o")], stdin=SIMPLE)
    assert ok.returncode == 0, ok.stderr
    assert json.loads((tmp / "o" / "hunks.json").read_text())["hunks"]
    empty = run(["-", "--out", str(tmp / "e")], stdin="")
    assert empty.returncode == 2 and "empty" in empty.stderr


def test_rejects_non_diff_input(tmp: Path) -> None:
    source = tmp / "notes.txt"
    source.write_text("just some prose\n")
    result = run([str(source), "--out", str(tmp / "out")])
    assert result.returncode == 2 and "not a unified diff" in result.stderr


def test_quoted_paths_are_decoded(tmp: Path) -> None:
    """git quotes non-ASCII and control characters; an empty path would merge unrelated files."""
    diff = (
        'diff --git "a/caf\\303\\251.md" "b/caf\\303\\251.md"\n'
        "--- \"a/caf\\303\\251.md\"\n+++ \"b/caf\\303\\251.md\"\n"
        "@@ -1 +1 @@\n-a\n+b\n"
        'diff --git "a/old\\tname.md" "b/new\\"name.md"\n'
        'similarity index 100%\nrename from "old\\tname.md"\nrename to "new\\"name.md"\n'
    )
    files = parse(diff, tmp)["json"]["files"]
    assert [(f["path"], f["oldPath"], f["status"]) for f in files] == [
        ("café.md", "café.md", "modified"),
        ('new"name.md', "old\tname.md", "renamed"),
    ]


def test_missing_input_file_is_an_error(tmp: Path) -> None:
    result = run([str(tmp / "nope.diff"), "--out", str(tmp / "out")])
    assert result.returncode == 2


def test_python_parser_matches_nightshift_when_available(tmp: Path) -> None:
    """Optional parity check: ids, statuses, and lines must match nightshift's parseDiff.

    Reported as a skip, never a pass, when no checkout is installed: the parser must not
    require one, and the point of the test is to catch drift for whoever has nightshift locally.
    """
    root = Path("~/Documents/dev/nightshift-pr-helper").expanduser()
    if not (root / "lib" / "diff.ts").is_file() or not (root / "node_modules" / "tsx").is_dir():
        raise Skip("no nightshift checkout")
    source = tmp / "parity.diff"
    source.write_text(MIXED)
    theirs = tmp / "theirs"
    theirs.mkdir()
    script = (
        "import fs from 'node:fs';"
        "import { parseDiff } from './lib/diff.ts';"
        f"const d = parseDiff(fs.readFileSync({json.dumps(str(source))}, 'utf8'));"
        f"fs.writeFileSync({json.dumps(str(theirs / 'hunks.json'))}, JSON.stringify(d));"
    )
    result = subprocess.run(["node", "--import", "tsx/esm", "--eval", script],
                            capture_output=True, text=True, cwd=root)
    if result.returncode:
        raise Skip(f"nightshift parser unavailable: {result.stderr.strip().splitlines()[-1:]}")
    ours = parse(MIXED, tmp)["json"]
    night = json.loads((theirs / "hunks.json").read_text())
    shape = lambda parsed: [  # noqa: E731
        (h["id"], h["file"], h["additions"], h["deletions"],
         [(line["t"], line["s"]) for line in h["lines"]])
        for h in parsed["hunks"]
    ]
    assert shape(ours) == shape(night), "hunk ids or bodies drifted from nightshift's parseDiff"
    assert [(f["path"], f["status"], f["hunkIds"]) for f in ours["files"]] == [
        (f["path"], f["status"], f["hunkIds"]) for f in night["files"]]


def main() -> int:
    tests = [value for key, value in globals().items() if key.startswith("test_")]
    failed = skipped = 0
    for test in tests:
        with tempfile.TemporaryDirectory() as tmp:
            try:
                test(Path(tmp))
                print(f"pass: {test.__name__}")
            except Skip as reason:
                skipped += 1
                print(f"skip: {test.__name__}: {reason}")
            except Exception as error:  # noqa: BLE001 - one broken test must not hide the rest
                failed += 1
                print(f"FAIL: {test.__name__}: {type(error).__name__}: {error}")
    print(f"{len(tests) - failed - skipped}/{len(tests)} passed, {skipped} skipped")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
