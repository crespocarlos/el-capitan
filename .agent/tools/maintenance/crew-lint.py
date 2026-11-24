#!/usr/bin/env python3
"""Validate cross-file el-capitan conventions.

Usage: crew-lint.py [--root DIR] [--budget]

Four families run in a fixed order, each in its own module so a rule change stays local:
`lint_catalog` (the manifest, `kind`, naming, and module resolution), `lint_prompts` (rules, skills,
and tool grants), `lint_references` (paths, installed names, routing, and swallowed calls),
`lint_progress` (PROGRESS transitions, edit discipline, and hook registration), and `lint_budget`
(always-on accounting, with `--budget`). This file only parses arguments and maps findings to an
exit code.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Installed flat into ~/.agent/bin, but in the repo this file is `.agent/tools/maintenance`; the
# family modules are its siblings there. `resolve()` follows the installed symlink back into the
# repo, so one directory covers both, and the `lint_*` names keep them from colliding on `sys.path`.
_MAINTENANCE_DIR = Path(__file__).resolve().parent
if str(_MAINTENANCE_DIR) not in sys.path:
    sys.path.insert(0, str(_MAINTENANCE_DIR))

from lint_budget import (  # noqa: E402
    MAX_ALWAYS_RULE_TOKENS,
    always_on_files,
    lint_budget,
)
from lint_catalog import lint_tool_catalog  # noqa: E402
from lint_files import files  # noqa: E402
from lint_naming import installed_tool_names  # noqa: E402
from lint_progress import (  # noqa: E402
    lint_edit_discipline,
    lint_hook_registration,
    lint_local_state_tracked,
    lint_progress_transitions,
)
from lint_prompts import (  # noqa: E402
    lint_agent_readonly,
    lint_rule_setup,
    lint_skill_setup,
    lint_tool_surface,
)
from lint_references import lint_documents, lint_repo_paths  # noqa: E402

Finding = tuple[str, int, str, str]
# The two documentation roots a stale path is most likely to hide in, checked alongside the prompts.
DOC_ROOTS = ("README.md", "AGENTS.md")


def rule_names(root: Path) -> set[str]:
    """The `.mdc` filenames that count as rules, preferring `rules/` when it exists."""
    rule_dir = root / "rules"
    if rule_dir.is_dir():
        return {path.name for path in rule_dir.glob("*.mdc")}
    return {path.name for path in (root / ".cursor/rules").glob("*.mdc")}


def router_path(root: Path) -> Path:
    """The routing table this repo reads, under either rules layout."""
    router = root / "rules/crew-router.mdc"
    return router if router.exists() else root / ".cursor/rules/crew-router.mdc"


def budget_report(root: Path) -> None:
    """Print the always-on measurement to stderr, so stdout stays one finding per line."""
    sizes = always_on_files(root)
    print(f"always-on: {sum(size // 4 for _, size in sizes)} tokens "
          f"(ceiling {MAX_ALWAYS_RULE_TOKENS})", file=sys.stderr)
    for name, size in sizes:
        print(f"  {size:>7} bytes  {size // 4:>6} tokens  {name}", file=sys.stderr)


def lint(root: Path, budget: bool) -> list[Finding]:
    """Every check over one repository root; findings are `(path, line, rule, message)` tuples."""
    findings: list[Finding] = []
    findings.extend(lint_tool_catalog(root))
    findings.extend(lint_rule_setup(root))
    findings.extend(lint_skill_setup(root))
    findings.extend(lint_agent_readonly(root))
    all_files = files(root)
    installed_names = installed_tool_names(root)
    findings.extend(lint_tool_surface(root, all_files))
    findings.extend(lint_progress_transitions(root, all_files))
    findings.extend(lint_edit_discipline(root, all_files))
    docs = [root / name for name in DOC_ROOTS if (root / name).is_file()]
    findings.extend(lint_repo_paths(root, all_files + docs))
    rules = rule_names(root)
    findings.extend(lint_documents(root, all_files, installed_names, rules, router_path(root)))
    findings.extend(lint_hook_registration(root))
    findings.extend(lint_local_state_tracked(root))
    if budget:
        findings.extend(lint_budget(root, all_files, rules))
    return findings


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate repository conventions; --budget adds the size gates.")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[3])
    parser.add_argument("--budget", action="store_true", help="also check the always-on and prompt ceilings")
    parser.add_argument("--json", action="store_true",
                        help="print findings as a JSON array on stdout; the measurement goes to stderr")
    args = parser.parse_args()
    if not args.root.is_dir():
        print(f"error: root does not exist: {args.root}", file=sys.stderr)
        return 2
    root = args.root.resolve()
    if args.budget:
        budget_report(root)
    findings = lint(root, args.budget)
    if args.json:
        print(json.dumps([{"path": path, "line": line, "rule": rule, "message": message}
                          for path, line, rule, message in findings], indent=2))
    else:
        for path, line, rule, message in findings:
            print(f"{path}:{line}: {rule}: {message}")
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
