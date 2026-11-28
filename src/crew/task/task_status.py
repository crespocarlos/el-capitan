"""What a task's records say: the `## Status` contract, the review location, the typed `## Tests` rule.

Usage: task_status.py [--head] <SPEC.md>. The status is the first line after a column-0 `## Status`
heading (canonical uppercase token). The review is `REVIEW.md` beside the task or the directory
`run.json` records. Gate 1 requires every `## Tests` layer to carry a Command or a bare `none`.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

REVIEWED_AT = re.compile(r"^Reviewed at:\s*([0-9a-f]{7,40})\s*$", re.M)
LOCAL = "REVIEW.md"
# The one reader of a review's `Verdict:` word: `##` and bold allowed, any case. The word is the whole token after
# it, so `pass-with-nits` is no code verdict.
VERDICT_LINE = re.compile(r"^[ \t]*(?:#{1,6}[ \t]*)?(?:\*\*)?Verdict:(?:\*\*)?[ \t]*([\w-]*)", re.M | re.I)


def verdict_word(text: str) -> str | None:
    """The word of the last `Verdict:` line that has one, as written, or None."""
    words = [word for word in VERDICT_LINE.findall(text) if word]
    return words[-1] if words else None


def recorded_review_dir(task: Path) -> Path | None:
    """The review directory `run.json` in the task names, when that directory still exists."""
    try:
        record = json.loads((task / "run.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    value = record.get("review_dir") if isinstance(record, dict) else None
    if not isinstance(value, str) or not value:
        return None
    directory = Path(value)
    return directory if directory.is_dir() else None


def review_file(task: Path) -> Path | None:
    """The review the gates read, or None when this task has no readable review anywhere.

    The task's own copy wins: it is what a person reads beside the spec, and it is the only file a
    `crew review address` rewrites. The recorded directory is the fallback a PR-mode review needs.
    """
    local = task / LOCAL
    if local.is_file():
        return local
    directory = recorded_review_dir(task)
    candidate = directory / LOCAL if directory is not None else None
    return candidate if candidate is not None and candidate.is_file() else None


def reviewed_at(review: Path | None) -> str:
    """The `Reviewed at:` commit in a review's footer, or "" when it carries none.

    Only the footer is read: the lines from the last `> Next:` onward, or the last five non-empty
    lines when the file has no trailer. A finding may quote the line verbatim — the contract requires
    quoting — and a quote anywhere above the footer is not a claim about which tree was reviewed.
    Reading the whole file let such a quote satisfy the gate that proves a review covers HEAD.

    A fixed line count failed open instead: anything appended below the footer pushed the commit out
    of the window, and `task_gates` then treats a missing commit as warning-grade. Starting at the
    trailer keeps an addendum from silently disabling the check.
    """
    if review is None:
        return ""
    lines = [line for line in review.read_text(encoding="utf-8").splitlines() if line.strip()]
    start = next((index for index in range(len(lines) - 1, -1, -1) if lines[index].startswith("> Next:")), max(len(lines) - 5, 0))
    matches = REVIEWED_AT.findall("\n".join(lines[start:]))
    return matches[-1] if matches else ""


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
        tail = block[match.end() :]
        next_heading = re.search(r"^### ", tail, re.MULTILINE)
        sub = tail[: next_heading.start()] if next_heading else tail
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
    rest = text[match.end() :]
    next_section = re.search(r"^## [^#\s]", rest, re.MULTILINE)
    block = rest[: next_section.start()] if next_section else rest
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


def typed_test_commands(text: str) -> list[str]:
    """Every runnable Command of the `## Tests` block, in file order, backticks stripped; none-only ones left out."""
    match = re.search(r"^## Tests", text, re.MULTILINE)
    if not match:
        return []
    rest = text[match.end() :]
    next_section = re.search(r"^## [^#\s]", rest, re.MULTILINE)
    commands = []
    for found in TYPED_COMMAND.finditer(rest[: next_section.start()] if next_section else rest):
        value = next((group for group in found.groups() if group), "").strip().strip("`").strip()
        if value and value.lower() != "none" and not value.startswith("<"):
            commands.append(value)
    return commands


def typed_tests_problem(spec_path: Path) -> str:
    """Return the check's message when a typed ## Tests block has no runnable Command.

    A spec with no ## Tests section passes: it has no commands to run, which is a documented
    outcome, not an error.
    """
    try:
        return typed_tests_block_problem(Path(spec_path).read_text(encoding="utf-8"))
    except OSError as error:
        return f"validator could not run: {error}"


STATUS = re.compile(r"^(## Status[ \t]*\r?\n)([^\n#][^\n]*?)[ \t]*$", re.M)
STATES = ("DRAFTING", "APPROVED", "IMPLEMENTING", "ON-HOLD", "DONE")
# A user-only side state from the orchestrator rules: it is not a transition, but it is a value the
# store legitimately holds, so a rewrite reports it rather than rejecting the task outright.
SIDE_STATES = ("ABANDONED",)
ACCEPTED = STATES + SIDE_STATES


class StatusError(ValueError):
    """A status value outside the contract; the message names every allowed token."""


def spec_text(text: str) -> str:
    """`text` as a spec reader sees it: universal newlines, so a lone `\\r` or `\\r\\n` is a `\\n`.

    `Path.read_text` does the same on disk; the Status guard (`.claude/hooks/lib/spec_guard.py`) applies
    it to the text a write would leave, so both read one Status.
    """
    return text.replace("\r\n", "\n").replace("\r", "\n")


def spec_field(text: str, name: str) -> str:
    """The SPEC.md `## <name>:` value (`Branch`, `Base`), or "" when absent or still the template's `[...]` placeholder."""
    found = re.search(rf"^## {name}:[ \t]*`?([^`\s]+)`?[ \t\r]*$", text, re.M)
    return found.group(1) if found and not found.group(1).startswith("[") else ""


