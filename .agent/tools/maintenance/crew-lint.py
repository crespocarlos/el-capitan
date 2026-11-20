#!/usr/bin/env python3
"""Validate cross-file el-capitan conventions.

Usage: crew-lint.py [--root DIR] [--budget]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

# The always-on ceiling is the larger of the two harnesses' payloads; `lint_budget` measures it.
MAX_ALWAYS_RULE_TOKENS = 14500
# Loaded by every request in every session alongside the always-on rules, so they belong in the
# same budget. `AGENTS.md` arrives through `@AGENTS.md` in CLAUDE.md and through the repo context
# file; `.claude/CLAUDE.md` is loaded directly by that harness.
ALWAYS_LOADED_PROJECT_FILES = ("AGENTS.md", ".claude/CLAUDE.md")
# The source of truth for skills that may activate without an explicit `crew` command.
MODEL_INVOCABLE_SKILLS = {"crew-diagnose", "crew-evals", "crew-recall", "crew-test", "spec-writing"}
# The memory CLI under both its primary and deprecated basenames: a caller may still use either
# until the wrapper is removed, and a swallowed memory failure is a defect under both.
MEMORY_COMMANDS = ("crew-mem.py", "mem.py")


def files(root: Path) -> list[Path]:
    patterns = [
        "rules/*.mdc",
        ".cursor/rules/*.mdc",
        ".cursor/agents/**/*.md",
        ".cursor/skills/**/SKILL.md",
        ".cursor/skills/**/references/*.md",
        ".agent/tools/*.md",
        ".claude/CLAUDE.md",
        ".claude/settings.json",
        ".cursor/hooks.template.json",
        ".claude/hooks/*.sh",
    ]
    result: set[Path] = set()
    for pattern in patterns:
        result.update(path for path in root.glob(pattern) if path.is_file())
    return sorted(result)


def rel(root: Path, path: Path) -> str:
    return str(path.relative_to(root))


def line_no(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def parse_frontmatter(text: str) -> tuple[str | None, str | None, str | None]:
    if not text.startswith("---\n"):
        return None, "missing", "add YAML frontmatter at the start of the file"
    value, separator, _ = text[4:].partition("\n---\n")
    if not separator:
        return None, "invalid", "close YAML frontmatter"
    return value, None, None


# The naming standard in TOOLS.md. A hyphen cannot appear in a Python import, so the two shapes
# are disjoint by construction rather than by convention an author has to remember.
COMMAND_NAME = re.compile(r"^crew-[a-z0-9-]+\.(py|sh)$")
MODULE_NAME = re.compile(r"^[a-z0-9_]+\.py$")
# What a catalog entry is. `kind` is the field that separates the installable commands from the
# helpers that used to leak into `~/.agent/bin` as fake ones, so the installer and the lint read it
# instead of inferring intent from the directory a file sits in.
CATALOG_KINDS = ("command", "module", "asset")
CATALOG_SECTIONS = (("tools", "command"), ("scripts", "command"),
                    ("modules", "module"), ("assets", "asset"))
# Sourced, never executed. `source` needs a real file at a fixed path and a wrapper cannot supply
# one, so this one command keeps a name the `crew-` rule would otherwise reject.
SOURCE_ONLY_COMMANDS = {"task-env.sh"}


def tool_tree_files(root: Path) -> list[Path]:
    """Every file in the tool tree, so a name is checked wherever it is filed."""
    directory = root / ".agent/tools"
    if not directory.is_dir():
        return []
    return sorted(
        path for path in directory.rglob("*")
        if path.is_file() and "__pycache__" not in path.parts
    )


def catalog_path(root: Path, entry: dict) -> Path:
    """The file a catalog entry names: its declared `dir` under `.agent/tools`."""
    return root / ".agent/tools" / str(entry.get("dir", ".")) / str(entry.get("name"))


def lint_tool_naming(root: Path, modules: set[str], cataloged: set[str]) -> list[tuple[str, int, str, str]]:
    """An undeclared executable is `crew-`-prefixed; a module another tool imports is snake_case.

    Checked over the tree rather than the catalog alone, so a file added without a catalog entry is
    still judged by the rule it violates instead of only by its missing entry. Cataloged names are
    skipped here because the catalog judges them: a deprecated wrapper keeps its old, non-prefixed
    basename on purpose, and a source-only script cannot be renamed at all.
    """
    findings: list[tuple[str, int, str, str]] = []
    for path in tool_tree_files(root):
        if path.suffix not in {".py", ".sh"} or path.name in modules | cataloged:
            continue
        if not COMMAND_NAME.match(path.name) and not MODULE_NAME.match(path.name):
            findings.append((rel(root, path), 1, "tool-name",
                             f"{path.name} is neither ^crew-[a-z0-9-]+\\.(py|sh)$ nor a snake_case "
                             f"module; rename it like crew-ls.py, or declare it under `modules` "
                             f"when another tool imports it"))
    return findings


def lint_tool_modules(root: Path, modules: list) -> list[tuple[str, int, str, str]]:
    """A declared importable module exists, is snake_case, and is not also cataloged as a command."""
    findings: list[tuple[str, int, str, str]] = []
    commands = set()
    manifest = root / ".agent/tools/tools.json"
    try:
        data = json.loads(manifest.read_text())
        commands = {entry.get("name") for key in ("tools", "scripts", "assets")
                    for entry in data.get(key, [])}
    except (OSError, json.JSONDecodeError, AttributeError):
        pass
    for entry in modules:
        name = entry.get("name") if isinstance(entry, dict) else None
        if not isinstance(name, str):
            findings.append((".agent/tools/tools.json", 1, "invalid-tool-catalog",
                             "modules entries must be objects with a name"))
            continue
        if not MODULE_NAME.match(name):
            findings.append((".agent/tools/tools.json", 1, "tool-name",
                             f"{name}: an imported module is snake_case (^[a-z0-9_]+\\.py$)"))
        if name in commands:
            findings.append((".agent/tools/tools.json", 1, "invalid-tool-catalog",
                             f"{name}: declared both as a module and as a command"))
        if not catalog_path(root, entry).is_file():
            findings.append((".agent/tools/tools.json", 1, "cataloged-module-unavailable",
                             f"{name} does not exist under its declared dir"))
    return findings


def installed_tool_names(root: Path) -> set[str]:
    """Basenames the installer links into `~/.agent/bin`: every `kind: command` catalog entry.

    Read from the manifest rather than from the tree, because that is what `install.sh` links. A
    module's basename is deliberately absent: it is imported, never installed, so a
    `~/.agent/bin/<module>` reference is a broken invocation and now reports as one.
    """
    manifest = root / ".agent/tools/tools.json"
    try:
        data = json.loads(manifest.read_text())
    except (OSError, json.JSONDecodeError):
        return set()
    return {entry.get("name") for section, _ in CATALOG_SECTIONS
            for entry in data.get(section, [])
            if isinstance(entry, dict) and entry.get("kind") == "command"
            and isinstance(entry.get("name"), str)}


def lint_catalog_kinds(data: dict) -> tuple[list[tuple[str, int, str, str]], set[str]]:
    """`kind` is declared on every entry; a module never carries a command's basename.

    One manifest, one rule: what `~/.agent/bin` links is a command, everything importable is a
    module, and everything else is an asset. The section an entry sits in fixes its kind, so a
    command cannot hide among the modules, which is exactly how eleven of them installed as fake
    commands. Returns the declared command names for the wrapper check.
    """
    name = ".agent/tools/tools.json"
    findings: list[tuple[str, int, str, str]] = []
    commands: set[str] = set()
    for section, expected in CATALOG_SECTIONS:
        for entry in data.get(section, []):
            if not isinstance(entry, dict) or not isinstance(entry.get("name"), str):
                continue
            entry_name, kind = entry["name"], entry.get("kind")
            if kind is None:
                findings.append((name, 1, "catalog-kind-missing",
                                 f"{entry_name}: add kind: {' or '.join(CATALOG_KINDS)}"))
            elif kind not in CATALOG_KINDS:
                findings.append((name, 1, "catalog-kind-invalid",
                                 f"{entry_name}: kind {kind!r} is not one of "
                                 f"{', '.join(CATALOG_KINDS)}"))
            elif kind != expected:
                findings.append((name, 1, "catalog-kind-invalid",
                                 f"{entry_name}: listed under {section} so its kind is {expected}, "
                                 f"not {kind}"))
            elif kind == "module" and COMMAND_NAME.match(entry_name):
                findings.append((name, 1, "installable-module",
                                 f"{entry_name}: a module is imported, never installed, so it must "
                                 f"not carry a command basename"))
            elif kind == "command":
                commands.add(entry_name)
    return findings, commands


def lint_command_names(data: dict, commands: set[str]) -> list[tuple[str, int, str, str]]:
    """Every command basename follows `^crew-[a-z0-9-]+\\.(py|sh)$`, and a wrapper names its target.

    Two explicit exemptions: a deprecated wrapper keeps its old basename until it is removed, and
    `task-env.sh` is sourced — `source` needs a real file at a fixed path, which a wrapper cannot
    provide, so it cannot be renamed at all.
    """
    name = ".agent/tools/tools.json"
    findings: list[tuple[str, int, str, str]] = []
    for section, _ in CATALOG_SECTIONS:
        for entry in data.get(section, []):
            if not isinstance(entry, dict) or entry.get("kind") != "command":
                continue
            entry_name = entry.get("name")
            if entry_name in SOURCE_ONLY_COMMANDS:
                continue
            if entry.get("status") == "deprecated":
                replacement = entry.get("replacement")
                if not isinstance(replacement, str):
                    findings.append((name, 1, "catalog-kind-invalid",
                                     f"{entry_name}: a deprecated entry names its `replacement`"))
                elif replacement not in commands:
                    findings.append((name, 1, "catalog-kind-invalid",
                                     f"{entry_name}: replacement {replacement} is not a cataloged "
                                     f"command"))
            elif not COMMAND_NAME.match(str(entry_name)):
                findings.append((name, 1, "command-name",
                                 f"{entry_name}: a command matches ^crew-[a-z0-9-]+\\.(py|sh)$"))
    return findings


def lint_catalog_entries(
    root: Path, entries: list, scripts: list, modules: list
) -> list[tuple[str, int, str, str]]:
    """Each catalog entry carries the required fields and resolves to a file.

    Only commands need the execute bit: they are what `~/.agent/bin` runs. A module is imported, so
    existence is enough, and `install.sh` never links one because it links `kind: command` only.
    """
    findings: list[tuple[str, int, str, str]] = []
    for listed, require_exec in ((entries, True), (scripts, True), (modules, False)):
        for entry in listed:
            name = entry.get("name")
            required = {"name", "dir", "kind", "category", "owner", "help", "smoke"}
            missing = required - entry.keys()
            if not isinstance(name, str):
                findings.append((".agent/tools/tools.json", 1, "invalid-tool-catalog",
                                 "every catalog entry needs a string name"))
            elif missing:
                findings.append((".agent/tools/tools.json", 1, "invalid-tool-catalog",
                                 f"{name}: missing {', '.join(sorted(missing))}"))
            else:
                path = catalog_path(root, entry)
                if require_exec and (not path.is_file() or not os.access(path, os.X_OK)):
                    findings.append((".agent/tools/tools.json", 1, "cataloged-tool-unavailable",
                                     f"{name} does not exist or is not executable at "
                                     f"{rel(root, path)}"))
                elif not require_exec and not path.is_file():
                    findings.append((".agent/tools/tools.json", 1, "cataloged-module-unavailable",
                                     f"{name} does not exist at {rel(root, path)}"))
    return findings


def lint_asset_entries(root: Path, assets: list) -> list[tuple[str, int, str, str]]:
    """Each declared asset exists at the path its `dir` gives."""
    findings: list[tuple[str, int, str, str]] = []
    for asset in assets:
        name = asset.get("name")
        path = catalog_path(root, asset)
        if not path.is_file():
            findings.append((".agent/tools/tools.json", 1, "cataloged-asset-unavailable",
                             f"{name} does not exist at {rel(root, path)}"))
    return findings


def lint_tool_catalog(root: Path) -> list[tuple[str, int, str, str]]:
    """Validate the installed command surface (tools and scripts) without executing it.

    Entries resolve through their declared `dir`, never by basename in one flat directory: the tree
    is grouped by responsibility and only `tools.json`, `TOOLS.md`, and `requirements.txt` sit at its
    root, so a lookup that ignored `dir` would report every entry missing.
    """
    findings: list[tuple[str, int, str, str]] = []
    tool_dir = root / ".agent/tools"
    manifest = tool_dir / "tools.json"
    if not manifest.exists():
        return [(".agent/tools", 1, "missing-tool-catalog", "add tools.json")]
    try:
        data = json.loads(manifest.read_text())
        entries = data["tools"]
        scripts = data.get("scripts", [])
        assets = data.get("assets", [])
        modules = data.get("modules", [])
    except (OSError, KeyError, TypeError, json.JSONDecodeError) as error:
        return [(".agent/tools/tools.json", 1, "invalid-tool-catalog", str(error))]
    names = [entry.get("name") for entry in entries + scripts + assets]
    if len(names) != len(set(names)) or any(not isinstance(name, str) for name in names):
        findings.append((".agent/tools/tools.json", 1, "invalid-tool-catalog",
                         "tool, script, and asset names must be unique strings"))
    kind_findings, commands = lint_catalog_kinds(data)
    findings.extend(kind_findings)
    findings.extend(lint_command_names(data, commands))
    findings.extend(lint_tool_modules(root, modules))
    module_names = {entry.get("name") for entry in modules if isinstance(entry, dict)}

    cataloged = {entry.get("name") for entry in entries + scripts + assets} | module_names
    findings.extend(lint_tool_naming(root, module_names, cataloged))
    for path in tool_tree_files(root):
        if path.suffix in {".py", ".sh"} and path.name not in cataloged:
            findings.append((rel(root, path), 1, "uncataloged-tool",
                             f"{path.name} is executable but absent from tools.json"))

    findings.extend(lint_catalog_entries(root, entries, scripts, modules))
    findings.extend(lint_asset_entries(root, assets))
    return findings


def load_tool_surface(
    root: Path,
) -> tuple[dict[str, list[str]], set[str], list[tuple[str, int, str, str]]]:
    """Read the MCP-server and native-tool allowlists that tool references are resolved against."""
    manifest = root / ".agent/tools/tools.json"
    name = ".agent/tools/tools.json"
    try:
        data = json.loads(manifest.read_text())
    except (OSError, json.JSONDecodeError) as error:
        return {}, set(), [(name, 1, "invalid-tool-catalog", str(error))]
    findings: list[tuple[str, int, str, str]] = []
    servers = data.get("mcp_servers")
    if not isinstance(servers, dict) or not all(
        isinstance(server, str)
        and isinstance(tools, list)
        and all(isinstance(tool, str) for tool in tools)
        for server, tools in (servers or {}).items()
    ):
        findings.append((name, 1, "invalid-tool-catalog",
                         "mcp_servers must map server names to lists of tool names"))
        servers = {}
    native = data.get("native_tools")
    if not isinstance(native, list) or not all(isinstance(tool, str) for tool in native):
        findings.append((name, 1, "invalid-tool-catalog",
                         "native_tools must be a list of tool names"))
        native = []
    return servers, set(native), findings


def lint_mcp_references(
    root: Path, paths: list[Path], servers: dict[str, list[str]]
) -> list[tuple[str, int, str, str]]:
    """Resolve every mcp__<server>__<tool> reference against the declared allowlist."""
    findings: list[tuple[str, int, str, str]] = []
    pattern = re.compile(r"mcp__([a-z0-9-]+)__([a-z0-9_]+)")
    for path in paths:
        text = path.read_text(errors="replace")
        for match in pattern.finditer(text):
            server, tool = match.group(1), match.group(2)
            if server not in servers:
                findings.append((rel(root, path), line_no(text, match.start()), "mcp-tool-unknown",
                                 f"{match.group(0)}: server {server} is not in mcp_servers"))
            elif tool not in servers[server]:
                findings.append((rel(root, path), line_no(text, match.start()), "mcp-tool-unknown",
                                 f"{match.group(0)}: {server} has no tool {tool} in mcp_servers"))
    return findings


def lint_native_tool_ids(
    root: Path, paths: list[Path], native: set[str]
) -> list[tuple[str, int, str, str]]:
    """Resolve each bare tool name in an agent's `tools:` line against native_tools."""
    findings: list[tuple[str, int, str, str]] = []
    agent_dir = root / ".cursor/agents"
    for path in paths:
        if agent_dir not in path.parents:
            continue
        text = path.read_text(errors="replace")
        for match in re.finditer(r"^tools:\s*(.+)$", text, re.MULTILINE):
            for entry in match.group(1).split(","):
                tool = entry.strip()
                if not tool or tool.startswith("mcp__"):
                    continue
                if tool not in native:
                    findings.append((rel(root, path), line_no(text, match.start()), "tool-id-unknown",
                                     f"{tool} is not in native_tools"))
    return findings


