#!/usr/bin/env python3
"""`task_progress`, the one owner of PROGRESS.md, and the `lib/` helpers it shares.

New entries carry one UTC stamp (`YYYY-MM-DDTHH:MM:SSZ`); legacy local `[YYYY-MM-DD HH:MM:SS]` lines
still parse, so a task written before the change still reads as BLOCKED, landed and costed. The
owner/repo parser is the one in `lib.git`; its accepted and refused URL shapes are listed here.
"""
from __future__ import annotations

import re
import sys
import time
from collections.abc import Iterator
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / ".agent" / "tools"
sys.path.insert(0, str(TOOLS / "task"))
sys.path.insert(0, str(TOOLS))

import task_progress  # noqa: E402

from lib.clock import parse_stamp, utc_stamp  # noqa: E402
from lib.git import slug_from_url  # noqa: E402

UTC_LINE = re.compile(r"^\[\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z\] ")
SLUGS = {
    "https://github.com/Acme/Widgets.git": "Acme/Widgets",
    "https://github.com/acme/widgets/": "acme/widgets",
    "git@github.com:acme/widgets.git": "acme/widgets",
    "ssh://git@github.com/acme/widgets": "acme/widgets",
    "ssh://git@github.com:22/acme/widgets.git": "acme/widgets",
    "  https://ghe.example.com/team/repo.name  ": "team/repo.name",
    "github-work:acme/widgets.git": "acme/widgets",
    "git://github.com/acme/widgets.git": "acme/widgets",
    "git://github.com/acme/widgets": "acme/widgets",
    "https://github.com/x/acme/widgets": None,
    "https://github.com/acme": None,
    "/local/path/repo": None,
    "": None,
    "file:///srv/acme/widgets.git": None,
    "git://github.com/x/acme/widgets": None,
    "github-work:x/acme/widgets": None,
    "github-work:/acme/widgets": None,
}


def check(name: str, condition: bool, detail: object = "") -> None:
    assert condition, f"{name}: {detail}"


def task(base: Path, name: str, text: str = "") -> Path:
    directory = base / name
    directory.mkdir()
    if text:
        (directory / "PROGRESS.md").write_text(text, encoding="utf-8")
    return directory


def test_stamps() -> None:
    moment = datetime(2026, 3, 4, 5, 6, 7, tzinfo=timezone.utc)
    check("utc_stamp is YYYY-MM-DDTHH:MM:SSZ", utc_stamp(moment) == "2026-03-04T05:06:07Z", utc_stamp(moment))
    check("utc_stamp round-trips through parse_stamp", parse_stamp(utc_stamp(moment)) == moment)
    check("a legacy local stamp parses as the local time in UTC",
          parse_stamp("2026-03-04 05:06:07") == datetime(2026, 3, 4, 5, 6, 7).astimezone(timezone.utc))
    check("a legacy minute stamp `YYYY-MM-DD HH:MM` parses as local time",
          parse_stamp("2026-03-04 05:06") == datetime(2026, 3, 4, 5, 6).astimezone(timezone.utc))
    check("an offset ISO stamp parses", parse_stamp("2026-03-04T05:06:07+00:00") == moment)
    check("garbage is None", parse_stamp("yesterday") is None and parse_stamp("") is None)


@pytest.fixture
def sao_paulo(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("TZ", "America/Sao_Paulo")  # UTC-3: a legacy 10:00 is 13:00Z
    time.tzset()
    yield
    monkeypatch.undo()
    time.tzset()


def test_mixed_stamps(tmp: Path, sao_paulo: None) -> None:
    directory = task(tmp, "mixed", "[2026-01-01 10:00:00] TRANSITION: DRAFTING → APPROVED\n"
                                   "\n[2026-01-01T12:00:00Z] METRIC: stage_start stage=implement\n"
                                   "a line with no stamp\n")
    entries = task_progress.read_entries(directory)
    check("every non-blank line is an entry, in file order", [e.kind for e in entries] == ["TRANSITION", "METRIC", ""],
          [e.kind for e in entries])
    minute = task(tmp, "minute", "[2026-01-01 10:00] BLOCKED: written by hand in the documented minute form\n")
    found = task_progress.read_entries(minute)
    check("a minute-form line is a BLOCKED entry at its local time in UTC",
          [(e.kind, e.at) for e in found] == [("BLOCKED", datetime(2026, 1, 1, 13, 0, tzinfo=timezone.utc))], found)
    check("a minute-form BLOCKED line is visible", task_progress.blocked_reason(minute) != "")
    check("the legacy local line is converted to UTC",
          entries[0].at == datetime(2026, 1, 1, 13, 0, tzinfo=timezone.utc), entries[0].at)
    check("ordering by time puts the legacy line after the earlier UTC line",
          [e.kind for e in sorted(entries[:2], key=lambda e: e.at)] == ["METRIC", "TRANSITION"])
    check("a line with no stamp keeps its text and no time",
          entries[2].at is None and entries[2].text == "a line with no stamp")
    check("latest is the newest stamped entry", task_progress.latest(directory) == entries[0].at)
    task_progress.append_transition(directory, "APPROVED → IMPLEMENTING")
    last = (directory / "PROGRESS.md").read_text(encoding="utf-8").splitlines()[-1]
    check("an appended transition carries the UTC stamp", UTC_LINE.match(last) is not None, last)
    check("an appended entry reads back last",
          task_progress.read_entries(directory)[-1].body == "APPROVED → IMPLEMENTING")


def test_blocked(tmp: Path) -> None:
    after_metric = task(tmp, "b1", "[2026-01-01 10:00:00] BLOCKED: no key\n"
                                   "[2026-01-01T11:00:00Z] METRIC: implement_start mode=inline\n")
    check("BLOCKED followed by a METRIC line is still visible", task_progress.blocked_reason(after_metric) == "no key")
    after_start = task(tmp, "b2", "[2026-01-01T10:00:00Z] BLOCKED: no key\n"
                                  "[2026-01-01T11:00:00Z] METRIC: stage_start stage=review\n")
    check("BLOCKED followed by a stage_start is cleared", task_progress.blocked_reason(after_start) == "")
    after_transition = task(tmp, "b3", "[2026-01-01 10:00:00] BLOCKED: x\n[2026-01-01 11:00:00] TRANSITION: A → B\n")
    check("BLOCKED followed by a transition is cleared", task_progress.blocked_reason(after_transition) == "")
    written = task(tmp, "b4")
    task_progress.append_blocked(written, "two\n  lines")
    task_progress.append_worktree(written, "here", "/tmp/marker")
    check("an appended BLOCKED survives a WORKTREE line, collapsed to one line",
          task_progress.blocked_reason(written) == "two lines", task_progress.blocked_reason(written))
    check("a task without PROGRESS.md is not blocked", task_progress.blocked_reason(task(tmp, "b5")) == "")


def test_metric(tmp: Path) -> None:
    directory = task(tmp, "m")
    task_progress.append_metric(directory, "review run=r1 personas=2 tokens_reported=10")
    check("has_metric finds an appended METRIC by prefix", task_progress.has_metric(directory, "review run=r1 "))
    check("has_metric is False for another run", not task_progress.has_metric(directory, "review run=r2 "))
    with pytest.raises(ValueError):
        task_progress.append_metric(directory, "  ")
    with pytest.raises(FileNotFoundError):
        task_progress.append_transition(tmp / "missing", "A → B")


@pytest.mark.parametrize("url,expected", [*SLUGS.items(), (None, None)])
def test_slug_from_url(url: str | None, expected: str | None) -> None:
    assert slug_from_url(url) == expected
