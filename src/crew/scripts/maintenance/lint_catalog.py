"""The tool manifest and basename naming: `kind`, entry fields, resolution, and the installed surface.

What `~/.agent/bin` links is a command (`crew-` prefix; a Python one is the module `crew_<name>.py` and its
pyproject launcher), everything importable a module (snake_case, declared under `modules`, never linked),
anything else an asset; an entry's section fixes its kind. A tree-wide check catches an uncatalogued file.
"""

from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path

from crew.scripts.maintenance.lint_files import rel

MANIFEST = "src/crew/tools.json"
# The naming standard in TOOLS.md. A hyphen cannot appear in a Python import, so the two shapes are
# disjoint by construction rather than by convention an author has to remember.
COMMAND_NAME = re.compile(r"^crew-[a-z0-9-]+\.(py|sh)$")
MODULE_NAME = re.compile(r"^[a-z0-9_]+\.py$")
CATALOG_SECTIONS = (("tools", "command"), ("modules", "module"), ("assets", "asset"))
Findings = list[tuple[str, int, str, str]]


def tool_tree_files(root: Path) -> list[Path]:
    """Every file in the tool tree, so a name is checked wherever it is filed."""
    directory = root / "src/crew"
    if not directory.is_dir():
        return []
    return sorted(path for path in directory.rglob("*") if path.is_file() and "__pycache__" not in path.parts and path.name != "__init__.py")


