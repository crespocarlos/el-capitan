"""The deterministic checks a held-out prompt case asserts, one function per artifact property.

A prompt's only test is what it produces, but a model call makes a suite non-hermetic and a score
makes a regression arguable. So every check here is structural: it reads an artifact as text and
names what is missing. A prompt change then fails a case only when the artifact shape it promises
actually changed, and the same check runs against a deliberately broken sample to prove it is not
vacuous.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

_TOOLS = Path(__file__).resolve().parents[2] / ".agent" / "tools" / "task"
if str(_TOOLS) not in sys.path:
    sys.path.insert(0, str(_TOOLS))

from task_typed_tests import typed_tests_block_problem  # noqa: E402

LABELS = {"blocking", "attention", "nit", "needs more info", "concern"}
# The score suffix a label may carry: `attention · 4`. Stripped before a label is compared, so the
# label vocabulary stays one set rather than one per rendering.
LABEL_WITH_SCORE = re.compile(r"\s*·\s*[1-5]\s*$")
SPEC_LABELS = {"blocking", "concern", "needs more info", "nit"}
MEMORY_TYPES = {"user", "feedback", "project", "reference", "failure-shield", "procedure",
                "observation"}
COMMIT_TYPES = ("feat", "fix", "refactor", "test", "docs", "chore", "perf", "build", "ci",
                "style", "revert")
HEADING = re.compile(r"^(#{1,6}) ")
# The label may carry its confidence score beside it (`[attention · 4]`), so the bracket is matched
# as a whole and the score is stripped from the captured label.
FINDING = re.compile(r"^\d+\.\s*\[([^\]]+)\]")
VERDICT = re.compile(r"^(?:\*\*)?Verdict:?(?:\*\*)?\s+([A-Za-z]+)(.*)$")
NIT_CAP = 4
FINDING_CAP = 12


def block_under(text: str, heading: str) -> str:
    """The text under `heading` up to the next heading of the same or a higher level."""
    lines = text.splitlines()
    wanted = heading.rstrip()
    for index, line in enumerate(lines):
        if line.strip() == wanted:
            level = len(HEADING.match(line).group(1)) if HEADING.match(line) else 1
            for offset in range(index + 1, len(lines)):
                match = HEADING.match(lines[offset])
                if match and len(match.group(1)) <= level:
                    return "\n".join(lines[index + 1:offset])
            return "\n".join(lines[index + 1:])
    return ""


def headings(artifact: str, names: list[str]) -> list[str]:
    """Every named heading must appear as a heading line of its own."""
    present = {line.strip() for line in artifact.splitlines() if HEADING.match(line)}
    return [f"missing heading: {name}" for name in names if name not in present]


def regex_present(artifact: str, patterns: list[str]) -> list[str]:
    return [f"missing pattern: {pattern}" for pattern in patterns
            if not re.search(pattern, artifact, re.M)]


def regex_absent(artifact: str, patterns: list[str]) -> list[str]:
    return [f"forbidden pattern: {pattern}" for pattern in patterns
            if re.search(pattern, artifact, re.M)]


def typed_tests(artifact: str, layers: list[str]) -> list[str]:
    """The same validator Gate 1 applies: a kept layer needs a runnable Command."""
    problems = headings(artifact, [f"### {layer}" for layer in layers])
    problem = typed_tests_block_problem(artifact)
    return problems + ([problem] if problem else [])


def criteria_verifiable(artifact: str) -> list[str]:
    """Each criterion carries a pass/fail check, and the set shows at least one WHEN/THEN."""
    section = block_under(artifact, "## Acceptance criteria")
    if not section.strip():
        return ["missing section: ## Acceptance criteria"]
    problems = []
    for line in section.splitlines():
        if not re.match(r"^- \[[ x]\] ", line):
            continue
        if not re.search(r"verify:", line, re.I):
            problems.append(f"criterion without a verify check: {line.strip()[:70]}")
    if not re.search(r"WHEN .+ THEN .+", section, re.I):
        problems.append("no criterion states WHEN <trigger> THEN <outcome>")
    return problems


def tasks_verify(artifact: str) -> list[str]:
    """Every task ends with a Verify line, so the builder knows what proves it."""
    section = block_under(artifact, "## Tasks")
    if not section.strip():
        return ["missing section: ## Tasks"]
    problems, current = [], ""
    for line in section.splitlines() + ["- [ ] 0) sentinel"]:
        if re.match(r"^- \[[ x]\] \d+\)", line):
            if current and not re.search(r"verify:", current, re.I):
                problems.append(f"task without Verify: {current.splitlines()[0].strip()[:70]}")
            current = line
        elif current:
            current += "\n" + line
    return problems


def finding_lines(artifact: str) -> list[tuple[str, str]]:
    """Each finding as (label, its own block), split at the next numbered finding.

    A label carrying its confidence score (`[attention · 4]`) is normalized to the label: the score
    is a separate field with its own checks, and requiring every assertion to know the syntax would
    make the label vocabulary two vocabularies.
    """
    blocks: list[tuple[str, str]] = []
    label, lines = "", []
    for line in artifact.splitlines():
        match = FINDING.match(line)
        if match:
            if label:
                blocks.append((label, "\n".join(lines)))
            label, lines = LABEL_WITH_SCORE.sub("", match.group(1)).strip().lower(), [line]
        elif label:
            lines.append(line)
    if label:
        blocks.append((label, "\n".join(lines)))
    return blocks


def finding_contract(artifact: str, anchors: bool) -> list[str]:
    """Every finding uses a known label; a code finding cites a line and a blocking one shows code."""
    findings = finding_lines(artifact)
    if not findings:
        return ["no numbered findings found"]
    problems = []
    for label, body in findings:
        if label not in LABELS:
            problems.append(f"label {label!r} is not one of {sorted(LABELS)}")
        if anchors and label in {"blocking", "attention"}:
            if not re.search(r"line \d+|:\d+", body):
                problems.append(f"{label} finding cites no file:line anchor")
        if anchors and label == "blocking" and "```" not in body:
            problems.append("blocking finding carries no code snippet")
    nits = sum(1 for label, _ in findings if label == "nit")
    if nits > NIT_CAP:
        problems.append(f"{nits} nits exceeds the cap of {NIT_CAP}")
    if len([body for label, body in findings if label != "nit"]) > FINDING_CAP:
        problems.append(f"more than {FINDING_CAP} severity findings")
    return problems


def spec_labels(artifact: str) -> list[str]:
    """A spec or idea review uses the evaluative label set, not the code one."""
    allowed = SPEC_LABELS | {"attention"}
    return [f"label {label!r} is not evaluative" for label, _ in finding_lines(artifact)
            if label not in allowed]


def verdict_line(artifact: str, values: list[str], reason: bool = True) -> list[str]:
    """One verdict line from the prompt's own vocabulary, with the deciding reason beside it."""
    found = [match for line in artifact.splitlines()
             for match in [VERDICT.match(line.strip())] if match]
    if not found:
        return ["no `Verdict:` line"]
    problems = []
    for match in found:
        if match.group(1).lower() not in {value.lower() for value in values}:
            problems.append(f"verdict {match.group(1)!r} is not one of {values}")
        if reason and len(match.group(2).strip(" —-–.:")) < 8:
            problems.append(f"verdict {match.group(1)!r} carries no reason")
    return problems


