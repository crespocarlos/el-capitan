#!/usr/bin/env python3
"""The tool manifest: `kind`, entry fields, and each entry's resolution to a file.

One manifest, one rule: what `~/.agent/bin` links is a command, everything importable is a module,
and everything else is an asset. The section an entry sits in fixes its kind, so a command cannot
hide among the modules — which is exactly how eleven of them once installed as fake commands.
Basename naming and module declarations live in `lint_naming`; this module answers what each entry
is and whether it resolves.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from lint_files import rel
from lint_naming import COMMAND_NAME, installable_naming, tree_naming

MANIFEST = ".agent/tools/tools.json"
CATALOG_KINDS = ("command", "module", "asset")
CATALOG_SECTIONS = (("tools", "command"), ("scripts", "command"),
                    ("modules", "module"), ("assets", "asset"))
REQUIRED_FIELDS = {"name", "dir", "kind", "category", "owner", "help", "smoke"}
Findings = list[tuple[str, int, str, str]]


def catalog_path(root: Path, entry: dict) -> Path:
    """The file a catalog entry names: its declared `dir` under `.agent/tools`."""
    return root / ".agent/tools" / str(entry.get("dir", ".")) / str(entry.get("name"))


def lint_catalog_kinds(data: dict) -> tuple[Findings, set[str]]:
    """`kind` is declared on every entry; a module never carries a command's basename.

    Returns the declared command names, which the naming check needs to resolve a wrapper target.
    """
    findings: Findings = []
    commands: set[str] = set()
    for section, expected in CATALOG_SECTIONS:
        for entry in data.get(section, []):
            if not isinstance(entry, dict) or not isinstance(entry.get("name"), str):
                continue
            name, kind = entry["name"], entry.get("kind")
            if kind is None:
                findings.append((MANIFEST, 1, "catalog-kind-missing",
                                 f"{name}: add kind: {' or '.join(CATALOG_KINDS)}"))
            elif kind not in CATALOG_KINDS:
                findings.append((MANIFEST, 1, "catalog-kind-invalid",
                                 f"{name}: kind {kind!r} is not one of {', '.join(CATALOG_KINDS)}"))
            elif kind != expected:
                findings.append((MANIFEST, 1, "catalog-kind-invalid",
                                 f"{name}: listed under {section} so its kind is {expected}, "
                                 f"not {kind}"))
            elif kind == "module" and COMMAND_NAME.match(name):
                findings.append((MANIFEST, 1, "installable-module",
                                 f"{name}: a module is imported, never installed, so it must not "
                                 f"carry a command basename"))
            elif kind == "command":
                commands.add(name)
    return findings, commands


def lint_entry_fields(root: Path, entries: list, modules: list) -> Findings:
    """Each entry carries the required fields and resolves to a file; a command is executable.

    Only commands need the execute bit: they are what `~/.agent/bin` runs. A module is imported, so
    existence is enough, and `install.sh` never links one because it links `kind: command` only.
    """
    findings: Findings = []
    for listed, require_exec in ((entries, True), (modules, False)):
        for entry in listed:
            name = entry.get("name")
            missing = REQUIRED_FIELDS - entry.keys()
            if not isinstance(name, str):
                findings.append((MANIFEST, 1, "invalid-tool-catalog",
                                 "every catalog entry needs a string name"))
            elif missing:
                findings.append((MANIFEST, 1, "invalid-tool-catalog",
                                 f"{name}: missing {', '.join(sorted(missing))}"))
            else:
                path = catalog_path(root, entry)
                if require_exec and (not path.is_file() or not os.access(path, os.X_OK)):
                    findings.append((MANIFEST, 1, "cataloged-tool-unavailable",
                                     f"{name} does not exist or is not executable at "
                                     f"{rel(root, path)}"))
                elif not require_exec and not path.is_file():
                    findings.append((MANIFEST, 1, "cataloged-module-unavailable",
                                     f"{name} does not exist at {rel(root, path)}"))
    return findings


def lint_asset_entries(root: Path, assets: list) -> Findings:
    """Each declared asset exists at the path its `dir` gives."""
    findings: Findings = []
    for asset in assets:
        path = catalog_path(root, asset)
        if not path.is_file():
            findings.append((MANIFEST, 1, "cataloged-asset-unavailable",
                             f"{asset.get('name')} does not exist at {rel(root, path)}"))
    return findings


def lint_tool_catalog(root: Path) -> Findings:
    """Validate the installed command surface without executing it.

    Entries resolve through their declared `dir`, never by basename in one flat directory: the tree
    is grouped by responsibility, so a lookup that ignored `dir` would report every entry missing.
    """
    manifest = root / ".agent/tools/tools.json"
    if not manifest.exists():
        return [(".agent/tools", 1, "missing-tool-catalog", "add tools.json")]
    try:
        data = json.loads(manifest.read_text())
        entries, scripts = data["tools"], data.get("scripts", [])
        assets, modules = data.get("assets", []), data.get("modules", [])
    except (OSError, KeyError, TypeError, json.JSONDecodeError) as error:
        return [(MANIFEST, 1, "invalid-tool-catalog", str(error))]
    findings: Findings = []
    names = [entry.get("name") for entry in entries + scripts + assets]
    if len(names) != len(set(names)) or any(not isinstance(name, str) for name in names):
        findings.append((MANIFEST, 1, "invalid-tool-catalog",
                         "tool, script, and asset names must be unique strings"))
    kind_findings, commands = lint_catalog_kinds(data)
    findings.extend(kind_findings)
    findings.extend(installable_naming(data, commands))
    findings.extend(tree_naming(root, modules, entries + scripts + assets))
    findings.extend(lint_entry_fields(root, entries + scripts, modules))
    findings.extend(lint_asset_entries(root, assets))
    return findings
