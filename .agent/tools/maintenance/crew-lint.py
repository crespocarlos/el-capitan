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

# Always-on rules are paid by every request in every session, so the cap is a ceiling on
# per-turn context, not a target.
#
# The number is the *larger* of the two harnesses' payloads. Claude Code ignores `alwaysApply` and
# `globs`, loading CLAUDE.md plus every `@` import whatever its glob says, so an imported glob rule
# costs it every turn while costing Cursor only on matching files. Measured 2026-11-18 at the
# maximum: 13,874 tokens — 6,997 of always-on rules, 2,963 AGENTS.md, 990 .claude/CLAUDE.md, and
# 2,924 of `@`-imported rules that the previous counter missed entirely (it reported 11,225 while
# Claude Code loaded 13,874).
#
# Two corrections produced the rise from 7,500: the counter learned about AGENTS.md and CLAUDE.md,
# then learned about imports. Neither added a rule — both stopped under-reporting rules that were
# already loaded. Raise this only with a new measurement recorded here; when the set grows without
# a new rule to justify it, trim the set instead. The first trim candidates are
# `crew-orchestrator.mdc` and `crew-router.mdc` (2,819 combined), whose routing and state-machine
# detail is read once per pipeline step rather than needed on every turn.
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
EXECUTABLE_NAME = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*\.(py|sh)$")
MODULE_NAME = re.compile(r"^[a-z0-9_]+\.py$")


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


def lint_tool_naming(root: Path, modules: set[str]) -> list[tuple[str, int, str, str]]:
    """Every executable is kebab-case; a module another tool imports is snake_case and declared.

    Checked over the tree rather than the catalog alone, so a file added without a catalog entry is
    still judged by the rule it violates instead of only by its missing entry.
    """
    findings: list[tuple[str, int, str, str]] = []
    for path in tool_tree_files(root):
        if path.suffix not in {".py", ".sh"} or path.name in modules:
            continue
        if not EXECUTABLE_NAME.match(path.name):
            findings.append((rel(root, path), 1, "tool-name",
                             f"{path.name} is not kebab-case; rename it like crew-ls.py, or declare "
                             f"it under `modules` when another tool imports it"))
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
    """Basenames the installer links into `~/.agent/bin` before any migration cleanup.

    Every file in the tree is linked, cataloged or not, so a `~/.agent/bin/<name>` reference
    resolves against the tree rather than against the catalog.
    """
    return {path.name for path in tool_tree_files(root)}


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
    findings.extend(lint_tool_modules(root, modules))
    module_names = {entry.get("name") for entry in modules if isinstance(entry, dict)}
    findings.extend(lint_tool_naming(root, module_names))

    cataloged = {entry.get("name") for entry in entries + scripts + assets} | module_names
    for path in tool_tree_files(root):
        if path.suffix in {".py", ".sh"} and path.name not in cataloged:
            findings.append((rel(root, path), 1, "uncataloged-tool",
                             f"{path.name} is executable but absent from tools.json"))

    for listed in (entries, scripts, modules):
        for entry in listed:
            name = entry.get("name")
            required = {"name", "dir", "category", "owner", "help", "smoke"}
            missing = required - entry.keys()
            if not isinstance(name, str):
                findings.append((".agent/tools/tools.json", 1, "invalid-tool-catalog",
                                 "every catalog entry needs a string name"))
            elif missing:
                findings.append((".agent/tools/tools.json", 1, "invalid-tool-catalog",
                                 f"{name}: missing {', '.join(sorted(missing))}"))
            else:
                path = catalog_path(root, entry)
                if not path.is_file() or not os.access(path, os.X_OK):
                    findings.append((".agent/tools/tools.json", 1, "cataloged-tool-unavailable",
                                     f"{name} does not exist or is not executable at "
                                     f"{rel(root, path)}"))
    for asset in assets:
        name = asset.get("name")
        path = catalog_path(root, asset)
        if not path.is_file():
            findings.append((".agent/tools/tools.json", 1, "cataloged-asset-unavailable",
                             f"{name} does not exist at {rel(root, path)}"))
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
    """A log-progress call must pass a state transition, not an event label.

    log-progress.py prefixes `TRANSITION: ` itself, so an event string like "commit: abc123" writes
    a line that is not a transition. Events belong in log-metric.py, which owns the METRIC line.
    """
    findings: list[tuple[str, int, str, str]] = []
    pattern = re.compile(r"log-progress\.py\"?\s+\"?\$TASK_DIR\"?\s+\"([^\"]*)\"")
    for path in paths:
        text = path.read_text(errors="replace")
        for match in pattern.finditer(text):
            value = match.group(1)
            if "→" not in value and "->" not in value:
                findings.append((rel(root, path), line_no(text, match.start()),
                                 "progress-not-a-transition",
                                 f'"{value}" has no state transition; use log-progress for '
                                 'FROM → TO and log-metric for events'))
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