def fix_on_blocking(artifact: str) -> list[str]:
    """An evaluative blocking finding states the exact Fix, per the finding format."""
    return [f"{label} finding has no Fix:" for label, body in finding_lines(artifact)
            if label in {"blocking", "concern"} and "Fix:" not in body]


def single_line(artifact: str) -> list[str]:
    lines = [line for line in artifact.splitlines() if line.strip()]
    return [] if len(lines) == 1 else [f"{len(lines)} non-empty lines; the format is one line"]


def conventional_commit(artifact: str) -> list[str]:
    """One Conventional Commits subject: type(scope): imperative, no period, within 72 columns."""
    problems = single_line(artifact)
    if problems:
        return problems
    subject = next(line for line in artifact.splitlines() if line.strip()).strip()
    kind = next((name for name in COMMIT_TYPES if re.match(rf"^{name}(\([^)]+\))?: ", subject)),
                 "")
    if not kind:
        problems.append(f"subject has no Conventional Commits type: {subject!r}")
    if subject.rstrip().endswith("."):
        problems.append("subject ends with a period")
    if len(subject) > 72:
        problems.append(f"subject is {len(subject)} columns, over 72")
    if kind and re.match(rf"^{kind}(\([^)]+\))?: [A-Z]", subject):
        problems.append("description starts with a capital; use the imperative mood")
    return problems


def bullets_max(artifact: str, section: str, cap: int) -> list[str]:
    """A reviewer-facing bullet list stays within its cap."""
    block = block_under(artifact, section)
    if not block.strip():
        return [f"missing section: {section}"]
    count = sum(1 for line in block.splitlines() if re.match(r"^- ", line))
    return [f"{count} bullets under {section}, over {cap}"] if count > cap else []


def closes_first(artifact: str) -> list[str]:
    """The closing reference is the first thing in a PR body, which is how GitHub links it."""
    lines = [line for line in artifact.splitlines() if line.strip()]
    return [] if lines and lines[0].lower().startswith("closes ") else \
        ["first line is not a `closes <issue>` reference"]


def frontmatter_fields(artifact: str, fields: list[str]) -> list[str]:
    """The unit's frontmatter carries every field the store reads back."""
    if not artifact.startswith("---\n"):
        return ["artifact does not start with YAML frontmatter"]
    try:
        header = artifact.split("---\n", 2)[1]
    except IndexError:
        return ["frontmatter is not closed"]
    present = {line.split(":", 1)[0].strip() for line in header.splitlines() if ":" in line}
    return [f"frontmatter lacks {field}" for field in fields if field not in present]


