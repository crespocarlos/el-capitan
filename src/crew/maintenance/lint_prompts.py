"""Prompt frontmatter, tool grants, and the always-on budget with the per-file size ceilings.

A rule is `.mdc` with `description` and `alwaysApply`; an always-on one is `@`-imported for Claude
Code, whose payload (CLAUDE.md, every import, `AGENTS.md`) is the budget. A skill declares `name` and
`description`. Every `mcp__<server>__<tool>` and bare `tools:` id resolves against `tools.json`.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from crew.harness.adapters import ACCESS
from crew.lib.markdown import frontmatter, frontmatter_text
from crew.maintenance.lint_files import line_no, rel

# The always-on total plus 300 tokens of headroom; raise it only with a new measurement.
MAX_ALWAYS_RULE_TOKENS = 5672
# An agent or skill file is read whole, so its ceiling is bytes rather than a token estimate: prose
# above it belongs in a references file. 11,500 keeps every file 500 bytes clear of the 12 KB mark.
MAX_PROMPT_FILE_BYTES = 11_500
MAX_PROMPT_FILE_LINES = 500
# Headroom: `--budget` fails a prompt file above 90% of its ceiling and the always-on set above 95% of its own, so
# the next change has room to add text without squeezing what is there; the fix is a cut or a move to references/.
PROMPT_HEADROOM = 0.90
ALWAYS_HEADROOM = 0.95
ALWAYS_LOADED_PROJECT_FILES = ("AGENTS.md", ".claude/CLAUDE.md")
PROMPT_ROOTS = (".cursor/agents", ".cursor/skills")
# The default ref whose merge base with HEAD the `--budget` report measures prompt growth from (`--delta-base`
# overrides it); information only, never a finding.
DELTA_BASE = "origin/main"
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
        for target in re.findall(r"@(\S+\.mdc?)\b", candidate.read_text(errors="replace")):
            names.add(Path(target).stem + ".mdc")  # the claude-code adapter installs `rules/x.mdc` as `x.md`
    return names


def always_on_unreachable(root: Path, rule: str) -> str:
    """Why an `alwaysApply: true` rule never reaches Claude Code, or "" when it does.

    Cursor honours `alwaysApply`; Claude Code does not know the field and loads only `CLAUDE.md`
    plus its `@` imports. A rule marked always-on but not imported therefore applies in one harness
    and silently vanishes in the other, which is a behavior difference no other check can see.
    """
    if rule in claude_imports(root):
        return ""
    return f"alwaysApply is true but CLAUDE.md never imports it, so Claude Code does not load it; add `@~/.claude/el-capitan/{Path(rule).stem}.md` to {rel(root, root / '.claude/CLAUDE.md')}"


def always_on_files(root: Path) -> list[tuple[str, int]]:
    """Every file a request pays for, with its size in bytes, largest first."""
    rule_dir = root / "rules"
    cursor_payload = {rule.name for rule in rule_dir.glob("*.mdc") if re.search(r"alwaysApply:\s*true", rule.read_text(errors="replace"))}
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


def prompt_files(root: Path) -> list[Path]:
    """Every agent and skill Markdown file, references included."""
    found: list[Path] = []
    for pattern in PROMPT_ROOTS:
        found.extend(path for path in (root / pattern).rglob("*.md") if path.is_file())
    return sorted(found)


# What `prompt_byte_delta` measures: agent and skill Markdown, the rules, and the always-loaded project files.
DELTA_ROOTS = (*PROMPT_ROOTS, "rules", *ALWAYS_LOADED_PROJECT_FILES)


def is_prompt_path(name: str) -> bool:
    """A repository-relative path `prompt_byte_delta` counts."""
    if name in ALWAYS_LOADED_PROJECT_FILES:
        return True
    if name.startswith("rules/"):
        return name.count("/") == 1 and name.endswith(".mdc")
    return name.startswith(tuple(f"{prefix}/" for prefix in PROMPT_ROOTS)) and name.endswith(".md")


def prompt_byte_delta(root: Path, base: dict[str, int]) -> list[tuple[str, int]]:
    """(path, bytes now minus bytes in `base`) for each prompt file that differs; an added file counts from 0 and a
    removed one goes to 0. `base` maps paths to sizes at the base ref (`lib.git.tree_sizes` over `DELTA_ROOTS`)."""
    paths = [rel(root, path) for path in prompt_files(root)]
    paths += [rel(root, path) for path in (root / "rules").glob("*.mdc")] + list(ALWAYS_LOADED_PROJECT_FILES)
    current = {name: (root / name).stat().st_size for name in paths if (root / name).is_file()}
    measured = set(current) | {name for name in base if is_prompt_path(name)}
    deltas = [(name, current.get(name, 0) - base.get(name, 0)) for name in sorted(measured)]
    return [(name, delta) for name, delta in deltas if delta]


def headroom(size: float, ceiling: int, share: float) -> bool:
    """True when `size` is within its ceiling but above `share` of it, the band `prompt-headroom` reports."""
    return ceiling * share < size <= ceiling


def lint_budget(root: Path, all_files: list[Path], rules: set[str]) -> Findings:
    """The always-on token estimate, the per-file size caps with their headroom, and the duplicate-rule layout."""
    findings: Findings = []
    sizes = always_on_files(root)
    always = sum(size // 4 for _, size in sizes)
    largest, size = sizes[0] if sizes else ("rules", 0)
    if always > MAX_ALWAYS_RULE_TOKENS:
        findings.append(
            (largest, 1, "budget", f"always-on set estimates {always} tokens (>{MAX_ALWAYS_RULE_TOKENS}); largest contributor {largest} ({size} bytes)")
        )
    elif headroom(always, MAX_ALWAYS_RULE_TOKENS, ALWAYS_HEADROOM):
        findings.append(
            (
                largest,
                1,
                "prompt-headroom",
                f"headroom exceeded, fails --budget: always-on set estimates {always} tokens, above "
                f"{ALWAYS_HEADROOM:.0%} of {MAX_ALWAYS_RULE_TOKENS}; cut text or move it to a references/ file "
                f"(largest: {largest})",
            )
        )
    for path in all_files:
        name = rel(root, path)
        lines = path.read_text(errors="replace").count("\n") + 1
        if ("/agents/" in name or "/skills/" in name) and lines > MAX_PROMPT_FILE_LINES:
            findings.append((name, 1, "budget", f"{lines} lines (>{MAX_PROMPT_FILE_LINES})"))
    for path in prompt_files(root):
        size = path.stat().st_size
        if size > MAX_PROMPT_FILE_BYTES:
            findings.append(
                (
                    rel(root, path),
                    1,
                    "prompt-budget",
                    f"{size} bytes (>{MAX_PROMPT_FILE_BYTES}); move reference material into a references/ file read on demand",
                )
            )
        elif headroom(size, MAX_PROMPT_FILE_BYTES, PROMPT_HEADROOM):
            findings.append(
                (
                    rel(root, path),
                    1,
                    "prompt-headroom",
                    f"headroom exceeded, fails --budget: {size} bytes, above {PROMPT_HEADROOM:.0%} of {MAX_PROMPT_FILE_BYTES}; cut text or move it to a references/ file",
                )
            )
    for rule in rules:
        if (root / "rules" / rule).exists() and (root / ".cursor/rules" / rule).exists():
            findings.append((f"rules/{rule}", 1, "budget", "rule exists under rules and .cursor/rules"))
    return findings


# The source of truth for skills that may activate without an explicit `crew` command.
MODEL_INVOCABLE_SKILLS = {"crew-evals", "spec-writing", "prompt-authoring"}
# A dispatched agent's `tools:` line is an allowlist: its class's native tools, then the placeholder install
# fills with one `mcp__<server>__*` per server in `mcp` of ~/.agent/config.json (.claude/install_blocks.py).
# A deny list cannot keep out claude.ai connectors, plugin servers or tools the harness adds later; an
# allowlist names exactly what the agent reaches. Agents that inherit (the writer and the inline
# orchestrators) carry no `tools:` line, and no agent carries `disallowedTools`.
# A YAML comment, so the source line is a valid list of the native tools until install renders it.
MCP_PLACEHOLDER = "  # {{mcp_servers}}"
READONLY_AGENT_TOOLS = ("Read", "Grep", "Glob")
# crew-pr-resolver is told never to edit, push or post; Bash (kept for `gh` reads and probes) makes that an
# instruction, not a deny.
RESOLVER_AGENT_TOOLS = (*READONLY_AGENT_TOOLS, "Bash")
# reviewer-probe writes one throwaway artifact and runs it; with Bash, "no edit outlives the run" is likewise
# an instruction, not a deny.
PROBE_AGENT_TOOLS = (*READONLY_AGENT_TOOLS, "Write", "Bash")
# The agents outside the read-only class: (readonly: true expected, native tools, or None to inherit). The
# probe and the builder write, so `readonly` would block them; the orchestrators run inline (the router
# refuses to dispatch them), so `readonly`, a subagent-only field, never applies (None). Every other agent
# is (True, READONLY_AGENT_TOOLS).
AGENT_CLASSES: dict[str, tuple[bool | None, tuple[str, ...] | None]] = {
    "crew-pr-resolver": (True, RESOLVER_AGENT_TOOLS),
    "reviewer-probe": (False, PROBE_AGENT_TOOLS),
    "crew-builder": (False, None),
    "crew-reviewer": (None, None),
    "crew-specwriter": (None, None),
}
TOOLS_LINE = re.compile(r"^tools:[ \t]*(.*)$", re.MULTILINE)
# Every `reviewer-*` and `specwriter-*` agent (the review lenses and spec critics) declares its tool-call budget once
# (`tool_budget:`), says it in its text, and gets two turns past it, so the reply never competes with a tool call for
# the last turn. The exempt ones are not personas: explorers, the layer pre-pass and the probe set their own budgets.
BUDGETED_PREFIXES = ("reviewer-", "specwriter-")
BUDGET_EXEMPT = ("reviewer-explorer", "reviewer-layers", "reviewer-probe", "specwriter-explorer")
REPLY_TURNS = 2
STATED_BUDGET = re.compile(r"stop calling tools at (\d+)\b", re.IGNORECASE)
MANIFEST = "src/crew/tools.json"
MCP_REFERENCE = re.compile(r"mcp__([a-z0-9-]+)__([a-z0-9_]+)")


def kind(text: str) -> str:
    """The frontmatter finding's prefix: `missing` with no opening `---`, else `invalid`."""
    return "invalid" if text.startswith("---\n") else "missing"


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
        text = path.read_text(errors="replace")
        block, error = frontmatter_text(text)  # Cursor's rule frontmatter is not YAML (`globs: **/*.ts`)
        if block is None:
            findings.append((name, 1, f"{kind(text)}-rule-frontmatter", error))
            continue
        if not re.search(r"^description:\s*\S", block, re.MULTILINE):
            findings.append((name, 1, "invalid-rule-frontmatter", "add description"))
        if not re.search(r"^alwaysApply:\s*(?:true|false)\s*$", block, re.MULTILINE):
            findings.append((name, 1, "invalid-rule-frontmatter", "set alwaysApply true or false"))
        if re.search(r"^alwaysApply:\s*true\s*$", block, re.MULTILINE):
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
        fields, error = frontmatter(text)
        if fields is None:
            findings.append((name, 1, "invalid-skill-frontmatter", error))
            continue
        for key in ("name", "description"):
            if not str(fields.get(key) or "").strip():
                findings.append((name, 1, "invalid-skill-frontmatter", f"add {key}"))
        if path.parent.name not in MODEL_INVOCABLE_SKILLS and fields.get("disable-model-invocation") is not True:
            findings.append((name, 1, "missing-disable-model-invocation", "set disable-model-invocation: true or add the skill to MODEL_INVOCABLE_SKILLS"))
    return findings


