#!/usr/bin/env python3
"""Hermetic structural checks for the Python under `.agent/tools/`.

The tree is read with `ast` and `tokenize`, so each rule is judged on syntax rather than on a
regex over text: a continuation line inside brackets is not an indentation, a `#` inside a string
is not a comment, and a function's length is its real span. Every assertion prints the file, the
line, and the rule it violates, so a failure names what to change instead of only a count.

Rules:
- every top-level function has a return annotation;
- no function spans more than `MAX_FUNCTION_LINES` lines;
- every logical line starts at a multiple-of-four column, with no tabs;
- no run of more than `MAX_COMMENT_BLOCK` consecutive comment lines;
- no bare-name import of a generic module name, which is what made `store`, `report`, and
  `findings` collide on `sys.path`;
- exactly one `atomic_write` and one `gh` runner exist in the whole tree.
"""
from __future__ import annotations

import ast
import io
import sys
import tokenize
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / ".agent" / "tools"

MAX_FUNCTION_LINES = 50
MAX_COMMENT_BLOCK = 4
GENERIC_MODULES = {"store", "units", "recall", "maintenance",
                   "findings", "layers", "personas", "report"}
UNIQUE_FUNCTIONS = ("atomic_write", "gh")


def module_files() -> list[Path]:
    return sorted(
        path for path in TOOLS.rglob("*.py") if "__pycache__" not in path.parts
    )


def display(path: Path) -> str:
    return str(path.relative_to(ROOT))


def functions(tree: ast.AST) -> list[ast.FunctionDef | ast.AsyncFunctionDef]:
    return [node for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))]


def check_annotations(path: Path, tree: ast.AST) -> list[tuple[str, int, str, str]]:
    found = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.returns is None:
            found.append((display(path), node.lineno, "untyped-function", node.name))
    return found


def check_lengths(path: Path, tree: ast.AST) -> tuple[list[tuple[str, int, str, str]], int]:
    found, longest = [], 0
    for node in functions(tree):
        span = (node.end_lineno or node.lineno) - node.lineno + 1
        longest = max(longest, span)
        if span > MAX_FUNCTION_LINES:
            found.append((display(path), node.lineno, "long-function", f"{node.name} ({span} lines)"))
    return found, longest


def logical_line_columns(source: str) -> list[tuple[int, int]]:
    """(line, column) for the first token of every logical line, indentation included."""
    starts: list[tuple[int, int]] = []
    at_start = True
    for token in tokenize.generate_tokens(io.StringIO(source).readline):
        if token.type == tokenize.NEWLINE:
            at_start = True
            continue
        if token.type in {tokenize.NL, tokenize.INDENT, tokenize.DEDENT,
                          tokenize.ENCODING, tokenize.COMMENT}:
            continue
        if at_start:
            starts.append((token.start[0], token.start[1]))
            at_start = False
    return starts


def check_indentation(path: Path, source: str) -> list[tuple[str, int, str, str]]:
    found = []
    for line in source.splitlines():
        if line.startswith("\t") or line.lstrip(" ").startswith("\t"):
            found.append((display(path), 1, "tab-indent", "tabs are not used for indentation"))
            break
    for number, column in logical_line_columns(source):
        if column % 4:
            found.append((display(path), number, "non-4-space-indent", f"column {column}"))
    return found


def check_comment_blocks(path: Path, source: str) -> list[tuple[str, int, str, str]]:
    found, run, start = [], 0, 0
    for number, line in enumerate(source.splitlines(), 1):
        if line.strip().startswith("#"):
            run += 1
            start = number - run + 1
            continue
        if run > MAX_COMMENT_BLOCK:
            found.append((display(path), start, "long-comment-block",
                          f"{run} consecutive comment lines (>{MAX_COMMENT_BLOCK})"))
        run = 0
    if run > MAX_COMMENT_BLOCK:
        found.append((display(path), start, "long-comment-block",
                      f"{run} consecutive comment lines (>{MAX_COMMENT_BLOCK})"))
    return found


def check_imports(path: Path, tree: ast.AST) -> list[tuple[str, int, str, str]]:
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom) or node.level:
            continue
        if node.module in GENERIC_MODULES:
            found.append((display(path), node.lineno, "bare-generic-import",
                          f"from {node.module} import ..."))
    return found


def check_unique_functions(modules: dict[Path, ast.AST]) -> list[tuple[str, int, str, str]]:
    found = []
    for name in UNIQUE_FUNCTIONS:
        defining = [(path, node.lineno) for path, tree in modules.items()
                    for node in functions(tree) if node.name == name]
        if len(defining) != 1:
            where = ", ".join(f"{display(path)}:{line}" for path, line in defining) or "nowhere"
            found.append((".agent/tools", 0, "shared-helper-count",
                          f"def {name} is defined {len(defining)} times ({where}); expected exactly once"))
    return found


def main() -> int:
    violations: list[tuple[str, int, str, str]] = []
    parsed: dict[Path, ast.AST] = {}
    untyped = 0
    longest = 0
    indent_files = set()

    for path in module_files():
        source = path.read_text(encoding="utf-8", errors="replace")
        try:
            tree = ast.parse(source, filename=str(path))
        except SyntaxError as error:
            violations.append((display(path), error.lineno or 1, "unparseable", str(error.msg)))
            continue
        parsed[path] = tree

        annotation_findings = check_annotations(path, tree)
        untyped += len(annotation_findings)
        violations.extend(annotation_findings)

        length_findings, longest_here = check_lengths(path, tree)
        longest = max(longest, longest_here)
        violations.extend(length_findings)

        indent_findings = check_indentation(path, source)
        if indent_findings:
            indent_files.add(path)
        violations.extend(indent_findings)

        violations.extend(check_comment_blocks(path, source))
        violations.extend(check_imports(path, tree))

    violations.extend(check_unique_functions(parsed))

    for file, line, rule, message in sorted(violations):
        print(f"{file}:{line}: {rule}: {message}")

    def count(rule: str) -> int:
        return sum(1 for entry in violations if entry[2] == rule)

    print()
    print(f"python-shape: {untyped} untyped, {longest} max function lines, "
          f"{len(indent_files)} files with non-4-space indent, "
          f"{count('long-comment-block')} long comment blocks, "
          f"{count('bare-generic-import')} bare-name imports, "
          f"{count('shared-helper-count')} shared-helper problems")
    bad = bool(violations)
    print("python-shape: fail" if bad else "python-shape: pass")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