def memory_type(artifact: str) -> list[str]:
    match = re.search(r"^type:\s*(\S+)\s*$", artifact, re.M)
    if not match:
        return ["frontmatter has no type"]
    return [] if match.group(1) in MEMORY_TYPES else [f"unknown memory type: {match.group(1)}"]


def body_sections(artifact: str, markers: list[str]) -> list[str]:
    """The body states why, how to apply, and where the lesson stops — the capture contract."""
    body = artifact.split("---\n", 2)[2] if artifact.count("---\n") >= 2 else artifact
    return [f"body lacks {marker}" for marker in markers if marker not in body]


def router_rows(artifact: str, triggers: list[str]) -> list[str]:
    """Every documented `crew <verb>` has exactly one routing row with a named handler."""
    rows: dict[str, list[str]] = {}
    for line in artifact.splitlines():
        if not line.startswith("| `crew "):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) < 2:
            continue
        trigger = cells[0].strip("`")
        rows.setdefault(trigger.split()[1].split("`")[0], []).append(cells[1])
    problems = []
    for verb in triggers:
        handlers = rows.get(verb, [])
        if not handlers:
            problems.append(f"no routing row for `crew {verb}`")
        elif len(handlers) > 1:
            problems.append(f"`crew {verb}` has {len(handlers)} rows")
        elif not handlers[0].strip("` "):
            problems.append(f"`crew {verb}` has an empty handler")
    return problems


def tasks_line(artifact: str) -> list[str]:
    return [] if re.search(r"\*\*Tasks:\*\* \d+/\d+ passed", artifact) else \
        ["missing `**Tasks:** N/M passed` line"]


def report_pointer(artifact: str) -> list[str]:
    """The builder's reply points at REPORT.md instead of restating it.

    The file is the contract, so a reply that carries the report body is a second copy that can
    disagree with it. Three things are checked: the first line is the pointer, the tasks line is
    present, and no report section heading came back with it.
    """
    lines = [line for line in artifact.splitlines() if line.strip()]
    if not lines:
        return ["the reply is empty; it must point at REPORT.md"]
    problems: list[str] = []
    if not re.match(r"^report: \S+REPORT(?:\.part-\d+-\d+)?\.md$", lines[0].strip()):
        problems.append(f"first line is not `report: <path>/REPORT.md`: {lines[0].strip()[:70]!r}")
    if len(lines) < 2 or not re.search(r"\*\*Tasks:\*\* \d+/\d+ passed", lines[1]):
        problems.append("the second line is not `**Tasks:** N/M passed`")
    restated = [heading for heading in ("## Implementation Report", "### Tasks", "### Decisions",
                                        "### Quality gates", "### Files Changed")
                if any(line.strip() == heading for line in lines)]
    if restated:
        problems.append(f"the reply pastes the report body back: {', '.join(restated)}")
    return problems


def layer_lines(artifact: str) -> list[str]:
    """Each typed layer that ran is reported with its verdict and command."""
    return [] if re.search(r"^\[(Unit|Integration|E2E|Validation)\] (PASS|FAIL) — .+$", artifact, re.M) \
        else ["no `[Layer] PASS|FAIL — command` line"]


def next_line(artifact: str) -> list[str]:
    return [] if re.search(r"^> Next: .+$", artifact, re.M) else ["no `> Next:` handoff line"]


CHECKS = {
    "headings": headings,
    "regex": regex_present,
    "absent": regex_absent,
    "typed_tests": typed_tests,
    "criteria_verifiable": criteria_verifiable,
    "tasks_verify": tasks_verify,
    "finding_contract": finding_contract,
    "spec_labels": spec_labels,
    "verdict_line": verdict_line,
    "fix_on_blocking": fix_on_blocking,
    "single_line": single_line,
    "conventional_commit": conventional_commit,
    "bullets_max": bullets_max,
    "closes_first": closes_first,
    "frontmatter_fields": frontmatter_fields,
    "memory_type": memory_type,
    "body_sections": body_sections,
    "router_rows": router_rows,
    "tasks_line": tasks_line,
    "report_pointer": report_pointer,
    "layer_lines": layer_lines,
    "next_line": next_line,
}


def evaluate(artifact: str, assertions: list[dict]) -> list[str]:
    """Every failure message from every assertion, prefixed with the check that produced it."""
    problems: list[str] = []
    for assertion in assertions:
        kind = assertion.get("kind", "")
        check = CHECKS.get(kind)
        if check is None:
            problems.append(f"unknown assertion kind: {kind}")
            continue
        arguments = {key: value for key, value in assertion.items() if key != "kind"}
        problems.extend(f"{kind}: {message}" for message in check(artifact, **arguments))
    return problems