def status_of(text: str) -> str:
    """The status value of a spec's text (after `spec_text`), "" when unset."""
    match = STATUS.search(spec_text(text))
    return match.group(2).strip() if match else ""


def read_status(path: Path | str) -> str | None:
    """Return the status value, "" when unset, or None when the file is unreadable."""
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError:
        return None
    return status_of(text)


def head(value: str | None) -> str:
    """Normalized state token: `IMPLEMENTING`, `ON-HOLD`, `DONE`, or "".

    Trailing punctuation is not part of the state: a status written as a sentence (`DONE.`) and one
    written as a label are the same value, and a query that compared the raw text missed it.
    """
    return value.split()[0].upper().rstrip("(:.,;") if value else ""


def token(value: str | None) -> str:
    """The contract token of a status value, raising `StatusError` for anything unknown.

    The reader stays lenient — a listing must render a malformed task instead of dying on it — but
    a value that becomes authoritative is checked, so a typo fails where it is written rather than
    silently matching no transition rule.
    """
    candidate = head(value)
    if candidate and candidate not in ACCEPTED:
        raise StatusError(f"status {value.strip()!r} is not one of {', '.join(ACCEPTED)}")
    return candidate


def canonical(value: str | None) -> str:
    """The value with its token in the one allowed spelling and any suffix kept verbatim."""
    stripped = (value or "").strip()
    if not stripped:
        return ""
    word, _, rest = stripped.partition(" ")
    token(value)
    return word.upper().rstrip("(:.,;") + (f" {rest}" if rest else "")


def main(argv: list[str]) -> int:
    args = list(argv)
    normalized = False
    if args[:1] == ["--head"]:
        normalized, args = True, args[1:]
    if not args or args[0] in {"-h", "--help"}:
        print(__doc__.strip())
        return 0 if args else 2
    value = read_status(args[0])
    if value is None:
        print(f"task_status: cannot read {args[0]}", file=sys.stderr)
        return 2
    print(head(value) if normalized else value)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