def lint_progress_transitions(root: Path, paths: list[Path]) -> list[tuple[str, int, str, str]]:
    """A crew-progress call must pass a state transition, not an event label.

    crew-progress.py prefixes `TRANSITION: ` itself, so an event string like "commit: abc123"
    writes a line that is not a transition. Events belong in crew-metric.py, which owns the METRIC
    line. Both basenames are checked while the deprecated wrapper exists.
    """
    findings: list[tuple[str, int, str, str]] = []
    pattern = re.compile(r"(?:crew-|log-)progress\.py\"?\s+\"?\$TASK_DIR\"?\s+\"([^\"]*)\"")
    for path in paths:
        text = path.read_text(errors="replace")
        for match in pattern.finditer(text):
            value = match.group(1)
            if "→" not in value and "->" not in value:
                findings.append((rel(root, path), line_no(text, match.start()),
                                 "progress-not-a-transition",
                                 f'"{value}" has no state transition; use crew-progress for '
                                 'FROM → TO and crew-metric for events'))
    return findings


def lint_edit_discipline(root: Path, paths: list[Path]) -> list[tuple[str, int, str, str]]:
    """Flag guidance that tells an agent to rewrite a tracked file from a shell command.

    `python3 - <<'PY'` for a scratch artifact is fine. A script, `sed -i`, or `perl -i` aimed at
    editing repository prose or code is not: it bypasses the edit log and review diffs, and a moved
    anchor silently no-ops instead of failing. The rules name the correct tool once; this catches a
    later reference that reintroduces the shell habit.

    A rule that documents the prohibition names those commands in backticks, which the lookbehind
    excludes. A real instruction is prose, so it is still caught.
    """
    findings: list[tuple[str, int, str, str]] = []
    offenders = (
        (re.compile(r"(?<!`)\bsed\s+-[a-zA-Z]*i"), "sed -i rewrites a file in place; use the edit tool"),
        (re.compile(r"(?<!`)\bperl\s+-[a-zA-Z]*i"), "perl -i rewrites a file in place; use the edit tool"),
        (re.compile(r"str\.replace\(.*\)\.write_text|\.write_text\(.*\.replace\("),
         "replace-then-write as an edit; use the edit tool"),
    )
    for path in paths:
        if path.suffix not in {".md", ".mdc"}:
            continue
        text = path.read_text(errors="replace")
        for line_index, line in enumerate(text.splitlines()):
            for pattern, message in offenders:
                for match in pattern.finditer(line):
                    findings.append((rel(root, path), line_index + 1, "shell-file-edit", message))
    return findings


