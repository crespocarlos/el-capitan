#!/usr/bin/env python3
"""`crew-review-findings.py consolidate`: group candidates, resolve hunks, draft `candidates.json`, and
render `report.md` from `consolidation.json` (`--render`).

Grouping never rewrites a finding, its title or its label: two emitted findings (`patch`, `decide`)
group when they name the same file and `kind` and their line ranges overlap. The representative keeps
`group_severity`, the others become `merged`. The report numbers emitted findings with their bodies.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from crew.lib.files import atomic_write
from crew.review.review_findings import is_path_prefix, read_findings
from crew.review.review_models import Finding
from crew.review.review_render import CLAUSE_DISPLAY_MAX, label_with_score

SCHEMA_VERSION = 1
SEVERITY_ORDER = ("blocking", "attention", "concern", "needs more info", "nit")
EMITTED = ("patch", "decide")


def add_consolidate_parser(commands) -> None:
    parser = commands.add_parser("consolidate", help="group candidates (same file, overlapping lines) into a draft candidates.json")
    parser.add_argument("--review-dir", required=True, type=Path)
    parser.add_argument("--input", type=Path, help="raw candidates; default <review-dir>/raw-candidates.json")
    parser.add_argument("--hunks", type=Path, help="hunks.json; default <review-dir>/hunks.json when present")
    parser.add_argument("--render", action="store_true", help="instead of drafting, write report.md from consolidation.json")
    parser.add_argument("--mode", default="self", help="named in the report heading (--render)")


def rank(finding: dict) -> tuple[int, int]:
    label = str(finding.get("label", "")).lower()
    score = finding.get("confidence")
    return (
        SEVERITY_ORDER.index(label) if label in SEVERITY_ORDER else len(SEVERITY_ORDER),
        -(score if isinstance(score, int) and not isinstance(score, bool) else 0),
    )


def span(finding: dict) -> tuple[str, int, int] | None:
    """`(file, first, last)` for a finding anchored to a file and a line, else None (never grouped)."""
    path, line = finding.get("file"), finding.get("line")
    if not isinstance(path, str) or not path or isinstance(line, bool) or not isinstance(line, int):
        return None
    end = finding.get("line_end")
    return path, line, end if isinstance(end, int) and not isinstance(end, bool) and end >= line else line


def clusters(findings: list[dict]) -> list[list[int]]:
    """Index lists of emitted findings sharing a file with transitively overlapping ranges (size 2 or more)."""
    spans = {i: s for i, f in enumerate(findings) if f.get("disposition") in EMITTED and (s := span(f))}
    kind = lambda i: str(findings[i].get("kind", "")).strip().lower()  # noqa: E731
    done: list[list[int]] = []
    for path, same in sorted({(s[0], kind(i)) for i, s in spans.items()}):
        current: list[int] = []
        reach = 0
        for i in sorted((i for i, s in spans.items() if s[0] == path and kind(i) == same), key=lambda i: spans[i][1]):
            if current and spans[i][1] > reach:
                done.append(current)
                current = []
            current.append(i)
            reach = max(reach, spans[i][2]) if len(current) > 1 else spans[i][2]
        done.append(current)
    return [c for c in done if len(c) > 1]


def resolve_hunks(finding: dict, hunks: list[dict]) -> list[str]:
    """Hunk ids whose new-file lines cover the finding's file and line range."""
    found = span(finding)
    if not found:
        return []
    path, first, last = found
    ids = []
    for hunk in hunks:
        if not isinstance(hunk.get("file"), str) or not is_path_prefix(path, hunk["file"]):
            continue
        if any(isinstance(row.get("n"), int) and first <= row["n"] <= last for row in hunk.get("lines") or []):
            ids.append(hunk["id"])
    return ids


def group_all(findings: list[dict]) -> list[dict]:
    """Mark members in place (`group`, `merged_into`, `group_severity`) and return the side list."""
    groups = []
    for number, members in enumerate(clusters(findings), 1):
        gid = f"g{number}"
        rep = min(members, key=lambda i: (rank(findings[i]), i))
        for i in members:
            findings[i]["group"] = gid
            if i != rep:
                findings[i]["disposition"] = "merged"
                findings[i]["merged_into"] = gid
        findings[rep]["group_severity"] = findings[rep]["label"]
        first, last = min(span(findings[i])[1] for i in members), max(span(findings[i])[2] for i in members)
        groups.append(
            {
                "id": gid,
                "file": findings[rep]["file"],
                "lines": [first, last],
                "representative": findings[rep].get("title"),
                "group_severity": min(
                    (findings[i]["label"] for i in members),
                    key=lambda label: SEVERITY_ORDER.index(str(label).lower()) if str(label).lower() in SEVERITY_ORDER else 99,
                ),
                "members": [findings[i].get("title") for i in members],
            }
        )
    return groups


