"""The repo-specific writing standard for prompt files: rules, agents, skills, references, guides.

Vale (`.vale.ini`) owns the generic prose rules. Here, with frontmatter and fenced code masked: history
narration, a 12-word passage shared by two files, the one glossary, Elastic-only identifiers outside
an opt-in section, an undefined `$PLACEHOLDER`, and a journal write or draft import instructed
anywhere but the closing confirmation, the resolver and the memory commands' own files.
"""

from __future__ import annotations

import collections
import re
from pathlib import Path

from crew.lib.markdown import FRONTMATTER
from crew.scripts.maintenance.lint_files import line_no, rel
from crew.scripts.maintenance.lint_writing import narration

Findings = list[tuple[str, int, str, str]]
PROMPT_GLOBS = ("rules/*.mdc", ".cursor/agents/**/*.md", ".cursor/skills/**/*.md", ".claude/CLAUDE.md", "AGENTS.md", "src/crew/AGENTS.md")
PASSAGE_WORDS = 12
TEMPLATES = ".cursor/skills/spec-writing/references/"
# File pairs that share passages by design, each with its reason.
SHARED_BY_DESIGN = {frozenset({TEMPLATES + "spec-template.md", TEMPLATES + "bug-spec-template.md"}): "the templates share sections"}
# The lookups pointer is one line every working agent carries by design: it is the link, not a copy.
# Only the fixed sentence is skipped, so text after it on the same line is still scanned.
POINTER_LINE = re.compile(
    r"(?m)^Lookups: follow `[^`]*lookups\.md` before you search for code whose file you do not "
    r"already know, or rely on a product or API fact\."
)
GLOSSARY_FILE = "src/crew/AGENTS.md"
GLOSSARY_TERMS = ("persona", "worker", "gate", "verification")
VENDOR = re.compile(
    r"(?i)\bkibana\b|\belasticsearch\b|\bES\|QL\b|\besql\b|@kbn/|mcp__elastic|\belastic-docs\b"
    r"|\b(?:localhost|127\.0\.0\.1|0\.0\.0\.0):5601\b|\bport 5601\b"
)
OPT_IN_HEADING = re.compile(r"(?i)^#+ (?=.*(?:kibana|elastic)).*\(opt-in")
# Prompts that target Kibana by design, and the owner's personal rules.
VENDOR_SCOPED = (".cursor/skills/crew-e2e/", ".cursor/skills/crew-evals/", "rules/personal.mdc", "rules/voice.mdc")
PLACEHOLDER = re.compile(r"\$\{?([A-Z][A-Z0-9_]+)")
ENVIRONMENT = {"HOME", "PATH", "PWD", "EDITOR", "CREW_TASK_DIR", "CREW_WORKER_TASK", "CREW_MEMORY_DIR", "CREW_JOURNAL_DIR"}
MEMORY_WRITE = re.compile(r"\bjournal\s+add\b|\bimport-inbox\b")
CLOSING_OWNER = ".cursor/skills/crew-open-pr/references/closing-confirmation.md"
# Where a journal write or a draft import may be instructed: the build workflow's closing confirmation,
# the respond workflow's resolver, and the memory commands the user invokes (their skills, the rule,
# the exit-code table, the session-start inbox listing).
MEMORY_WRITERS = (
    CLOSING_OWNER,
    ".cursor/agents/crew-pr-resolver/references/acting-on-threads.md",
    ".cursor/skills/crew-log/",
    ".cursor/skills/crew-memory/",
    "rules/memory-capture.mdc",
    "src/crew/AGENTS.md",
    ".claude/hooks/spec-status-reconcile.sh",
)

FENCE = re.compile(r"[ \t]*(`{3,}|~{3,})(.*)")
CODE_SPAN = re.compile(r"(?<!`)(`+)(?!`)[^\n]*?(?<!`)\1(?!`)")


def prompt_files(root: Path) -> list[Path]:
    found = {path for pattern in PROMPT_GLOBS for path in root.glob(pattern) if path.is_file()}
    return sorted(path for path in found if "fixtures" not in path.parts)


def blank(match: re.Match) -> str:
    return re.sub(r"[^\n]", " ", match.group(0))


def fenced(text: str) -> str:
    """Fenced code blocks as spaces, by CommonMark's rule: a closer repeats the opener's character at
    least as many times with nothing after it, and a backtick opener's info string holds no backtick."""
    lines, fence = text.splitlines(keepends=True), ""
    for index, line in enumerate(lines):
        run = FENCE.match(line)
        if fence:
            if run and run.group(1)[0] == fence[0] and len(run.group(1)) >= len(fence) and not run.group(2).strip():
                fence = ""
        elif run and not (run.group(1)[0] == "`" and "`" in run.group(2)):
            fence = run.group(1)
        else:
            continue
        lines[index] = re.sub(r"[^\n]", " ", line)
    return "".join(lines)


def mask(text: str, inline: bool = True) -> str:
    """Frontmatter and fenced code (and code spans when `inline`) as spaces; offsets and lines stay put."""
    text = fenced(FRONTMATTER.sub(blank, text))
    return CODE_SPAN.sub(blank, text) if inline else text


