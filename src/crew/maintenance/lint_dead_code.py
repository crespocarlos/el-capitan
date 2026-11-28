"""`crew-lint.py --dead-code`: catalog commands nothing references, so the next uncalled command is visible.

Callers are prompts, hooks, `install.sh`, other tools and the CI workflows. `TOOLS.md`, `README.md`,
`tools.json` and the tool tree's `.md` docs describe commands, so they are not callers, and neither is a
Python docstring or comment; tests are counted apart and never decide. `uncalled` is the only
automatic verdict; `test-only` is listed for a person to decide.
"""

from __future__ import annotations

import io
import json
import tokenize
from pathlib import Path

PROMPT_PATTERNS = (
    "rules/*.mdc",
    ".cursor/rules/*.mdc",
    ".cursor/agents/**/*.md",
    ".cursor/skills/**/*.md",
    ".agent/_*TEMPLATE.md",
    "AGENTS.md",
    "CLAUDE.md",
    ".claude/CLAUDE.md",
)
HOOK_PATTERNS = (".claude/hooks/**/*.sh",)
TOOL_PATTERNS = ("src/crew/**/*.py", "src/crew/**/*.sh", ".github/workflows/*.yml")
TEST_PATTERNS = ("evals/**/*.py",)
# The catalog page names every command, so it cannot be a caller; the README describes the surface
# to a person and never asks the pipeline to run one.
EXCLUDED = {"TOOLS.md", "README.md"}
VERDICTS = ("called", "test-only", "uncalled")
WIDTHS = {"name": 30, "verdict": 12, "other": 9}


def tool_names(root: Path) -> list[str]:
    """Every `kind: command` basename in the catalog, sorted."""
    try:
        data = json.loads((root / "src/crew/tools.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"cannot read the catalog: {error}") from error
    names = []
    for section in ("tools", "scripts"):
        for entry in data.get(section, []):
            if isinstance(entry, dict) and entry.get("kind") == "command":
                names.append(str(entry.get("name", "")))
    return sorted(name for name in names if name)


def sources(root: Path, patterns: tuple[str, ...]) -> list[Path]:
    """Every file under `root` matching one of `patterns`, minus the catalog page and the README."""
    found: set[Path] = set()
    for pattern in patterns:
        found.update(path for path in root.glob(pattern) if path.is_file())
    return sorted(path for path in found if path.name not in EXCLUDED)


def python_code(source: str) -> str:
    """The module's tokens without comments and docstrings (any string standing alone as a statement)."""
    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(source).readline))
    except (tokenize.TokenError, IndentationError, SyntaxError):
        return source
    skip = {tokenize.NL, tokenize.COMMENT}
    kept = []
    for index, token in enumerate(tokens):
        if token.type == tokenize.COMMENT:
            continue
        if token.type == tokenize.STRING:
            before = next((t for t in reversed(tokens[:index]) if t.type not in skip), None)
            after = next((t for t in tokens[index + 1 :] if t.type not in skip), None)
            starts = before is None or before.type in (tokenize.NEWLINE, tokenize.INDENT, tokenize.DEDENT, tokenize.ENCODING)
            if starts and after is not None and after.type in (tokenize.NEWLINE, tokenize.ENDMARKER):
                continue
        kept.append(token.string)
    return " ".join(kept)


def read(paths: list[Path]) -> list[tuple[Path, str]]:
    """Each file with the text that can call a command; an unreadable file is skipped, not counted."""
    texts = []
    for path in paths:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        texts.append((path, python_code(text) if path.suffix == ".py" else text))
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


def verdict(counts: dict[str, int]) -> str:
    """Called when any caller group names it; test-only when only a test does; else uncalled.

    A test keeps a command correct, not needed, so a command only a test exercises is not called.
    """
    if sum(counts[group] for group in ("prompts", "hooks", "install", "tools")):
        return "called"
    return "test-only" if counts["tests"] else "uncalled"


def command_row(name: str, corpus: dict) -> dict:
    """One command's counts per caller group, its own file excluded, and the verdict they support."""
    own = {path for group in ("tools", "tests") for path, _ in corpus[group] if path.name == name}
    counts = {group: sum(1 for path, text in texts if path not in own and name in text) for group, texts in corpus.items()}
    return {"name": name, **counts, "verdict": verdict(counts)}


def dead_code_rows(root: Path) -> list[dict]:
    """One row per catalog command; raises ValueError when the catalog is unreadable."""
    names = tool_names(root)
    corpus = caller_texts(root)
    return [command_row(name, corpus) for name in names]


def dead_code_table(results: list[dict]) -> list[str]:
    """The table, then the counts that make the verdict auditable."""
    columns = ("name", "verdict", "prompts", "hooks", "install", "tools", "tests")
    lines = ["".join(name.upper().ljust(WIDTHS.get(name, WIDTHS["other"])) for name in columns)]
    lines += ["".join(str(row[name]).ljust(WIDTHS.get(name, WIDTHS["other"])) for name in columns) for row in results]
    uncalled = [row["name"] for row in results if row["verdict"] == "uncalled"]
    test_only = [row["name"] for row in results if row["verdict"] == "test-only"]
    lines += [
        "",
        f"{len(results)} commands: {len(results) - len(uncalled) - len(test_only)} called, {len(test_only)} named only by a test, {len(uncalled)} uncalled",
    ]
    if test_only:
        lines.append(f"test-only (a person decides): {', '.join(test_only)}")
    if uncalled:
        lines.append(f"uncalled (no reference at all): {', '.join(uncalled)}")
    return lines
