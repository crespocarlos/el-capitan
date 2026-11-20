#!/usr/bin/env python3
"""The typed `## Tests` validator that Gate 1 applies before a spec may be approved.

A spec's tests section becomes a commitment at approval, so an unapprovable one has to fail there
rather than at `crew test` later. The rule: every recognised layer heading carries a runnable
Command, and a bare `none` documents an intentional absence (which `crew test` reports as WARN)
instead of passing as a commitment.
"""
from __future__ import annotations

import re
from pathlib import Path

TYPED_LAYERS = ("Unit", "Integration", "E2E", "Validation")
TYPED_COMMAND = re.compile(
    r"^\s*-\s*\*\*Command\*\*:\s*(.+)$|^\s*\*\*Command\*\*:\s*(.+)$|^\s*-\s*Command:\s*(.+)$"
    r"|^\s*Command:\s*(.+)$",
    re.M | re.IGNORECASE,
)


def layer_block(block: str, layer: str) -> str | None:
    """The failure message for one typed layer heading, or None when it has a runnable Command.

    Specs in the wild write `### unit` and `### E2E tests`, so headings match case-insensitively: a
    case-sensitive pattern skipped both the layer and its Command check, making an unapprovable
    block pass vacuously.
    """
    for match in re.finditer(rf"^### {layer}\b[^\n]*$", block, re.MULTILINE | re.IGNORECASE):
        tail = block[match.end():]
        next_heading = re.search(r"^### ", tail, re.MULTILINE)
        sub = tail[:next_heading.start()] if next_heading else tail
        command = TYPED_COMMAND.search(sub)
        if not command:
            return f"[fail] spec-typed-tests: ### {layer} missing Command line"
        value = next((group for group in command.groups() if group), "").strip()
        if not value or value.lower() == "none" or value == '<test command or "none">':
            return f"[fail] spec-typed-tests: ### {layer} Command empty or none-only"
    return None


def typed_tests_block_problem(text: str) -> str:
    """Return the [fail] message when a typed ## Tests block has no runnable Command, else ''."""
    match = re.search(r"^## Tests", text, re.MULTILINE)
    if not match:
        return ""
    rest = text[match.end():]
    next_section = re.search(r"^## [^#\s]", rest, re.MULTILINE)
    block = rest[:next_section.start()] if next_section else rest
    seen = 0
    for layer in TYPED_LAYERS:
        found = list(re.finditer(rf"^### {layer}\b[^\n]*$", block, re.MULTILINE | re.IGNORECASE))
        if not found:
            continue
        seen += len(found)
        problem = layer_block(block, layer)
        if problem:
            return problem
    if not seen:
        return "[fail] spec-typed-tests: ## Tests has no recognized layer heading"
    return ""


def typed_tests_problem(spec_path: Path) -> str:
    """Return the check's message when a typed ## Tests block has no runnable Command.

    A spec with no ## Tests section passes: `crew test` reports WARN for it, which is a documented
    outcome, not an error.
    """
    try:
        return typed_tests_block_problem(Path(spec_path).read_text(encoding="utf-8"))
    except OSError as error:
        return f"validator could not run: {error}"
