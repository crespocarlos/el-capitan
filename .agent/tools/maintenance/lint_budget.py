#!/usr/bin/env python3
"""Always-on accounting: which rules every request pays for, and the token ceiling on that set.

The estimate is the larger of the two harnesses' payloads, not Cursor's `alwaysApply` set alone:
Claude Code ignores `alwaysApply` and `globs`, loading CLAUDE.md plus every `@` import whatever its
glob says, so an imported glob rule costs that harness every turn. `AGENTS.md` and
`.claude/CLAUDE.md` are always loaded too, so a budget that omits them cannot constrain.
"""
from __future__ import annotations

import re
from pathlib import Path

from lint_files import rel

# The ceiling was measured 2026-11-18 at 13,874 tokens; raise it only with a new measurement, and
# when the set grows with no new rule to justify it, trim the set instead.
MAX_ALWAYS_RULE_TOKENS = 14500
ALWAYS_LOADED_PROJECT_FILES = ("AGENTS.md", ".claude/CLAUDE.md")
# A harness loads an agent/skill file whole on every dispatch, so an oversized one is a per-call tax.
MAX_PROMPT_FILE_LINES = 500
Findings = list[tuple[str, int, str, str]]


def claude_imports(root: Path) -> set[str]:
    """Rule filenames `@`-imported by a CLAUDE.md this harness can see."""
    names: set[str] = set()
    for candidate in (root / "CLAUDE.md", root / ".claude/CLAUDE.md",
                      Path.home() / ".claude/CLAUDE.md"):
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


def lint_budget(root: Path, all_files: list[Path], rules: set[str]) -> Findings:
    """The always-on token estimate, the per-file size caps, and the duplicate-rule layout."""
    findings: Findings = []
    rule_dir = root / "rules"
    always = 0
    cursor_payload = set()
    for rule in rule_dir.glob("*.mdc"):
        if re.search(r"alwaysApply:\s*true", rule.read_text(errors="replace")):
            cursor_payload.add(rule.name)
    for name in sorted(cursor_payload | claude_imports(root)):
        path = rule_dir / name
        if path.is_file():
            always += len(path.read_text(errors="replace")) // 4
    for name in ALWAYS_LOADED_PROJECT_FILES:
        path = root / name
        if path.is_file():
            always += len(path.read_text(errors="replace")) // 4
    if always > MAX_ALWAYS_RULE_TOKENS:
        findings.append(("rules", 1, "budget",
                         f"always-on rules estimate {always} tokens (>{MAX_ALWAYS_RULE_TOKENS})"))
    for path in all_files:
        lines = path.read_text(errors="replace").count("\n") + 1
        if ("/agents/" in rel(root, path) or "/skills/" in rel(root, path)) and lines > MAX_PROMPT_FILE_LINES:
            findings.append((rel(root, path), 1, "budget",
                             f"{lines} lines (>{MAX_PROMPT_FILE_LINES})"))
    for rule in rules:
        if (root / "rules" / rule).exists() and (root / ".cursor/rules" / rule).exists():
            findings.append((f"rules/{rule}", 1, "budget",
                             "rule exists under rules and .cursor/rules"))
    return findings
