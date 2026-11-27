#!/usr/bin/env python3
"""Validate cross-file el-capitan conventions.

Usage: crew-lint.py [--root DIR] [--budget] [--json] [--list-rules | --commands | --write-readme | --dead-code]

Each family lives in its own `lint_*` module and every rule is registered in `lint_files.RULES`
(`--list-rules` prints it). This file only parses arguments and maps findings to an exit code.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import maintenance_bootstrap  # noqa: F401

from lint_catalog import installed_tool_names, lint_tool_catalog
from lint_dead_code import dead_code_rows, dead_code_table
from lint_docs import help_text, lint_readme, lint_release_files, write_readme
from lint_files import files, rule_table
from lint_prompts import (
    MAX_ALWAYS_RULE_TOKENS,
    always_on_files,
    lint_agent_readonly,
    lint_budget,
    lint_rule_setup,
    lint_skill_setup,
    lint_tool_surface,
)
from lint_python import lint_python
from lint_references import lint_documents, lint_handoff, lint_repo_paths
from lint_style import lint_style
from lint_writing import (
    lint_edit_discipline,
    lint_hook_registration,
    lint_local_state_tracked,
    lint_progress_transitions,
    lint_removed_forms,
    lint_tool_prose,
)

Finding = tuple[str, int, str, str]
# The documentation a stale path is most likely to hide in, checked alongside the prompts.
DOC_ROOTS = ("README.md", "AGENTS.md", "CONTRIBUTING.md", "SECURITY.md", "docs/*.md")


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
    docs = sorted(path for pattern in DOC_ROOTS for path in root.glob(pattern) if path.is_file())
    findings.extend(lint_repo_paths(root, all_files + docs))
    rules = rule_names(root)
    findings.extend(lint_documents(root, all_files, installed_names, rules, router_path(root)))
    findings.extend(lint_handoff(root, router_path(root)))
    findings.extend(lint_hook_registration(root))
    findings.extend(lint_local_state_tracked(root))
    findings.extend(lint_python(root))
    findings.extend(lint_removed_forms(root))
    findings.extend(lint_tool_prose(root))
    findings.extend(lint_style(root))
    findings.extend(lint_readme(root))
    findings.extend(lint_release_files(root))
    if budget:
        findings.extend(lint_budget(root, all_files, rules))
    return findings


def dead_code(root: Path, as_json: bool) -> int:
    """The caller report: exit 1 when a command is uncalled, 2 when the catalog is unreadable."""
    try:
        results = dead_code_rows(root)
    except ValueError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    print(json.dumps(results, indent=2) if as_json else "\n".join(dead_code_table(results)))
    return 1 if any(row["verdict"] == "uncalled" for row in results) else 0


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate repository conventions; --budget adds the size gates.")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[3])
    parser.add_argument("--budget", action="store_true", help="also check the always-on and prompt ceilings")
    parser.add_argument("--json", action="store_true",
                        help="print findings (or --dead-code rows) as JSON on stdout; the measurement goes to stderr")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--list-rules", action="store_true", help="print every registered rule and exit")
    mode.add_argument("--commands", action="store_true",
                      help="print the crew command table (`crew help`), generated from the router and tools.json")
    mode.add_argument("--write-readme", action="store_true",
                      help="rewrite the README's generated blocks: the command table and the counts")
    mode.add_argument("--dead-code", action="store_true",
                      help="report catalog commands no prompt, hook, installer or tool calls; exit 1 on one uncalled")
    return parser


def main() -> int:
    args = make_parser().parse_args()
    if args.list_rules:
        print("\n".join(rule_table()))
        return 0
    if not args.root.is_dir():
        print(f"error: root does not exist: {args.root}", file=sys.stderr)
        return 2
    root = args.root.resolve()
    if args.commands:
        print(help_text(root))
        return 0
    if args.write_readme:
        missing = write_readme(root)
        for name in missing:
            print(f"error: README.md has no generated:{name} block", file=sys.stderr)
        return 1 if missing else 0
    if args.dead_code:
        return dead_code(root, args.json)
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
