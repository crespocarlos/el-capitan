"""The caller set for a catalog command: which files reference it, and where.

A command earns its place by being invoked. The four groups that can invoke one are prompts (rules,
agents, skills, and the always-loaded guidance), hooks, `install.sh`, and other tools; a reference in
any of them is a caller. Documentation is deliberately not a caller: `TOOLS.md` and `tools.json` name
every command by construction, so counting them would make the report answer "all called" forever.
Tests are not callers either — a test proves a command runs, not that the pipeline asks for it — so
they are reported in their own column and never decide the verdict.
"""
from __future__ import annotations

import json
from pathlib import Path

PROMPT_PATTERNS = (
    "rules/*.mdc",
    ".cursor/rules/*.mdc",
    ".cursor/agents/**/*.md",
    ".cursor/skills/**/*.md",
    ".agent/tools/AGENTS.md",
    ".agent/_*TEMPLATE.md",
    "AGENTS.md",
    "CLAUDE.md",
    ".claude/CLAUDE.md",
)
HOOK_PATTERNS = (".claude/hooks/**/*.sh",)
TOOL_PATTERNS = (".agent/tools/**/*.py", ".agent/tools/**/*.sh")
TEST_PATTERNS = ("evals/**/*.py",)
GROUPS = ("prompts", "hooks", "install", "tools", "tests")
# The catalog page names every command, so it is the one document that cannot be a caller. `README.md`
# is not a caller either: it describes the surface to a human and never asks the pipeline to run one.
EXCLUDED = {"TOOLS.md", "README.md"}
VERDICTS = ("called", "test-only", "uncalled")


def tool_names(root: Path) -> list[str]:
    """Every `kind: command` basename in the catalog, sorted."""
    try:
        data = json.loads((root / ".agent/tools/tools.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"cannot read the catalog: {error}") from error
    names = []
    for section in ("tools", "scripts"):
        for entry in data.get(section, []):
            if isinstance(entry, dict) and entry.get("kind") == "command":
                names.append(str(entry.get("name", "")))
    return sorted(name for name in names if name)


def sources(root: Path, patterns: tuple[str, ...], exclude: Path | None = None) -> list[Path]:
    """Every file under `root` matching one of `patterns`, minus the catalog page and `exclude`."""
    found: set[Path] = set()
    for pattern in patterns:
        found.update(path for path in root.glob(pattern) if path.is_file())
    return sorted(path for path in found
                  if path.name not in EXCLUDED and (exclude is None or path != exclude))


def read(paths: list[Path]) -> list[tuple[Path, str]]:
    """Each file with its text; an unreadable file is skipped rather than counted as a caller."""
    texts = []
    for path in paths:
        try:
            texts.append((path, path.read_text(encoding="utf-8", errors="replace")))
        except OSError:
            continue
    return texts


def caller_texts(root: Path) -> dict[str, list[tuple[Path, str]]]:
    """Each caller group read once, since every command is counted against the same corpus."""
    install = [path for path in (root / "install.sh",) if path.is_file()]
    return {
        "prompts": read(sources(root, PROMPT_PATTERNS)),
        "hooks": read(sources(root, HOOK_PATTERNS)),
        "install": read(install),
        "tools": read(sources(root, TOOL_PATTERNS)),
        "tests": read(sources(root, TEST_PATTERNS)),
    }


def count(name: str, texts: list[tuple[Path, str]], exclude: Path | None = None) -> int:
    """How many files reference `name`, ignoring the file that defines it."""
    return sum(1 for path, text in texts if path != exclude and name in text)


def telemetry(name: str, texts: list[tuple[Path, str]]) -> int:
    """How many task journals name the command, reported as a hint rather than a verdict."""
    return count(name, texts)


def verdict(counts: dict[str, int]) -> str:
    """Called when any caller group names it; test-only when only a test does; else uncalled.

    A command the pipeline never invokes and only a test exercises is reported separately rather
    than called: a test keeps a command correct, not needed.
    """
    if sum(counts[group] for group in ("prompts", "hooks", "install", "tools")):
        return "called"
    return "test-only" if counts["tests"] else "uncalled"


def journal_texts(tasks_dir: Path | None) -> list[tuple[Path, str]]:
    if tasks_dir is None or not tasks_dir.is_dir():
        return []
    return read(sorted(tasks_dir.glob("*/PROGRESS.md")))