def expected_tools(native: tuple[str, ...]) -> str:
    """The exact `tools:` value of an allowlist class: its native tools, then the placeholder install fills."""
    return ", ".join(native) + MCP_PLACEHOLDER


def lint_agent_readonly(root: Path) -> Findings:
    """Each agent follows its class in AGENT_CLASSES (else the read-only class): `readonly: true` as the
    class says (Cursor), and in Claude Code either exactly its class's `tools:` line with the placeholder
    or, for an inheriting agent, none; no agent carries `disallowedTools`."""
    findings: Findings = []
    agent_dir = root / ".cursor/agents"
    if not agent_dir.is_dir():
        return findings
    for path in sorted(agent_dir.glob("*.md")):
        text = path.read_text(errors="replace")
        fields, error = frontmatter(text)
        if fields is None:
            findings.append((rel(root, path), 1, f"{kind(text)}-agent-frontmatter", error))
            continue
        name, block = rel(root, path), frontmatter_text(text)[0] or ""
        if fields.get("access") not in ACCESS:
            findings.append((name, 1, "agent-access", f"set access: to one of {', '.join(ACCESS)} (the class every harness adapter maps)"))
        readonly, native = AGENT_CLASSES.get(path.stem, (True, READONLY_AGENT_TOOLS))
        if readonly is False and fields.get("readonly") is True:
            findings.append((name, 1, "unexpected-readonly", f"{path.stem} writes, so readonly: true would block every edit"))
        elif readonly and fields.get("readonly") is not True:
            findings.append(
                (
                    name,
                    1,
                    "missing-readonly",
                    "set readonly: true, or give the agent a class in AGENT_CLASSES in lint_prompts.py "
                    "(READONLY_AGENT_TOOLS, RESOLVER_AGENT_TOOLS, PROBE_AGENT_TOOLS, or None to inherit) with a reason",
                )
            )
        tools_line = TOOLS_LINE.search(block)  # read as text: its `# {{mcp_servers}}` comment is part of the contract
        where = line_no(block, tools_line.start()) + 1 if tools_line else 1
        if native is None and tools_line:
            findings.append((name, where, "agents-inherit-tools", f"{path.stem} inherits the session's tools: drop the tools: line"))
        elif native is not None and (not tools_line or tools_line.group(1).strip() != expected_tools(native)):
            findings.append(
                (
                    name,
                    where,
                    "agents-inherit-tools",
                    f"set tools: {expected_tools(native)} (the class list in AGENT_CLASSES, then the placeholder install fills with the configured MCP servers)",
                )
            )
        if "disallowedTools" in fields:
            findings.append((name, 1, "agents-inherit-tools", "drop disallowedTools: the tools: allowlist decides what the agent reaches"))
    return findings