def installed_tool_names(root: Path) -> set[str]:
    """Basenames the installer links into `~/.agent/bin`: every `kind: command` catalog entry.

    Read from the manifest rather than the tree, because that is what `install.sh` links. A module
    is deliberately absent: it is imported, never installed, so a `~/.agent/bin/<module>` reference
    is a broken invocation and reports as one.
    """
    try:
        data = json.loads((root / MANIFEST).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return set()
    return {
        entry.get("name")
        for section, _ in CATALOG_SECTIONS
        for entry in data.get(section, [])
        if isinstance(entry, dict) and entry.get("kind") == "command" and isinstance(entry.get("name"), str)
    }


def installable_naming(data: dict) -> Findings:
    """Every command basename matches `^crew-[a-z0-9-]+\\.(py|sh)$`."""
    findings: Findings = []
    for section, _ in CATALOG_SECTIONS:
        for entry in data.get(section, []):
            if not isinstance(entry, dict) or entry.get("kind") != "command":
                continue
            name = entry.get("name")
            if not COMMAND_NAME.match(str(name)):
                findings.append((MANIFEST, 1, "command-name", f"{name}: a command matches ^crew-[a-z0-9-]+\\.(py|sh)$"))
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
            findings.append((MANIFEST, 1, "invalid-tool-catalog", "modules entries must be objects with a name"))
            continue
        if not MODULE_NAME.match(name):
            findings.append((MANIFEST, 1, "tool-name", f"{name}: an imported module is snake_case (^[a-z0-9_]+\\.py$)"))
        if name in listed:
            findings.append((MANIFEST, 1, "invalid-tool-catalog", f"{name}: declared both as a module and as a command"))
        if not (root / "src/crew" / str(entry.get("dir", ".")) / name).is_file():
            findings.append((MANIFEST, 1, "cataloged-module-unavailable", f"{name} does not exist under its declared dir"))
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
            findings.append(
                (
                    rel(root, path),
                    1,
                    "tool-name",
                    f"{path.name} is neither ^crew-[a-z0-9-]+\\.(py|sh)$ nor a snake_case module; rename it like crew-ls.py, or declare it under `modules` when another tool imports it",
                )
            )
    return findings


def tree_naming(root: Path, modules: list, listed: list) -> Findings:
    """The module declarations, the tree-wide naming rule, and any uncatalogued executable."""
    findings: Findings = []
    module_names = {entry.get("name") for entry in modules if isinstance(entry, dict)}
    listed_names = {entry.get("name") for entry in listed}
    cataloged = {catalog_path(root, entry).name for entry in listed} | module_names
    findings.extend(lint_tool_modules(root, modules, listed_names))
    findings.extend(lint_tool_naming(root, module_names, cataloged))
    for path in tool_tree_files(root):
        if path.suffix in {".py", ".sh"} and path.name not in cataloged:
            findings.append((rel(root, path), 1, "uncataloged-tool", f"{path.name} is executable but absent from tools.json"))
    return findings


CATALOG_KINDS = ("command", "module", "asset")
REQUIRED_FIELDS = {"name", "dir", "kind", "category", "owner", "help", "smoke"}
# Who runs a command; install links every audience but `dev`. An agent command lives in `tools/`, an owner one in `scripts/`.
AUDIENCE_DIRS = {"agent": "tools", "hook": "harness", "owner": "scripts", "dev": "scripts"}


def catalog_path(root: Path, entry: dict) -> Path:
    """The file a catalog entry names: its declared `dir` under `src/crew`; a Python command's module is snake_case."""
    name = str(entry.get("name"))
    if entry.get("kind") == "command" and name.endswith(".py"):
        name = name.replace("-", "_")
    return root / "src/crew" / str(entry.get("dir", ".")) / name


def launcher_target(entry: dict) -> str:
    """The `[project.scripts]` value that makes a Python command's launcher."""
    return f"crew.{str(entry['dir']).replace('/', '.')}.{catalog_path(Path(), entry).stem}:main"


def lint_catalog_kinds(data: dict) -> Findings:
    """`kind` is declared on every entry; a module never carries a command's basename."""
    findings: Findings = []
    for section, expected in CATALOG_SECTIONS:
        for entry in data.get(section, []):
            if not isinstance(entry, dict) or not isinstance(entry.get("name"), str):
                continue
            name, kind = entry["name"], entry.get("kind")
            if kind is None:
                findings.append((MANIFEST, 1, "catalog-kind-missing", f"{name}: add kind: {' or '.join(CATALOG_KINDS)}"))
            elif kind not in CATALOG_KINDS:
                findings.append((MANIFEST, 1, "catalog-kind-invalid", f"{name}: kind {kind!r} is not one of {', '.join(CATALOG_KINDS)}"))
            elif kind != expected:
                findings.append((MANIFEST, 1, "catalog-kind-invalid", f"{name}: listed under {section} so its kind is {expected}, not {kind}"))
            elif kind == "module" and COMMAND_NAME.match(name):
                findings.append((MANIFEST, 1, "installable-module", f"{name}: a module is imported, never installed, so it must not carry a command basename"))
    return findings


def lint_entry_fields(root: Path, entries: list, modules: list) -> Findings:
    """Each entry carries the required fields and resolves to a file; a command has its audience's directory and its
    pyproject launcher. A module is imported, so existence is enough."""
    findings: Findings = []
    pyproject = root / "pyproject.toml"
    scripts = tomllib.loads(pyproject.read_text(encoding="utf-8"))["project"]["scripts"] if pyproject.is_file() else {}
    for listed, require_exec in ((entries, True), (modules, False)):
        for entry in listed:
            name = entry.get("name")
            missing = REQUIRED_FIELDS - entry.keys()
            if not isinstance(name, str):
                findings.append((MANIFEST, 1, "invalid-tool-catalog", "every catalog entry needs a string name"))
            elif missing:
                findings.append((MANIFEST, 1, "invalid-tool-catalog", f"{name}: missing {', '.join(sorted(missing))}"))
            else:
                path = catalog_path(root, entry)
                python = require_exec and name.endswith(".py")
                if require_exec and AUDIENCE_DIRS.get(entry.get("audience", "")) != entry["dir"]:
                    findings.append((MANIFEST, 1, "invalid-tool-catalog", f"{name}: audience {'|'.join(AUDIENCE_DIRS)} lives in its directory {AUDIENCE_DIRS}"))
                if python and scripts.get(name) != launcher_target(entry):
                    findings.append(
                        (
                            MANIFEST,
                            1,
                            "cataloged-tool-unavailable",
                            f'{name}: tools.json catalogs it, so pyproject.toml [project.scripts] needs "{name}" = "{launcher_target(entry)}"',
                        )
                    )
                if require_exec and not (python and path.is_file()):
                    findings.append((MANIFEST, 1, "cataloged-tool-unavailable", f"{name} is not a Python command at {rel(root, path)}"))
                elif not require_exec and not path.is_file():
                    findings.append((MANIFEST, 1, "cataloged-module-unavailable", f"{name} does not exist at {rel(root, path)}"))
    return findings


def lint_asset_entries(root: Path, assets: list) -> Findings:
    """Each declared asset exists at the path its `dir` gives."""
    findings: Findings = []
    for asset in assets:
        path = catalog_path(root, asset)
        if not path.is_file():
            findings.append((MANIFEST, 1, "cataloged-asset-unavailable", f"{asset.get('name')} does not exist at {rel(root, path)}"))
    return findings


def lint_tool_catalog(root: Path) -> Findings:
    """Validate the installed command surface without executing it.

    Entries resolve through their declared `dir`, never by basename in one flat directory: the tree
    is grouped by responsibility, so a lookup that ignored `dir` would report every entry missing.
    """
    manifest = root / "src/crew/tools.json"
    if not manifest.exists():
        return [("src/crew", 1, "missing-tool-catalog", "add tools.json")]
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
        entries, assets, modules = data["tools"], data.get("assets", []), data.get("modules", [])
    except (OSError, KeyError, TypeError, json.JSONDecodeError) as error:
        return [(MANIFEST, 1, "invalid-tool-catalog", str(error))]
    findings: Findings = []
    names = [entry.get("name") for entry in entries + assets]
    if len(names) != len(set(names)) or any(not isinstance(name, str) for name in names):
        findings.append((MANIFEST, 1, "invalid-tool-catalog", "tool and asset names must be unique strings"))
    kind_findings = lint_catalog_kinds(data)
    findings.extend(kind_findings)
    findings.extend(installable_naming(data))
    findings.extend(tree_naming(root, modules, entries + assets))
    findings.extend(lint_entry_fields(root, entries, modules))
    findings.extend(lint_asset_entries(root, assets))
    return findings