def lint_rule_setup(root: Path) -> list[tuple[str, int, str, str]]:
    findings: list[tuple[str, int, str, str]] = []
    rule_dir = root / "rules"
    if not rule_dir.is_dir():
        rule_dir = root / ".cursor/rules"

    for path in sorted(rule_dir.iterdir()):
        if not path.is_file():
            continue
        name = rel(root, path)
        if path.suffix == ".md":
            findings.append(
                (name, 1, "inactive-rule-extension", "Cursor rules must use .mdc")
            )
            continue
        if path.suffix != ".mdc":
            continue

        text = path.read_text(errors="replace")
        frontmatter_text, error_kind, error = parse_frontmatter(text)
        if error:
            findings.append(
                (name, 1, f"{error_kind}-rule-frontmatter", error)
            )
            continue
        if not re.search(r"^description:\s*\S", frontmatter_text, re.MULTILINE):
            findings.append(
                (name, 1, "invalid-rule-frontmatter", "add description")
            )
        if not re.search(r"^alwaysApply:\s*(?:true|false)\s*$", frontmatter_text, re.MULTILINE):
            findings.append(
                (name, 1, "invalid-rule-frontmatter", "set alwaysApply true or false")
            )
        if re.search(r"^alwaysApply:\s*true\s*$", frontmatter_text, re.MULTILINE):
            unreachable = always_on_unreachable(root, path.name)
            if unreachable:
                findings.append(
                    (name, 1, "always-on-rule-unreachable", unreachable)
                )
    return findings


