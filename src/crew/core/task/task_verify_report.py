"""`crew-verify.py report-check`: a builder's REPORT.md checked against the gates JSON a verify run wrote.

A report's machine part is its `### Report data` JSON block only (`ReportData`); the prose around it is for
people. Its `gates` must equal the verify result; `--lenient` accepts a report without the block.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import TypedDict

from crew.lib.markdown import fenced_blocks

HEADING = re.compile(r"^###\s+(.+?)\s*$", re.M)
OLD_CLAIM = re.compile(r"^- `(.+?)` — verify: `(.+?)`", re.M)


class ReportData(TypedDict, total=False):
    """The one reader's record (the builder writes it): `gates` `[{name, exit}]`, `unverified_claims` `[{claim, verify}]`."""

    schema_version: int
    tasks: dict
    gates: list[dict]
    unverified_claims: list[dict]


def sections(text: str) -> dict[str, str]:
    """Each `### heading` of the report mapped to its body; empty for a report with none."""
    found = list(HEADING.finditer(text))
    return {m.group(1): text[m.end() : found[i + 1].start() if i + 1 < len(found) else len(text)] for i, m in enumerate(found)}


def unverified_claims(text: str) -> list[tuple[str, str]]:
    """`(claim, command)` pairs of Report data's `unverified_claims`; a report written before the block keeps its
    `### Unverified claims` bullets (`- `claim` — verify: `command``), so an in-flight task's claims still reach review."""
    if report_data(text) is None:
        return OLD_CLAIM.findall(sections(text).get("Unverified claims", ""))
    found = (report_data(text) or {}).get("unverified_claims") or []
    return [(str(c.get("claim", "")), str(c.get("verify", ""))) for c in found if isinstance(c, dict)]


def report_data(text: str) -> ReportData | None:
    """The one reader: the Report data JSON object, or None when absent or unparsable."""
    found = fenced_blocks(sections(text).get("Report data", ""), "json")
    try:
        data = json.loads(found[0]) if found else None
    except ValueError:
        return None
    return data if isinstance(data, dict) else None  # type: ignore[return-value]


def load_gates(path: Path | None) -> dict[str, int] | None:
    """`{gate name: exit}` from a verify result file, or None when there is no such file."""
    if path is None or not path.is_file():
        return None
    try:
        gates = json.loads(path.read_text(encoding="utf-8")).get("gates", [])
        return {g["name"]: int(g["exit"]) for g in gates}
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return None


def structure(text: str) -> list[str]:
    """A Report data block with `schema_version` 1, a `gates` list and `unverified_claims` each with its verify command."""
    data = report_data(text)
    if data is None or data.get("schema_version") != 1:
        return ['### Report data needs a ```json block with "schema_version": 1']
    found = [] if isinstance(data.get("gates"), list) else ["Report data needs `gates`: [{name, exit}], [] when verify ran none"]
    claims = data.get("unverified_claims")
    if not isinstance(claims, list) or not all(isinstance(c, dict) and c.get("claim") and c.get("verify") for c in claims):
        found.append("Report data needs `unverified_claims`: [{claim, verify}] with a verify command each, [] for none")
    return found


def problems(text: str, gates: dict[str, int] | None, lenient: bool) -> list[str]:
    """Every problem with a report: its structure (unless lenient), and its `gates` against the verify result."""
    found = [] if lenient else structure(text)
    if gates is not None:
        reported = {g.get("name"): g.get("exit") for g in (report_data(text) or {}).get("gates") or [] if isinstance(g, dict)}
        if reported != gates:
            found.append(f"Report data gates {reported} differ from the verify result {gates}")
    return found


def capped(text: str, limit: int) -> list[str]:
    """The Unverified claims for a confirmation step: at most `limit`, then a pointer to the rest."""
    claims = unverified_claims(text)
    lines = [f"- {claim} — verify: `{command}`" for claim, command in claims[:limit]]
    if len(claims) > limit:
        lines.append(f"(+{len(claims) - limit} more in REPORT.md)")
    return lines


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="crew-verify.py report-check", description="Check a builder REPORT.md against a crew-verify.py gates.json.")
    parser.add_argument("report", type=Path, help="the REPORT.md (or part report) to check; - reads a draft on stdin")
    parser.add_argument("--gates", type=Path, default=None, help="the JSON file `verify` wrote")
    parser.add_argument("--lenient", action="store_true", help="accept a report without the new sections")
    parser.add_argument("--unverified", type=int, default=None, metavar="N", help="print at most N unverified claims and check nothing")
    args = parser.parse_args(argv)
    try:
        text = sys.stdin.read() if str(args.report) == "-" else args.report.read_text(encoding="utf-8")
    except OSError as error:
        print(f"report-check: {error}", file=sys.stderr)
        return 2
    if args.unverified is not None:
        print("\n".join(capped(text, args.unverified)))
        return 0
    found = problems(text, load_gates(args.gates), args.lenient)
    for line in found:
        print(f"report-check: {line}", file=sys.stderr)
    print("report-check: " + ("FAIL" if found else "ok"))
    return 1 if found else 0