def lint_turn_budget(root: Path) -> Findings:
    """Each persona (`BUDGETED_PREFIXES`, less `BUDGET_EXEMPT`) declares `tool_budget: N` with `maxTurns` at least
    N + 2 and states "stop calling tools at N" once in its text; any agent that declares a budget gets both checks."""
    findings: Findings = []
    for path in sorted((root / ".cursor/agents").glob("*.md")):
        text = path.read_text(errors="replace")
        fields, _ = frontmatter(text)
        if fields is None:
            continue
        name, body = rel(root, path), text.split("\n---\n", 1)[1]
        calls, turns = fields.get("tool_budget"), fields.get("maxTurns")
        if not isinstance(calls, int):
            if path.stem.startswith(BUDGETED_PREFIXES) and path.stem not in BUDGET_EXEMPT:
                findings.append((name, 1, "persona-turn-budget", "declare tool_budget: N in the frontmatter"))
            continue
        if not isinstance(turns, int) or turns < calls + REPLY_TURNS:
            findings.append(
                (name, 1, "persona-turn-budget", f"set maxTurns to at least {calls + REPLY_TURNS} (tool_budget + {REPLY_TURNS}), so the reply has its own turn")
            )
        if STATED_BUDGET.findall(body) != [str(calls)]:
            findings.append((name, 1, "persona-turn-budget", f'say the budget once in the text: "stop calling tools at {calls}"'))
    return findings