def claude_imports(root: Path) -> set[str]:
    """Rule filenames `@`-imported by a CLAUDE.md this harness can see."""
    names: set[str] = set()
    for candidate in (root / "CLAUDE.md", root / ".claude/CLAUDE.md", Path.home() / ".claude/CLAUDE.md"):
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


def lint_skill_setup(root: Path) -> list[tuple[str, int, str, str]]:
    findings: list[tuple[str, int, str, str]] = []
    for path in sorted((root / ".cursor/skills").glob("*/SKILL.md")):
        text = path.read_text(errors="replace")
        name = rel(root, path)
        frontmatter_text, _, error = parse_frontmatter(text)
        if error:
            findings.append((name, 1, "invalid-skill-frontmatter", error))
            continue
        for key in ("name", "description"):
            if not re.search(rf"^{key}:\s*\S", frontmatter_text, re.MULTILINE):
                findings.append((name, 1, "invalid-skill-frontmatter", f"add {key}"))
        skill_name = path.parent.name
        if skill_name not in MODEL_INVOCABLE_SKILLS and not re.search(
            r"^disable-model-invocation:\s*true\s*$", frontmatter_text, re.MULTILINE
        ):
            findings.append(
                (name, 1, "missing-disable-model-invocation",
                 "set disable-model-invocation: true or add the skill to "
                 "MODEL_INVOCABLE_SKILLS")
            )
    return findings


