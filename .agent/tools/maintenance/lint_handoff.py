#!/usr/bin/env python3
"""The handoff grammar: one `> Next:` trailer, last line, naming a command the router recognizes.

Every stage of the pipeline ends by handing text to a session, and the trailer is the one line that
says what happens next. It had drifted into six shapes across fourteen files, none checked, so a
reader could not tell a real handoff from a sentence that merely contained the token. The rule
constrains trailers that exist rather than requiring one everywhere: a persona ends on its verdict by
contract, and most skills document output instead of emitting a trailer of their own.

`Next:` inside backticks documents a branch's output — `crew-test` prints one of three verdicts, and
`output-formats` describes what a review ends with — so only unbackticked text counts. One documented
exception: a PR review hands off to a person (`paste the bodies from comments.md onto PR #<n>`), which
names no `crew` verb and is accepted by its own prefix.
"""
from __future__ import annotations

import re
from pathlib import Path

from lint_files import rel
from lint_references import routing_commands

Findings = list[tuple[str, int, str, str]]

TRAILER = re.compile(r"^\s*> Next: (?P<body>.*)$")
ANY_NEXT = re.compile(r"Next:")
CREW_COMMAND = re.compile(r"`(crew [^`]+)`")
FENCE = re.compile(r"^\s*(```|~~~)")
# `output-formats.md:12`: a PR review's findings are pasted by a person, not handed to a command.
HUMAN_HANDOFF = "paste the bodies from"


def handoff_files(root: Path) -> list[Path]:
    """Every file the grammar governs: skills, agents and their references, and rules."""
    paths: list[Path] = []
    paths.extend(sorted((root / ".cursor/skills").glob("*/SKILL.md")))
    paths.extend(sorted((root / ".cursor/agents").glob("*.md")))
    paths.extend(sorted((root / ".cursor/agents").glob("*/references/*.md")))
    # The shared references load beside every agent, so the grammar governs them too: a trailer rule
    # stated in `dispatch.md` and a stray `Next:` beside it belong to the same contract.
    paths.extend(sorted((root / ".cursor/agents/references").glob("*.md")))
    paths.extend(sorted((root / ".cursor/skills").glob("*/references/*.md")))
    for rule_dir in (root / "rules", root / ".cursor/rules"):
        if rule_dir.is_dir():
            paths.extend(sorted(rule_dir.glob("*.mdc")))
            break
    return [path for path in paths if path.is_file()]


def fenced_lines(text: str) -> list[tuple[int, str]]:
    """Each line with its number, from outside fenced blocks: a fence holds examples, not a handoff."""
    kept: list[tuple[int, str]] = []
    in_fence = False
    for number, line in enumerate(text.splitlines(), 1):
        if FENCE.match(line):
            in_fence = not in_fence
            continue
        if not in_fence:
            kept.append((number, line))
    return kept


def prose_lines(text: str) -> list[tuple[int, str]]:
    """The same lines with every `code span` blanked out, so a quoted token is not a handoff.

    A span may wrap across lines — a skill that prints one of three next steps quotes each one — so
    the span is tracked across the whole file rather than matched per line. A span delimited by a run
    of backticks closes only on a run of the same length, which is how a quoted handoff is written
    inside a file that also uses single-backtick spans.
    """
    kept: list[tuple[int, str]] = []
    in_fence = False
    span = 0
    for number, line in enumerate(text.splitlines(), 1):
        if not span and FENCE.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        visible: list[str] = []
        index = 0
        while index < len(line):
            char = line[index]
            if char != "`":
                visible.append(" " if span else char)
                index += 1
                continue
            run = len(line) - len(line[index:].lstrip("`"))
            if span == 0:
                span = run
            elif run == span:
                span = 0
            visible.append(" " * run)
            index += run
        kept.append((number, "".join(visible).rstrip()))
    return kept


def trailer_problems(name: str, text: str, verbs: set[str]) -> Findings:
    """The rules for a file that emits a trailer: exactly one, last, and every verb resolvable."""
    lines = fenced_lines(text)
    trailers = [(number, line) for number, line in lines if TRAILER.match(line)]
    if not trailers:
        return []
    if len(trailers) > 1:
        return [(name, number, "handoff-multiple-trailers",
                 f"a file declares one handoff trailer; this is number {index} of {len(trailers)}")
                for index, (number, _) in enumerate(trailers, 1) if index > 1]
    number, line = trailers[0]
    last = next((candidate for candidate, value in reversed(lines) if value.strip()), 0)
    if last != number:
        return [(name, number, "handoff-trailer-not-last",
                 "the trailer must be the file's last non-empty line, or nothing after it runs")]
    body = TRAILER.match(line).group("body")
    named = CREW_COMMAND.findall(body)
    problems: Findings = []
    for command in named:
        verb = command.split()[1]
        if verb not in verbs:
            problems.append((name, number, "handoff-unrouted-command",
                             f"`{command}` has no row in crew-router.mdc"))
    if not named and HUMAN_HANDOFF not in body:
        problems.append((name, number, "handoff-no-command",
                         "a trailer names a `crew <verb>` command, or the documented "
                         f"`{HUMAN_HANDOFF}` action for a PR review"))
    return problems


def stray_next_problems(name: str, text: str, claimed: set[int] | None = None) -> Findings:
    """A file may not carry an unbackticked `Next:` that reads as one, beyond its own trailer.

    `claimed` holds the line numbers the trailer check already accounted for, so a file with one
    trailer is still checked everywhere else: two handoff sentences in one file is the shape this
    rule exists to stop, and treating "has a trailer" as "is done" hid exactly that.
    """
    seen = claimed or set()
    return [(name, number, "handoff-stray-next",
             "`Next:` outside a quoted trailer is not a handoff; wrap the example in backticks")
            for number, line in prose_lines(text)
            if ANY_NEXT.search(line) and number not in seen]


def lint_handoff(root: Path, router: Path) -> Findings:
    """Check every governed file: trailers are well formed, and no stray `Next:` claims to be one."""
    verbs = routing_commands(router.read_text(encoding="utf-8")) if router.exists() else set()
    findings: Findings = []
    for path in handoff_files(root):
        name = rel(root, path)
        text = path.read_text(encoding="utf-8", errors="replace")
        trailers = [number for number, line in fenced_lines(text) if TRAILER.match(line)]
        if trailers:
            findings.extend(trailer_problems(name, text, verbs))
        findings.extend(stray_next_problems(name, text, set(trailers)))
    return findings