def lint(root: Path, budget: bool) -> list[tuple[str, int, str, str]]:
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
    rule_dir = root / "rules"
    rules = (
        {path.name for path in rule_dir.glob("*.mdc")}
        if rule_dir.is_dir()
        else {path.name for path in (root / ".cursor/rules").glob("*.mdc")}
    )
    agents = {path.stem for path in (root / ".cursor/agents").glob("*.md")}
    router = root / "rules/crew-router.mdc"
    if not router.exists():
        router = root / ".cursor/rules/crew-router.mdc"
    router_text = router.read_text() if router.exists() else ""
    routed = set(re.findall(r"`(crew [^`|]+?)(?:`|\s)", router_text))
    routed.update(re.findall(r"\|\s*`(crew [^`]+)`", router_text))
    routed_commands = {
        match.group(1)
        for command in routed
        if (match := re.match(r"crew\s+([a-z-]+)", command))
    }

    for path in all_files:
        text = path.read_text(errors="replace")
        name = rel(root, path)
        for match in re.finditer(r"tasks/(?:\$REPO|<repo>)", text):
            findings.append((name, line_no(text, match.start()), "stale-task-path",
                             "use resolve-task-dir.py instead"))
        for match in re.finditer(r"~/.agent/bin/([\w.-]+)", text):
            script = match.group(1)
            if script not in installed_names:
                findings.append((name, line_no(text, match.start()), "missing-script",
                                 f"{script} is not in the .agent/tools tree"))
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
        for line, value in enumerate(text.splitlines(), 1):
            if name == "rules/crew-router.mdc":
                continue
            for command in re.findall(r"\bcrew\s+([a-z-]+)", value):
                if command in {"member", "command", "commands", "triggers", "protocol"}:
                    continue
                if command not in routed_commands:
                    findings.append((name, line, "unrouted-command",
                                     f"crew {command} has no routing row"))
            if any(name in value for name in MEMORY_COMMANDS) and (
                "2>/dev/null" in value or "|| true" in value
            ):
                findings.append((name, line, "swallowed-call",
                                 "memory command failure is hidden"))
            # State and gate commands must surface failure; audit logging is the one
            # legitimate exception because it cannot change a pipeline decision. A hook
            # that must never block a session opts out with a `crew-lint: allow-swallow`
            # comment on its own line.
            if "~/.agent/bin/" in value and "log-metric.py" not in value and (
                "2>/dev/null" in value or re.search(r"\|\|\s*true", value)
            ):
                exempt = "crew-lint: allow-swallow" in value
                if not exempt and not re.search(r"\|\|\s*(echo|printf|exit)", value):
                    findings.append((name, line, "swallowed-call",
                                     "agent command failure is hidden"))
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

    referenced_hooks = ""
    for config in (root / ".claude/settings.json", root / ".cursor/hooks.template.json"):
        if config.exists():
            referenced_hooks += config.read_text(errors="replace")
    for hook in (root / ".claude/hooks").glob("*.sh"):
        if hook.name not in referenced_hooks:
            findings.append((rel(root, hook), 1, "unregistered-hook",
                             "hook is not registered in a settings file"))

    if budget:
        always = 0
        # Measure the larger of the two harnesses' payloads, not Cursor's `alwaysApply` set alone.
        # Claude Code ignores `alwaysApply` and `globs` entirely, loading CLAUDE.md plus its `@`
        # imports whatever their globs say — so an `@`-imported glob rule costs this harness every
        # turn while costing Cursor only on matching files. Counting only `alwaysApply: true`
        # undercounted by 2,649 tokens, which is exactly the blind spot that let the ceiling drift.
        cursor_payload = set()
        for rule in rule_dir.glob("*.mdc"):
            text = rule.read_text(errors="replace")
            if re.search(r"alwaysApply:\s*true", text):
                cursor_payload.add(rule.name)
        claude_payload = claude_imports(root)
        for name in sorted(cursor_payload | claude_payload):
            path = rule_dir / name
            if path.is_file():
                always += len(path.read_text(errors="replace")) // 4
        # AGENTS.md and .claude/CLAUDE.md are always loaded too, through `@AGENTS.md` and the
        # repo context file, so counting only `rules/*.mdc` measured a fraction of the real
        # per-turn payload: the five rules below it reported 6,997 tokens while the true
        # always-on set was over 10,000. A budget that omits the two largest files cannot
        # constrain anything.
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
                findings.append((rel(root, path), 1, "budget",
                                 f"{lines} lines (>500)"))
        for rule in rules:
            if (root / "rules" / rule).exists() and (root / ".cursor/rules" / rule).exists():
                findings.append((f"rules/{rule}", 1, "budget",
                                 "rule exists under rules and .cursor/rules"))
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