def lint_repo_paths(root: Path, paths: list[Path]) -> list[tuple[str, int, str, str]]:
    """Flag backticked repo-relative paths that no longer exist."""
    findings: list[tuple[str, int, str, str]] = []
    pattern = re.compile(r"`((?:\.agent|\.cursor|\.claude|rules|evals)/[^`\s]*)`")
    for path in paths:
        text = path.read_text(errors="replace")
        for match in pattern.finditer(text):
            target = match.group(1)
            if any(char in target for char in "<>*${}"):
                continue
            if not (root / target.rstrip("/")).exists():
                findings.append((rel(root, path), line_no(text, match.start()), "stale-path",
                                 f"{target} does not exist"))
    return findings


def routing_commands(router_text: str) -> set[str]:
    """The `crew <command>` verbs the router recognizes, from both its table and its prose."""
    routed = set(re.findall(r"`(crew [^`|]+?)(?:`|\s)", router_text))
    routed.update(re.findall(r"\|\s*`(crew [^`]+)`", router_text))
    return {
        match.group(1)
        for command in routed
        if (match := re.match(r"crew\s+([a-z-]+)", command))
    }


def lint_swallowed_calls(
    name: str, lines: list[str]
) -> list[tuple[str, int, str, str]]:
    """Flag a memory or agent command whose failure is hidden by `2>/dev/null` or `|| true`.

    State and gate commands must surface failure; audit logging is the one legitimate exception
    because it cannot change a pipeline decision. A hook that must never block a session opts out
    with a `crew-lint: allow-swallow` comment on its own line.
    """
    findings: list[tuple[str, int, str, str]] = []
    for line, value in enumerate(lines, 1):
        if any(name in value for name in MEMORY_COMMANDS) and (
            "2>/dev/null" in value or "|| true" in value
        ):
            findings.append((name, line, "swallowed-call", "memory command failure is hidden"))
        if "~/.agent/bin/" in value and "crew-metric.py" not in value and (
            "2>/dev/null" in value or re.search(r"\|\|\s*true", value)
        ):
            exempt = "crew-lint: allow-swallow" in value
            if not exempt and not re.search(r"\|\|\s*(echo|printf|exit)", value):
                findings.append((name, line, "swallowed-call",
                                 "agent command failure is hidden"))
    return findings