def lint_style(root: Path) -> Findings:
    """Every repo-specific writing rule over every prompt file."""
    found: Findings = []
    texts = {rel(root, path): path.read_text(encoding="utf-8", errors="replace") for path in prompt_files(root)}
    for name, text in texts.items():
        found += narration(name, mask(text)) + vendor_terms(name, text)
        found += placeholders(name, text) + memory_writes(name, text)
    for hook in sorted((root / ".claude/hooks").glob("*.sh")):
        found += memory_writes(rel(root, hook), hook.read_text(encoding="utf-8", errors="replace"))
    return found + duplicate_passages(texts) + glossary_defined(root, texts)


def glossary_defined(root: Path, texts: dict[str, str]) -> Findings:
    """One glossary, in `GLOSSARY_FILE`, defining each of `GLOSSARY_TERMS`."""
    found = [
        (name, line_no(text, m.start()), "glossary-terms", f"a second glossary; it lives in {GLOSSARY_FILE}")
        for name, text in texts.items()
        if name != GLOSSARY_FILE
        for m in re.finditer(r"(?im)^#+ glossary\b", text)
    ]
    if (root / GLOSSARY_FILE).is_file():
        section = re.search(r"(?ims)^## Glossary\b(.*?)(?=^## |\Z)", texts.get(GLOSSARY_FILE, ""))
        body = section.group(1) if section else ""
        found += [
            (GLOSSARY_FILE, 1, "glossary-terms", f"the glossary does not define `{term}`")
            for term in GLOSSARY_TERMS
            if not re.search(rf"(?im)^\|\s*{term}\s*\|", body)
        ]
    return found


def vendor_terms(name: str, text: str) -> Findings:
    """An Elastic-only identifier outside the Kibana-scoped prompts sits under an `(opt-in)` heading."""
    if name.startswith(VENDOR_SCOPED):
        return []
    text = FRONTMATTER.sub(blank, text)  # a frontmatter tool list is agents-inherit-tools's
    found, opted, level, offset = [], False, 0, 0
    for line in mask(text, inline=False).splitlines(keepends=True):
        heading = re.match(r"(#+) ", line)
        if heading and (not opted or len(heading.group(1)) <= level):
            opted, level = bool(OPT_IN_HEADING.match(line)), len(heading.group(1))
        if not opted:
            found += [
                (
                    name,
                    line_no(text, offset + m.start()),
                    "vendor-tools-scoped",
                    f"`{m.group(0)}` is Elastic-specific; move it under an `(opt-in)` Kibana or Elastic heading",
                )
                for m in VENDOR.finditer(text[offset : offset + len(line)])
            ]
        offset += len(line)
    return found


def placeholders(name: str, text: str) -> Findings:
    """A `$NAME` in an agent or skill is assigned, read, sourced or named in backticks before first use."""
    if not name.startswith((".cursor/agents/", ".cursor/skills/")):
        return []
    found, seen = [], set()
    for match in PLACEHOLDER.finditer(text):
        word = match.group(1)
        if word in seen or word in ENVIRONMENT:
            continue
        seen.add(word)
        before = text[: match.start()]
        named_here = before.endswith("`") and re.match(r"\}?`", text[match.end() :])  # an inputs line: `$X` or `${X}`
        if named_here or re.search(rf"(?<![\w$]){word}=|\bread\b[^\n]*\b{word}\b|\bfor {word} in|`\$?{word}`", before):
            continue
        found.append(
            (
                name,
                line_no(text, match.start()),
                "undefined-placeholder",
                f"`${word}` is used before the file defines it; name it in an inputs line or assign it",
            )
        )
    return found


def memory_writes(name: str, text: str) -> Findings:
    """A journal write or a draft import is instructed only where the user's answer is asked for."""
    if name.startswith(MEMORY_WRITERS):
        return []
    return [
        (
            name,
            line_no(text, m.start()),
            "one-closing-confirmation",
            f"`{m.group(0)}` writes memory; only {CLOSING_OWNER} (build) or the resolver (respond) asks and writes",
        )
        for m in MEMORY_WRITE.finditer(text)
    ]


def duplicate_passages(texts: dict[str, str]) -> Findings:
    """No run of `PASSAGE_WORDS` words in two prompt files outside `SHARED_BY_DESIGN`; one finding per pair."""
    owners: dict[str, list[tuple[str, int]]] = collections.defaultdict(list)
    for name, text in texts.items():
        prose = POINTER_LINE.sub(blank, mask(text, inline=False))
        words = [(m.group(0).lower(), m.start()) for m in re.finditer(r"[A-Za-z0-9][A-Za-z0-9_'-]*", prose)]
        for index in range(len(words) - PASSAGE_WORDS + 1):
            owners[" ".join(word for word, _ in words[index : index + PASSAGE_WORDS])].append((name, words[index][1]))
    reported: set[frozenset] = set()
    found: Findings = []
    for passage, places in owners.items():
        names = sorted({name for name, _ in places})
        for first, second in ((a, b) for i, a in enumerate(names) for b in names[i + 1 :]):
            pair = frozenset({first, second})
            if pair in reported or pair in SHARED_BY_DESIGN:
                continue
            reported.add(pair)
            offset = next(at for name, at in places if name == first)
            found.append((first, line_no(texts[first], offset), "duplicate-passages", f'shares "{passage}" with {second}; keep it in one file and link it'))
    return found