def draft(args: argparse.Namespace) -> int:
    source = args.input or args.review_dir / "raw-candidates.json"
    data = json.loads(source.read_text(encoding="utf-8"))
    findings = data.get("findings") if isinstance(data, dict) else data
    if not isinstance(findings, list) or not all(isinstance(f, dict) for f in findings):
        raise ValueError(f"{source}: expected a JSON list of findings or an object with a findings list")
    for f in findings:
        for key in ("group", "group_severity", "merged_into"):
            f.pop(key, None)
    hunks_path = args.hunks or (args.review_dir / "hunks.json")
    hunks = json.loads(hunks_path.read_text(encoding="utf-8")).get("hunks", []) if hunks_path.is_file() else []
    for f in findings:
        if "hunks" not in f and (ids := resolve_hunks(f, hunks)):
            f["hunks"] = ids
    groups = group_all(findings)
    target = args.review_dir / "candidates.json"
    atomic_write(target, json.dumps({"schema_version": SCHEMA_VERSION, "findings": findings, "groups": groups}, indent=2) + "\n")
    print(
        json.dumps(
            {
                "candidates": str(target),
                "findings": len(findings),
                "groups": len(groups),
                "merged": sum(1 for f in findings if f.get("disposition") == "merged"),
            }
        )
    )
    return 0


def consolidate(args: argparse.Namespace) -> int:
    if not args.review_dir.is_dir():
        raise ValueError(f"no such review directory: {args.review_dir}")
    return render_report(args.review_dir, args.mode) if args.render else draft(args)


def anchor_text(finding: Finding) -> str:
    """`file:line` as `persist` reads it back: the record's own file and line, else its evidence."""
    if finding.text("file") and finding.text("line").isdigit():
        return f"{finding.text('file')}:{finding.text('line')}"
    return finding.text("evidence")


def originals(findings: list[Finding], representative: Finding) -> list[Finding]:
    """The merged findings whose `merged_into` is the representative's group id (never its title)."""
    group = representative.extra.get("group")
    return [f for f in findings if group and f.disposition == "merged" and f.extra.get("merged_into") == group]


def body_text(finding: Finding) -> str:
    """The finding's prose under its anchor, rendered as one quoted line: the first paragraph of its `comment`, else
    of its `validation`, capped at `CLAUSE_DISPLAY_MAX`; a paragraph that opens a fence is skipped."""
    for name in ("comment", "validation"):
        for paragraph in re.split(r"\n\s*\n", finding.text(name).strip()):
            if paragraph.strip() and not paragraph.lstrip().startswith(("```", "~~~")):
                text = " ".join(paragraph.split())
                return text if len(text) <= CLAUSE_DISPLAY_MAX else text[: CLAUSE_DISPLAY_MAX - 1].rstrip() + "…"
    return ""


def excerpt_block(finding: Finding) -> list[str]:
    """A `[blocking]` finding's `excerpt` as an indented fence (finding formats: its anchored snippet), else []."""
    excerpt = finding.text("excerpt").strip("\n")
    if finding.label != "blocking" or not excerpt.strip():
        return []
    fence = "````" if "```" in excerpt else "```"
    return [f"   {fence}", *(f"   {line}" for line in excerpt.splitlines()), f"   {fence}"]


def entry(number: int, finding: Finding, absorbed: list[Finding]) -> list[str]:
    lines = [f"{number}. {label_with_score(finding)} — {finding.title}"]
    if anchor_text(finding):
        lines.append(f"   Anchor: {anchor_text(finding)}")
    if body_text(finding):  # quoted: persist never reads a label, anchor or verdict from a quoted line
        lines.append(f"   > {body_text(finding)}")
    lines.extend(excerpt_block(finding))
    if finding.extra.get("anchor") == "non-hunk":
        lines.append("   Outside the diff: read at the reviewed head, not a changed hunk.")
    if finding.extra.get("group_severity"):
        lines.append(f"   Group severity: {finding.extra['group_severity']}")
    if absorbed:
        lines.append(f"   Merged {len(absorbed)} duplicate{'' if len(absorbed) == 1 else 's'}; originals:")
        for other in absorbed:
            who = ", ".join(other.persona) if isinstance(other.persona, list) else "unattributed"
            lines.append(f"   - {label_with_score(other)} {other.title} ({who}; {anchor_text(other) or 'no anchor'})")
    return lines


def render_report(review_dir: Path, mode: str) -> int:
    source = review_dir / "consolidation.json"
    if not source.is_file():
        raise ValueError(f"{source} not found: run `normalize --output` on the draft candidates first")
    findings = read_findings(source)
    emitted = [f for f in findings if f.is_emitted()]
    merged = [f for f in findings if f.disposition == "merged"]
    body = [
        f"## Review: {mode}",
        "",
        f"Consolidated {len(findings)} candidates: {len(emitted)} emitted, merged {len(merged)} duplicates."
        if merged
        else f"Consolidated {len(findings)} candidates: {len(emitted)} emitted, no duplicates merged.",
        "",
    ]
    for number, finding in enumerate(emitted, 1):
        body.extend(entry(number, finding, originals(findings, finding)))
        body.append("")
    if not emitted:
        body.append("No emitted findings.")
    target = review_dir / "report.md"
    atomic_write(target, "\n".join(body).rstrip() + "\n")
    print(f"report: {target} ({len(emitted)} emitted, merged {len(merged)} duplicates)", file=sys.stdout)
    return 0