def lint_document_refs(
    root: Path, path: Path, text: str, name: str, rules: set[str],
    agents: set[str], routed_commands: set[str], router: Path,
) -> list[tuple[str, int, str, str]]:
    """The per-document references: scripts, rules, agents, routing, frontmatter, references."""
    findings: list[tuple[str, int, str, str]] = []
    for match in re.finditer(r"([\w-]+\.mdc)", text):
        candidate = match.group(1)
        if candidate not in rules and candidate != path.name:
            findings.append((name, line_no(text, match.start()), "missing-rule-file",
                             f"{candidate} is not a rule file"))
    for match in re.finditer(r"(?:subagent_type:\s*|@)([\w-]+)", text):
        agent = match.group(1)
        if agent.startswith("crew-") and agent not in agents:
            findings.append((name, line_no(text, match.start()), "missing-agent",
                             f"{agent} is not in .cursor/agents"))
    if name != "rules/crew-router.mdc":
        for line, value in enumerate(text.splitlines(), 1):
            for command in re.findall(r"\bcrew\s+([a-z-]+)", value):
                if command in {"member", "command", "commands", "triggers", "protocol"}:
                    continue
                if command not in routed_commands:
                    findings.append((name, line, "unrouted-command",
                                     f"crew {command} has no routing row"))
    findings.extend(lint_swallowed_calls(name, text.splitlines()))
    if path.suffix == ".md" and ("/agents/" in name or path.name == "SKILL.md"):
        if text.startswith("---"):
            agent_frontmatter = text.split("---", 2)[1]
            for key in ("name:", "description:"):
                if key not in agent_frontmatter:
                    findings.append((name, 1, "bad-frontmatter",
                                     f"frontmatter lacks {key[:-1]}"))
        for match in re.finditer(r"\]\((references/[^)#]+)\)", text):
            target = path.parent / match.group(1)
            if not target.is_file():
                findings.append((name, line_no(text, match.start()), "missing-reference",
                                 f"{match.group(1)} does not exist"))
    if path != router and name != ".cursor/agents/crew-reviewer.md":
        for match in re.finditer(r"\|\s*`crew ", text):
            findings.append((name, line_no(text, match.start()), "routing-drift",
                             "routing tables belong only in crew-router.mdc"))
    return findings


