"""Prompt frontmatter, tool grants, and the always-on budget with the per-file size ceilings.

A rule is `.mdc` with `description` and `alwaysApply`; an always-on one is `@`-imported for Claude
Code, whose payload (CLAUDE.md, every import, `AGENTS.md`) is the budget. A skill declares `name` and
`description`. Every `mcp__<server>__<tool>` and bare `tools:` id resolves against `tools.json`.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from lint_files import line_no, rel

# Measured 2026-11-21 at 7,204 tokens after the trim; 9,100 leaves room for prompt-engineering.mdc,
# which is imported because Claude Code ignores globs and prompt work is frequent here. The `crew inbox`
# row measured 9,112 and the 2026-11-23 `crew pr` row measured 9,145, after compressing `crew
# review-stats`, `crew ls`, and `crew prune` paid for it. Raise it only with a new measurement.
MAX_ALWAYS_RULE_TOKENS = 9150
# An agent or skill file is read whole, so its ceiling is bytes rather than a token estimate: the
# dispatch cost of a 12 KB prompt is already large, and prose above it belongs in a references file.
MAX_PROMPT_FILE_BYTES = 12_000
MAX_PROMPT_FILE_LINES = 500
ALWAYS_LOADED_PROJECT_FILES = ("AGENTS.md", ".claude/CLAUDE.md")
PROMPT_ROOTS = (".cursor/agents", ".cursor/skills")
Findings = list[tuple[str, int, str, str]]


def claude_imports(root: Path) -> set[str]:
    """Rule filenames `@`-imported by a repository CLAUDE.md.

    Only the repository's own files are read: `$HOME/.claude/CLAUDE.md` is generated from
    `.claude/CLAUDE.md` by `install.sh`, so including it would let a stale machine-level copy mask a
    missing repository import and would make the token count differ per machine.
    """
    names: set[str] = set()
    for candidate in (root / "CLAUDE.md", root / ".claude/CLAUDE.md"):
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


def always_on_files(root: Path) -> list[tuple[str, int]]:
    """Every file a request pays for, with its size in bytes, largest first."""
    rule_dir = root / "rules"
    cursor_payload = {rule.name for rule in rule_dir.glob("*.mdc")
                      if re.search(r"alwaysApply:\s*true", rule.read_text(errors="replace"))}
    sizes: list[tuple[str, int]] = []
    for name in cursor_payload | claude_imports(root):
        path = rule_dir / name
        if path.is_file():
            sizes.append((f"rules/{name}", len(path.read_text(errors="replace"))))
    for name in ALWAYS_LOADED_PROJECT_FILES:
        path = root / name
        if path.is_file():
            sizes.append((name, len(path.read_text(errors="replace"))))
    return sorted(sizes, key=lambda entry: -entry[1])


def always_on_tokens(root: Path) -> int:
    """The estimate `--budget` prints and the ceiling enforces, from one measurement."""
    return sum(size // 4 for _, size in always_on_files(root))


def prompt_files(root: Path) -> list[Path]:
    """Every agent and skill Markdown file, references included."""
    found: list[Path] = []
    for pattern in PROMPT_ROOTS:
        found.extend(path for path in (root / pattern).rglob("*.md") if path.is_file())
    return sorted(found)


def lint_budget(root: Path, all_files: list[Path], rules: set[str]) -> Findings:
    """The always-on token estimate, the per-file size caps, and the duplicate-rule layout."""
    findings: Findings = []
    sizes = always_on_files(root)
    always = sum(size // 4 for _, size in sizes)
    if always > MAX_ALWAYS_RULE_TOKENS:
        largest, size = sizes[0]
        findings.append((largest, 1, "budget",
                         f"always-on set estimates {always} tokens (>{MAX_ALWAYS_RULE_TOKENS}); "
                         f"largest contributor {largest} ({size} bytes)"))
    for path in all_files:
        name = rel(root, path)
        lines = path.read_text(errors="replace").count("\n") + 1
        if ("/agents/" in name or "/skills/" in name) and lines > MAX_PROMPT_FILE_LINES:
            findings.append((name, 1, "budget", f"{lines} lines (>{MAX_PROMPT_FILE_LINES})"))
    for path in prompt_files(root):
        size = path.stat().st_size
        if size > MAX_PROMPT_FILE_BYTES:
            findings.append((rel(root, path), 1, "prompt-budget",
                             f"{size} bytes (>{MAX_PROMPT_FILE_BYTES}); move reference material "
                             f"into a references/ file read on demand"))
    for rule in rules:
        if (root / "rules" / rule).exists() and (root / ".cursor/rules" / rule).exists():
            findings.append((f"rules/{rule}", 1, "budget",
                             "rule exists under rules and .cursor/rules"))
    return findings


# The source of truth for skills that may activate without an explicit `crew` command.
MODEL_INVOCABLE_SKILLS = {"crew-diagnose", "crew-evals", "crew-recall", "crew-test", "spec-writing"}
# Agents that write by definition, so `readonly` cannot apply to them. `reviewer-probe` is here
# because a probe is a throwaway artifact and the rule that keeps it honest is deletion, not
# `readonly`: a read-only worker could not run the artifact that is the whole point.
WRITE_CAPABLE_AGENTS = {"crew-builder", "reviewer-probe"}
# Orchestrators the router refuses to dispatch, so `readonly` — a subagent-only field — never applies.
INLINE_ONLY_AGENTS = {"crew-reviewer", "crew-specwriter"}
# The exact `disallowedTools` of a read-only agent with no `tools:` line, which inherits every session
# tool in Claude Code: the native writers, Agent, and by pattern the MCP servers whose tools write.
# Read-only search servers (sourcerer, elastic-*docs, semantic-code-search) stay available; a server
# not listed is denied only by the agent's instructions (.agent/tools/AGENTS.md).
READONLY_AGENT_DENY = ("Write", "Edit", "NotebookEdit", "Bash", "Agent", "mcp__github__*", "mcp__gitlab__*", "mcp__slack__*", "mcp__linear__*",
                       "mcp__jira__*", "mcp__atlassian__*", "mcp__notion__*", "mcp__filesystem__*", "mcp__claude_ai_Claude_Docs__*")
MANIFEST = ".agent/tools/tools.json"
MCP_REFERENCE = re.compile(r"mcp__([a-z0-9-]+)__([a-z0-9_]+)")
TOOLS_LINE = re.compile(r"^tools:\s*(.+)$", re.MULTILINE)


def parse_frontmatter(text: str) -> tuple[str | None, str | None, str | None]:
    if not text.startswith("---\n"):
        return None, "missing", "add YAML frontmatter at the start of the file"
    value, separator, _ = text[4:].partition("\n---\n")
    if not separator:
        return None, "invalid", "close YAML frontmatter"
    return value, None, None


def lint_rule_setup(root: Path) -> Findings:
    """Every rule is `.mdc` with the required frontmatter, and an always-on rule reaches both harnesses."""
    findings: Findings = []
    rule_dir = root / "rules"
    if not rule_dir.is_dir():
        rule_dir = root / ".cursor/rules"
    for path in sorted(rule_dir.iterdir()):
        if not path.is_file():
            continue
        name = rel(root, path)
        if path.suffix == ".md":
            findings.append((name, 1, "inactive-rule-extension", "Cursor rules must use .mdc"))
            continue
        if path.suffix != ".mdc":
            continue
        frontmatter_text, error_kind, error = parse_frontmatter(path.read_text(errors="replace"))
        if error:
            findings.append((name, 1, f"{error_kind}-rule-frontmatter", error))
            continue
        if not re.search(r"^description:\s*\S", frontmatter_text, re.MULTILINE):
            findings.append((name, 1, "invalid-rule-frontmatter", "add description"))
        if not re.search(r"^alwaysApply:\s*(?:true|false)\s*$", frontmatter_text, re.MULTILINE):
            findings.append((name, 1, "invalid-rule-frontmatter", "set alwaysApply true or false"))
        if re.search(r"^alwaysApply:\s*true\s*$", frontmatter_text, re.MULTILINE):
            unreachable = always_on_unreachable(root, path.name)
            if unreachable:
                findings.append((name, 1, "always-on-rule-unreachable", unreachable))
    return findings


def lint_skill_setup(root: Path) -> Findings:
    """Every skill declares its identity and is either model-invocable by name or opted out."""
    findings: Findings = []
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
        if path.parent.name not in MODEL_INVOCABLE_SKILLS and not re.search(
            r"^disable-model-invocation:\s*true\s*$", frontmatter_text, re.MULTILINE
        ):
            findings.append((name, 1, "missing-disable-model-invocation",
                             "set disable-model-invocation: true or add the skill to "
                             "MODEL_INVOCABLE_SKILLS"))
    return findings


def lint_agent_readonly(root: Path) -> Findings:
    """A read-only agent declares `readonly: true` (Cursor) and, when it has no `tools:` line and so
    inherits every tool, `disallowedTools` equal to READONLY_AGENT_DENY (Claude Code); a writing agent
    declares neither. The two exemption sets keep each exception a reviewed edit."""
    findings: Findings = []
    agent_dir = root / ".cursor/agents"
    if not agent_dir.is_dir():
        return findings
    for path in sorted(agent_dir.glob("*.md")):
        frontmatter_text, error_kind, error = parse_frontmatter(path.read_text(errors="replace"))
        if error:
            findings.append((rel(root, path), 1, f"{error_kind}-agent-frontmatter", error))
            continue
        declared = re.search(r"^readonly:\s*(true|false)\s*$", frontmatter_text, re.MULTILINE)
        if path.stem in WRITE_CAPABLE_AGENTS:
            if declared and declared.group(1) == "true":
                findings.append((rel(root, path), 1, "unexpected-readonly",
                                 f"{path.stem} writes, so readonly: true would block every edit"))
        elif path.stem in INLINE_ONLY_AGENTS:
            continue
        elif not declared or declared.group(1) != "true":
            findings.append((rel(root, path), 1, "missing-readonly",
                             "set readonly: true, or add the agent to WRITE_CAPABLE_AGENTS / "
                             "INLINE_ONLY_AGENTS in lint_prompts.py with a reason"))
        elif not re.search(r"^tools:", frontmatter_text, re.MULTILINE) and {item.strip() for item in (
                re.search(r"^disallowedTools:(.*)$", frontmatter_text, re.MULTILINE) or [None, ""])[1].split(",")} - {""} != set(READONLY_AGENT_DENY):
            findings.append((rel(root, path), 1, "inherited-tools-can-write", "no tools: line inherits every tool in Claude Code; "
                             f"set disallowedTools: {', '.join(READONLY_AGENT_DENY)} (READONLY_AGENT_DENY)"))
    return findings


def load_tool_surface(root: Path) -> tuple[dict[str, list[str]], set[str], Findings]:
    """Read the MCP-server and native-tool allowlists that tool references are resolved against."""
    try:
        data = json.loads((root / MANIFEST).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        return {}, set(), [(MANIFEST, 1, "invalid-tool-catalog", str(error))]
    findings: Findings = []
    servers = data.get("mcp_servers")
    # JSON object keys are always strings, so only the values need checking.
    if not isinstance(servers, dict) or not all(isinstance(tools, list) and all(isinstance(tool, str) for tool in tools) for tools in servers.values()):
        findings.append((MANIFEST, 1, "invalid-tool-catalog", "mcp_servers must map server names to lists of tool names"))
        servers = {}
    native = data.get("native_tools")
    if not isinstance(native, list) or not all(isinstance(tool, str) for tool in native):
        findings.append((MANIFEST, 1, "invalid-tool-catalog",
                         "native_tools must be a list of tool names"))
        native = []
    return servers, set(native), findings


def lint_mcp_references(root: Path, paths: list[Path], servers: dict[str, list[str]]) -> Findings:
    """Resolve every mcp__<server>__<tool> reference against the declared allowlist."""
    findings: Findings = []
    for path in paths:
        text = path.read_text(errors="replace")
        for match in MCP_REFERENCE.finditer(text):
            server, tool = match.group(1), match.group(2)
            if server not in servers:
                findings.append((rel(root, path), line_no(text, match.start()), "mcp-tool-unknown",
                                 f"{match.group(0)}: server {server} is not in mcp_servers"))
            elif tool not in servers[server]:
                findings.append((rel(root, path), line_no(text, match.start()), "mcp-tool-unknown",
                                 f"{match.group(0)}: {server} has no tool {tool} in mcp_servers"))
    return findings


def lint_native_tool_ids(root: Path, paths: list[Path], native: set[str]) -> Findings:
    """Resolve each bare tool name in an agent's `tools:` line against native_tools.

    `mcp-grant-policy`: no `tools:` line names an `mcp__` id, because a granted id fails the whole
    dispatch on a project without that server; vendor tools stay optional prose.
    """
    findings: Findings = []
    agent_dir = root / ".cursor/agents"
    for path in paths:
        if agent_dir not in path.parents:
            continue
        text = path.read_text(errors="replace")
        for match in TOOLS_LINE.finditer(text):
            for entry in match.group(1).split(","):
                tool = entry.strip()
                if tool.startswith("mcp__"):
                    findings.append((rel(root, path), line_no(text, match.start()), "mcp-grant-policy",
                                     f"{tool}: grant no MCP id; name it in prose as optional"))
                elif tool and tool not in native:
                    findings.append((rel(root, path), line_no(text, match.start()),
                                     "tool-id-unknown", f"{tool} is not in native_tools"))
    return findings


def lint_tool_surface(root: Path, all_files: list[Path]) -> Findings:
    """Both halves of the tool-grant check; a malformed allowlist suppresses the reference checks."""
    servers, native, findings = load_tool_surface(root)
    if findings:
        return findings
    findings.extend(lint_mcp_references(root, all_files, servers))
    findings.extend(lint_native_tool_ids(root, all_files, native))
    return findings
