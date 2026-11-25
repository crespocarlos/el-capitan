#!/usr/bin/env python3
"""The prior-round block: what an earlier round reported, and what the author did with it.

Two measured rounds at one `HEAD` shared zero finding fingerprints and still raised the same subject
twice — "the flaky flag and the flaky_probe reason are explained in two bullets" became "the flaky
rule is stated in the flag bullet and the reason bullet". Fingerprint dedupe cannot see that reword,
so the only defence is a persona that has read the earlier titles. These tests pin the block's
content, its author-decision tags, and its refusal to invent a decision nobody recorded.
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / ".agent" / "tools"), str(ROOT / ".agent" / "tools" / "review"),
                str(ROOT / ".agent" / "tools" / "lib")]

from assemble_prior import section  # noqa: E402

REWORDED = {"file": "prompt/discovery.md.text", "line": 11, "label": "nit", "fingerprint": "aaa",
            "title": "The flaky flag and the flaky_probe reason are explained in two bullets",
            "disposition": "patch"}


def round_dir(tmp: Path, name: str = "20260101000000", findings: list | None = None) -> Path:
    """A run directory holding one consolidated finding, plus the journals beside it."""
    directory = tmp / "review" / name
    directory.mkdir(parents=True)
    (directory / "run.json").write_text("{}")
    if findings is not None:
        (directory / "consolidation.json").write_text(json.dumps(findings))
    return directory


def outcome(tmp: Path, fingerprint: str, value: str) -> None:
    journal = tmp / "review" / "outcomes.jsonl"
    with journal.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({"fingerprint": fingerprint, "outcome": value}) + "\n")


def test_the_block_lists_the_earlier_findings(tmp: Path) -> None:
    directory = round_dir(tmp, findings=[REWORDED])
    block = section(directory)
    assert "The flaky flag and the flaky_probe reason are explained in two bullets" in block
    assert "prompt/discovery.md.text:11" in block, "the anchor is what makes a re-raise recognisable"
    assert "[nit]" in block


def test_the_block_reports_the_authors_decision(tmp: Path) -> None:
    """`fixed` and `rejected` mean different things to a re-raise, so the word has to be there."""
    directory = round_dir(tmp, findings=[REWORDED])
    outcome(tmp, "aaa", "rejected")
    assert "rejected" in section(directory)


def test_an_unrecorded_finding_is_not_given_a_decision(tmp: Path) -> None:
    """Absent is a fact: the author said nothing, and a guessed `fixed` would silence a real finding."""
    directory = round_dir(tmp, findings=[REWORDED])
    line = next(item for item in section(directory).splitlines() if item.startswith("- [nit]"))
    for word in ("fixed", "rejected", "deferred", "skipped"):
        assert word not in line, f"the block invented the decision `{word}` on the finding line"


def test_the_block_carries_the_re_raise_rule(tmp: Path) -> None:
    directory = round_dir(tmp, findings=[REWORDED])
    block = section(directory).lower()
    assert "new evidence" in block, "without the rule the block is only a list of titles"


def test_a_run_with_no_findings_adds_no_block(tmp: Path) -> None:
    directory = round_dir(tmp, findings=[])
    assert section(directory) == ""


def test_a_run_with_no_consolidation_adds_no_block(tmp: Path) -> None:
    """Pre-artifact rounds and abandoned runs must not inject an empty heading into a package."""
    assert section(round_dir(tmp)) == ""


def test_a_long_title_is_cut_to_keep_the_block_small(tmp: Path) -> None:
    long = dict(REWORDED, title="word " * 200)
    block = section(round_dir(tmp, findings=[long]))
    line = next(item for item in block.splitlines() if item.startswith("- [nit]"))
    assert len(line) < 220, f"one finding costs {len(line)} chars, which grows the package per round"


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
