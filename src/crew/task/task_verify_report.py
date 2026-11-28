"""`crew-verify.py report-check`: a builder's REPORT.md checked against the gates JSON a verify run wrote.

`### Quality gates`, `### Unverified claims` and `### Report data` must agree with the gates JSON;
`--lenient` accepts a report without them; the parsers return empty for a report that has none.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from crew.lib.markdown import fenced_blocks

HEADING = re.compile(r"^###\s+(.+?)\s*$", re.M)
EXIT_LINE = re.compile(r"^\s*([A-Za-z0-9][\w./-]*) exit=(\d+)(?: cached)?\s*$", re.M)
CLAIM = re.compile(r"^\s*[-*]\s+`?([A-Za-z0-9][\w./-]*)`?\s*(?:—|--|-|:)\s*[*_`]*([A-Za-z]+)", re.M)
VERDICTS = ("pass", "fail", "skipped")
UNVERIFIED = re.compile(r"^\s*[-*]\s+(.+?)\s*(?:—|--)\s*verify:\s*`([^`]+)`", re.M)

REQUIRED = ("Quality gates", "Unverified claims", "Report data")


def sections(text: str) -> dict[str, str]:
    """Each `### heading` of the report mapped to its body; empty for a report with none."""
    found = list(HEADING.finditer(text))
    return {m.group(1): text[m.end() : found[i + 1].start() if i + 1 < len(found) else len(text)] for i, m in enumerate(found)}


def gate_exits(body: str) -> dict[str, int]:
    return {m.group(1): int(m.group(2)) for m in EXIT_LINE.finditer(body)}


def unverified_claims(text: str) -> list[tuple[str, str]]:
    """`(claim, command)` pairs from the Unverified claims section; `none` or no section is empty."""
    return [(m.group(1), m.group(2)) for m in UNVERIFIED.finditer(sections(text).get("Unverified claims", ""))]


def report_data(text: str) -> dict | None:
    """The Report data JSON object, or None when absent or unparsable."""
    found = fenced_blocks(sections(text).get("Report data", ""), "json")
    try:
        data = json.loads(found[0]) if found else None
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def load_gates(path: Path | None) -> dict[str, int] | None:
    """`{gate name: exit}` from a verify result file, or None when there is no such file."""
    if path is None or not path.is_file():
        return None
    try:
        gates = json.loads(path.read_text(encoding="utf-8")).get("gates", [])
        return {g["name"]: int(g["exit"]) for g in gates}
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return None


def compare(body: str, actual: dict[str, int]) -> list[str]:
    """Mismatches between the Quality gates section and the verify result."""
    found: list[str] = []
    copied = gate_exits(body)
    for gate, code in actual.items():
        if gate not in copied:
            found.append(f"gate {gate} (exit={code}) is not copied into Quality gates")
        elif copied[gate] != code:
            found.append(f"gate {gate}: report says exit={copied[gate]}, verify says exit={code}")
    for gate in copied.keys() - actual.keys():
        found.append(f"gate {gate} is in the report but not in the verify result")
    return found + claim_problems(body, actual)


def claim_problems(body: str, actual: dict[str, int]) -> list[str]:
    """Exactly one claim line per gate, worded `pass`, `fail` or `skipped`, that agrees with its exit."""
    found: list[str] = []
    claims: dict[str, list[str]] = {}
    for match in CLAIM.finditer(body):
        claims.setdefault(match.group(1), []).append(match.group(2))
    for gate, code in actual.items():
        words = claims.get(gate, [])
        if len(words) != 1:
            found.append(f"no claim line for gate {gate}" if not words else f"{len(words)} claim lines for gate {gate}; write one")
        for word in words:
            verdict = word.lower()
            if verdict not in VERDICTS:
                found.append(f"claim for gate {gate} says `{word}`; write pass, fail or skipped")
            elif verdict == "skipped" or (verdict == "pass") != (code == 0):
                found.append(f"claim `{gate}: {verdict}` contradicts exit={code}" + (" (verify ran this gate)" if verdict == "skipped" else ""))
    return found


def structure(text: str) -> list[str]:
    """Missing sections, a missing JSON block, and unverified claims with no verifying command."""
    found = [f"missing section: ### {name}" for name in REQUIRED if name not in sections(text)]
    data = report_data(text)
    if "Report data" in sections(text) and (data is None or data.get("schema_version") != 1):
        found.append('Report data needs a ```json block with "schema_version": 1')
    body = sections(text).get("Unverified claims", "")
    bullets = [x for x in body.splitlines() if re.match(r"^\s*[-*]\s", x)]
    for line in bullets:
        if not UNVERIFIED.match(line):
            found.append(f"unverified claim without `— verify: `<command>``: {line.strip()[:80]}")
    if "Unverified claims" in sections(text) and not bullets and body.strip().strip("`*- ").lower() != "none":
        found.append("Unverified claims must list claims with a verify command, or say `none`")
    return found


def problems(text: str, gates: dict[str, int] | None, lenient: bool) -> list[str]:
    """Every problem with a report; a lenient run skips the structure check of an old report."""
    found = [] if lenient else structure(text)
    if gates is not None:
        found += compare(sections(text).get("Quality gates", ""), gates)
    data = report_data(text)
    if gates is not None and data and isinstance(data.get("gates"), list):
        reported = {g.get("name"): g.get("exit") for g in data["gates"] if isinstance(g, dict)}
        if reported != gates:
            found.append("Report data gates differ from the verify result")
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
