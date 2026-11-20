#!/usr/bin/env python3
"""Basename naming: the `crew-` command rule, module declarations, and the installed surface.

A command is what `~/.agent/bin` links, so its name is a public interface and follows one shape.
An imported module is snake_case, declared under `modules`, and never executable-and-linked. Three
checks live here because they are one decision seen from three angles: the catalog's command rule,
the catalog's module rule, and the tree-wide rule that catches a file nobody catalogued yet.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from lint_files import rel

MANIFEST = ".agent/tools/tools.json"
# The naming standard in TOOLS.md. A hyphen cannot appear in a Python import, so the two shapes are
# disjoint by construction rather than by convention an author has to remember.
COMMAND_NAME = re.compile(r"^crew-[a-z0-9-]+\.(py|sh)$")
MODULE_NAME = re.compile(r"^[a-z0-9_]+\.py$")
CATALOG_SECTIONS = (("tools", "command"), ("scripts", "command"),
                    ("modules", "module"), ("assets", "asset"))
# Sourced, never executed. `source` needs a real file at a fixed path, so this one command keeps a
# name the `crew-` rule would otherwise reject.
SOURCE_ONLY_COMMANDS = {"task-env.sh"}
Findings = list[tuple[str, int, str, str]]


def tool_tree_files(root: Path) -> list[Path]:
    """Every file in the tool tree, so a name is checked wherever it is filed."""
    directory = root / ".agent/tools"
    if not directory.is_dir():
        return []
    return sorted(path for path in directory.rglob("*")
                  if path.is_file() and "__pycache__" not in path.parts)


def installed_tool_names(root: Path) -> set[str]:
    """Basenames the installer links into `~/.agent/bin`: every `kind: command` catalog entry.

    Read from the manifest rather than the tree, because that is what `install.sh` links. A module
    is deliberately absent: it is imported, never installed, so a `~/.agent/bin/<module>` reference
    is a broken invocation and reports as one.
    """
    try:
        data = json.loads((root / MANIFEST).read_text())
    except (OSError, json.JSONDecodeError):
        return set()
    return {entry.get("name") for section, _ in CATALOG_SECTIONS
            for entry in data.get(section, [])
            if isinstance(entry, dict) and entry.get("kind") == "command"
            and isinstance(entry.get("name"), str)}


def installable_naming(data: dict) -> Findings:
    """Every command basename matches `^crew-[a-z0-9-]+\\.(py|sh)$`.

    One explicit exemption: `task-env.sh` is sourced — `source` needs a real file at a fixed path,
    so it cannot be renamed at all.
    """
    findings: Findings = []
    for section, _ in CATALOG_SECTIONS:
        for entry in data.get(section, []):
            if not isinstance(entry, dict) or entry.get("kind") != "command":
                continue
            name = entry.get("name")
            if name in SOURCE_ONLY_COMMANDS:
                continue
            if not COMMAND_NAME.match(str(name)):
                findings.append((MANIFEST, 1, "command-name",
                                 f"{name}: a command matches ^crew-[a-z0-9-]+\\.(py|sh)$"))
    return findings


def lint_tool_modules(root: Path, modules: list, listed: set[str]) -> Findings:
    """A declared importable module exists, is snake_case, and is not also cataloged as a command.

    `listed` is the command/script/asset set only: a module is expected to be absent from it, so an
    overlap means one file was declared under two kinds.
    """
    findings: Findings = []
    for entry in modules:
        name = entry.get("name") if isinstance(entry, dict) else None
        if not isinstance(name, str):
            findings.append((MANIFEST, 1, "invalid-tool-catalog",
                             "modules entries must be objects with a name"))
            continue
        if not MODULE_NAME.match(name):
            findings.append((MANIFEST, 1, "tool-name",
                             f"{name}: an imported module is snake_case (^[a-z0-9_]+\\.py$)"))
        if name in listed:
            findings.append((MANIFEST, 1, "invalid-tool-catalog",
                             f"{name}: declared both as a module and as a command"))
        if not (root / ".agent/tools" / str(entry.get("dir", ".")) / name).is_file():
            findings.append((MANIFEST, 1, "cataloged-module-unavailable",
                             f"{name} does not exist under its declared dir"))
    return findings


def lint_tool_naming(root: Path, modules: set[str], cataloged: set[str]) -> Findings:
    """An undeclared executable is `crew-`-prefixed; a module another tool imports is snake_case.

    Checked over the tree, so a file added without a catalog entry is still judged by the rule it
    violates. Cataloged names are skipped because the catalog judges them.
    """
    findings: Findings = []
    for path in tool_tree_files(root):
        if path.suffix not in {".py", ".sh"} or path.name in modules | cataloged:
            continue
        if not COMMAND_NAME.match(path.name) and not MODULE_NAME.match(path.name):
            findings.append((rel(root, path), 1, "tool-name",
                             f"{path.name} is neither ^crew-[a-z0-9-]+\\.(py|sh)$ nor a snake_case "
                             f"module; rename it like crew-ls.py, or declare it under `modules` "
                             f"when another tool imports it"))
    return findings


def tree_naming(root: Path, modules: list, listed: list) -> Findings:
    """The module declarations, the tree-wide naming rule, and any uncatalogued executable."""
    findings: Findings = []
    module_names = {entry.get("name") for entry in modules if isinstance(entry, dict)}
    listed_names = {entry.get("name") for entry in listed}
    cataloged = listed_names | module_names
    findings.extend(lint_tool_modules(root, modules, listed_names))
    findings.extend(lint_tool_naming(root, module_names, cataloged))
    for path in tool_tree_files(root):
        if path.suffix in {".py", ".sh"} and path.name not in cataloged:
            findings.append((rel(root, path), 1, "uncataloged-tool",
                             f"{path.name} is executable but absent from tools.json"))
    return findings