def lint_installed_names(
    root: Path, all_files: list[Path], installed_names: set[str]
) -> list[tuple[str, int, str, str]]:
    """Every `~/.agent/bin/<name>` reference resolves to a file in the tool tree."""
    findings: list[tuple[str, int, str, str]] = []
    for path in all_files:
        text = path.read_text(errors="replace")
        name = rel(root, path)
        for match in re.finditer(r"~/.agent/bin/([\w.-]+)", text):
            script = match.group(1)
            if script not in installed_names:
                findings.append((name, line_no(text, match.start()), "missing-script",
                                 f"{script} is not in the .agent/tools tree"))
    return findings


def lint_budget(root: Path, all_files: list[Path], rules: set[str]) -> list[tuple[str, int, str, str]]:
    """The always-on token estimate and the per-file size caps.

    The estimate is the larger of the two harnesses' payloads, not Cursor's `alwaysApply` set
    alone: Claude Code ignores `alwaysApply` and `globs`, loading CLAUDE.md plus every `@` import
    whatever its glob says, so an imported glob rule costs that harness every turn. AGENTS.md and
    `.claude/CLAUDE.md` are always loaded too, so a budget that omits them cannot constrain. The
    ceiling was measured 2026-11-18 at 13,874 tokens; raise it only with a new measurement, and
    when the set grows with no new rule to justify it, trim the set instead.
    """
    findings: list[tuple[str, int, str, str]] = []
    rule_dir = root / "rules"
    always = 0
    cursor_payload = set()
    for rule in rule_dir.glob("*.mdc"):
        text = rule.read_text(errors="replace")
        if re.search(r"alwaysApply:\s*true", text):
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
        if ("/agents/" in rel(root, path) or "/skills/" in rel(root, path)) and lines > 500:
            findings.append((rel(root, path), 1, "budget", f"{lines} lines (>500)"))
    for rule in rules:
        if (root / "rules" / rule).exists() and (root / ".cursor/rules" / rule).exists():
            findings.append((f"rules/{rule}", 1, "budget",
                             "rule exists under rules and .cursor/rules"))
    return findings


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


