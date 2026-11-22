#!/usr/bin/env python3
"""Always-on accounting: which rules every request pays for, and the size ceilings on prompts.

The estimate is the larger of the two harnesses' payloads, not Cursor's `alwaysApply` set alone:
Claude Code ignores `alwaysApply` and `globs`, loading CLAUDE.md plus every `@` import whatever its
glob says, so an imported glob rule costs that harness every turn. `AGENTS.md` and
`.claude/CLAUDE.md` are always loaded too, so a budget that omits them cannot constrain.

The same module owns the per-file ceiling, so `--budget` and the gate measure one set of files the
same way: an agent or skill file is loaded whole on every dispatch, and an oversized one is a
per-call tax rather than a one-time read.
"""
from __future__ import annotations

import re
from pathlib import Path

from lint_files import rel

# Measured 2026-11-21 at 7,204 tokens after the trim; 9,100 leaves room for prompt-engineering.mdc,
# which is imported because Claude Code ignores globs and prompt work is frequent here. The 2026-11-22
# addition of the `crew inbox` routing row measured 9,112, so the ceiling carries that command too.
# Raise it only with a new measurement; when the set grows with no new rule to justify it, trim.
MAX_ALWAYS_RULE_TOKENS = 9150
# An agent or skill file is read whole, so its ceiling is bytes rather than a token estimate: the
# dispatch cost of a 12 KB prompt is already large, and prose above it belongs in a references file.
MAX_PROMPT_FILE_BYTES = 12_000
MAX_PROMPT_FILE_LINES = 500
ALWAYS_LOADED_PROJECT_FILES = ("AGENTS.md", ".claude/CLAUDE.md")
PROMPT_ROOTS = (".cursor/agents", ".cursor/skills")
Findings = list[tuple[str, int, str, str]]


def claude_imports(root: Path) -> set[str]:
    """Rule filenames `@`-imported by a repository CLAUDE.md.

    Only the repository's own files are read: `$HOME/.claude/CLAUDE.md` is generated from
    `.claude/CLAUDE.md` by `install.sh`, so including it would let a stale machine-level copy mask a
    missing repository import and would make the token count differ per machine.
    """
    names: set[str] = set()
    for candidate in (root / "CLAUDE.md", root / ".claude/CLAUDE.md"):
        if not candidate.is_file():
            continue
        for target in re.findall(r"@(\S+\.mdc)", candidate.read_text(errors="replace")):
            names.add(Path(target).name)
    return names


def always_on_unreachable(root: Path, rule: str) -> str:
    """Why an `alwaysApply: true` rule never reaches Claude Code, or "" when it does.

    Cursor honours `alwaysApply`; Claude Code does not know the field and loads only `CLAUDE.md`
    plus its `@` imports. A rule marked always-on but not imported therefore applies in one harness
    and silently vanishes in the other, which is a behavior difference no other check can see.
    """
    if rule in claude_imports(root):
        return ""
    return (f"alwaysApply is true but CLAUDE.md never imports it, so Claude Code does not load it; "
            f"add `@~/.cursor/rules/{rule}` to {rel(root, root / '.claude/CLAUDE.md')}")


def always_on_files(root: Path) -> list[tuple[str, int]]:
    """Every file a request pays for, with its size in bytes, largest first."""
    rule_dir = root / "rules"
    cursor_payload = {rule.name for rule in rule_dir.glob("*.mdc")
                      if re.search(r"alwaysApply:\s*true", rule.read_text(errors="replace"))}
    sizes: list[tuple[str, int]] = []
    for name in cursor_payload | claude_imports(root):
        path = rule_dir / name
        if path.is_file():
            sizes.append((f"rules/{name}", len(path.read_text(errors="replace"))))
    for name in ALWAYS_LOADED_PROJECT_FILES:
        path = root / name
        if path.is_file():
            sizes.append((name, len(path.read_text(errors="replace"))))
    return sorted(sizes, key=lambda entry: -entry[1])


def always_on_tokens(root: Path) -> int:
    """The estimate `--budget` prints and the ceiling enforces, from one measurement."""
    return sum(size // 4 for _, size in always_on_files(root))


def prompt_files(root: Path) -> list[Path]:
    """Every agent and skill Markdown file, references included."""
    found: list[Path] = []
    for pattern in PROMPT_ROOTS:
        found.extend(path for path in (root / pattern).rglob("*.md") if path.is_file())
    return sorted(found)


def lint_budget(root: Path, all_files: list[Path], rules: set[str]) -> Findings:
    """The always-on token estimate, the per-file size caps, and the duplicate-rule layout."""
    findings: Findings = []
    sizes = always_on_files(root)
    always = sum(size // 4 for _, size in sizes)
    if always > MAX_ALWAYS_RULE_TOKENS:
        largest, size = sizes[0]
        findings.append((largest, 1, "budget",
                         f"always-on set estimates {always} tokens (>{MAX_ALWAYS_RULE_TOKENS}); "
                         f"largest contributor {largest} ({size} bytes)"))
    for path in all_files:
        name = rel(root, path)
        lines = path.read_text(errors="replace").count("\n") + 1
        if ("/agents/" in name or "/skills/" in name) and lines > MAX_PROMPT_FILE_LINES:
            findings.append((name, 1, "budget", f"{lines} lines (>{MAX_PROMPT_FILE_LINES})"))
    for path in prompt_files(root):
        size = path.stat().st_size
        if size > MAX_PROMPT_FILE_BYTES:
            findings.append((rel(root, path), 1, "prompt-budget",
                             f"{size} bytes (>{MAX_PROMPT_FILE_BYTES}); move reference material "
                             f"into a references/ file read on demand"))
    for rule in rules:
        if (root / "rules" / rule).exists() and (root / ".cursor/rules" / rule).exists():
            findings.append((f"rules/{rule}", 1, "budget",
                             "rule exists under rules and .cursor/rules"))
    return findings