def lint_native_tool_ids(root: Path, native: set[str]) -> Findings:
    """Each native id of an agent's `tools:` line and of every class list is in `native_tools`, so a typo fails."""
    findings: Findings = []
    for stem, (_, tools) in {"read-only class": (True, READONLY_AGENT_TOOLS), **AGENT_CLASSES}.items():
        findings += [
            ("src/crew/maintenance/lint_prompts.py", 1, "tool-id-unknown", f"{tool} ({stem} in AGENT_CLASSES) is not in native_tools")
            for tool in tools or ()
            if tool not in native
        ]
    for path in sorted((root / ".cursor/agents").glob("*.md")):
        text = path.read_text(errors="replace")
        block = frontmatter_text(text)[0] or ""
        match = TOOLS_LINE.search(block)
        for tool in match.group(1).split("#", 1)[0].split(",") if match else []:
            if tool.strip() and not tool.strip().startswith("mcp__") and tool.strip() not in native:
                findings.append((rel(root, path), line_no(block, match.start()) + 1, "tool-id-unknown", f"{tool.strip()} is not in native_tools of tools.json"))
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
        findings.append((MANIFEST, 1, "invalid-tool-catalog", "native_tools must be a list of tool names"))
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
                findings.append((rel(root, path), line_no(text, match.start()), "mcp-tool-unknown", f"{match.group(0)}: server {server} is not in mcp_servers"))
            elif tool not in servers[server]:
                findings.append(
                    (rel(root, path), line_no(text, match.start()), "mcp-tool-unknown", f"{match.group(0)}: {server} has no tool {tool} in mcp_servers")
                )
    return findings


def lint_tool_surface(root: Path, all_files: list[Path]) -> Findings:
    """The catalog check, then the MCP reference and native id checks; a malformed catalog suppresses both."""
    servers, native, findings = load_tool_surface(root)
    if findings:
        return findings
    return lint_mcp_references(root, all_files, servers) + lint_native_tool_ids(root, native)