def lint_hook_registration(root: Path) -> list[tuple[str, int, str, str]]:
    """Every hook script is named in a settings file, or it never runs."""
    findings: list[tuple[str, int, str, str]] = []
    referenced_hooks = ""
    for config in (root / ".claude/settings.json", root / ".cursor/hooks.template.json"):
        if config.exists():
            referenced_hooks += config.read_text(errors="replace")
    for hook in (root / ".claude/hooks").glob("*.sh"):
        if hook.name not in referenced_hooks:
            findings.append((rel(root, hook), 1, "unregistered-hook",
                             "hook is not registered in a settings file"))
    return findings


def lint_documents(
    root: Path, all_files: list[Path], installed_names: set[str], rules: set[str]
) -> list[tuple[str, int, str, str]]:
    """The per-document checks: stale paths, installed names, references, and hook registration."""
    findings: list[tuple[str, int, str, str]] = []
    agents = {path.stem for path in (root / ".cursor/agents").glob("*.md")}
    router = router_path(root)
    routed_commands = routing_commands(router.read_text() if router.exists() else "")
    findings.extend(lint_installed_names(root, all_files, installed_names))
    for path in all_files:
        text = path.read_text(errors="replace")
        name = rel(root, path)
        for match in re.finditer(r"tasks/(?:\$REPO|<repo>)", text):
            findings.append((name, line_no(text, match.start()), "stale-task-path",
                             "use crew-resolve-task-dir.py instead"))
        findings.extend(lint_document_refs(root, path, text, name, rules, agents,
                                           routed_commands, router))
    findings.extend(lint_hook_registration(root))
    return findings


def lint(root: Path, budget: bool) -> list[tuple[str, int, str, str]]:
    """Every check over one repository root; findings are `(path, line, rule, message)` tuples."""
    findings: list[tuple[str, int, str, str]] = []
    findings.extend(lint_tool_catalog(root))
    findings.extend(lint_rule_setup(root))
    findings.extend(lint_skill_setup(root))
    all_files = files(root)
    # What `~/.agent/bin` receives: every cataloged file, linked flat by basename.
    installed_names = installed_tool_names(root)
    servers, native, surface_findings = load_tool_surface(root)
    findings.extend(surface_findings)
    if not surface_findings:
        findings.extend(lint_mcp_references(root, all_files, servers))
        findings.extend(lint_native_tool_ids(root, all_files, native))
    findings.extend(lint_progress_transitions(root, all_files))
    findings.extend(lint_edit_discipline(root, all_files))
    docs = [root / name for name in ("README.md", "AGENTS.md") if (root / name).is_file()]
    findings.extend(lint_repo_paths(root, all_files + docs))
    rules = rule_names(root)
    findings.extend(lint_documents(root, all_files, installed_names, rules))
    if budget:
        findings.extend(lint_budget(root, all_files, rules))
    return findings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[3])
    parser.add_argument("--budget", action="store_true")
    args = parser.parse_args()
    if not args.root.is_dir():
        print(f"error: root does not exist: {args.root}", file=sys.stderr)
        return 2
    findings = lint(args.root.resolve(), args.budget)
    for path, line, rule, message in findings:
        print(f"{path}:{line}: {rule}: {message}")
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
