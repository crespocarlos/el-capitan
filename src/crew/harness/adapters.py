"""What every harness adapter shares: its manifest, the hook contract, and the harness-free sources it renders.

A harness is `harness/<id>.json` (its manifest: each capability with a value or a declared `fallback`) and
`harness/<id>.py` (its adapter: `render`, `normalize`, `encode`). The hook rules are harness-free: `contract.json`
in the hooks directory names each rule's canonical event, script, fail mode and timeout, and a rule reads one
normalised event on stdin. Only this package knows a harness's payloads, event names and config files.
"""

from __future__ import annotations

import importlib
import json
import re
from pathlib import Path
from types import ModuleType

HERE = Path(__file__).resolve().parent
IDS = tuple(sorted(path.stem for path in HERE.glob("*.json")))
# The version of the normalised event and the contract (`version`): crew-hook refuses a contract stamped otherwise.
VERSION = 1
# The one entry point every registration runs: a launcher in ~/.agent/bin, so a refactor that moves a rule file never
# strands an installed registration.
ENTRY = '"$HOME/.agent/bin/crew-hook.py"'
# A read-only agent's frontmatter `tools:` line ends with this YAML comment, so the source line is a valid list by
# itself; rendering replaces it with one `, mcp__<server>__*` per server in `mcp` of ~/.agent/config.json.
PLACEHOLDER_COMMENT = re.compile(r"[ \t]+#[ \t]*\{\{mcp_servers\}\}[ \t]*$")
TOOLS_LINE = re.compile(r"^tools:[ \t]*(.*)$", re.MULTILINE)  # the shape `lint_prompts.TOOLS_LINE` reads
SERVER_NAME = re.compile(r"[A-Za-z0-9_-]+")  # `task_gc.SERVER_NAME` is the same pattern
# The agents' sibling directories their relative links read.
AGENT_DIRS = ("references", "crew-reviewer", "crew-pr-resolver")
ACCESS = ("readonly", "probe", "worker", "inline")  # an agent's frontmatter `access:`, which `lint_prompts` checks


def manifest(harness: str) -> dict:
    return json.loads((HERE / f"{harness}.json").read_text(encoding="utf-8"))


def adapter(harness: str) -> ModuleType:
    return importlib.import_module(f"crew.harness.{harness.replace('-', '_')}")


def hooks_dir(checkout: Path | None = None) -> Path:
    """The hook rules: the checkout's when rendering, else the copy install wrote (`~/.agent/hooks`)."""
    return checkout / ".claude" / "hooks" if checkout else Path.home() / ".agent" / "hooks"


def contract(hooks: Path) -> dict:
    return json.loads((hooks / "contract.json").read_text(encoding="utf-8"))


def natives(spec: dict) -> list[str]:
    native = spec.get("native")
    return [native] if isinstance(native, str) else list(native or [])


def events_for(spec: dict, native: str, tool: str) -> list[str]:
    """The canonical events one native call serves: those mapped to `native` whose matcher accepts the tool."""
    found = []
    for event, mapped in spec["events"].items():
        matcher = mapped.get("matcher")
        if native in natives(mapped) and (not matcher or re.fullmatch(matcher, tool or "")):
            found.append(event)
    return found


def deny_rules(spec: dict, mode: str | None) -> bool:
    """Whether a deny rule holds in this mode: the demoted rules run in the dispatcher where it does not."""
    modes = spec["deny"]["modes"]
    return bool(modes.get(mode or "", modes["*"]))


def registrations(harness: str, hooks: Path) -> list[dict]:
    """One registration per native event (and matcher): the rules it serves, its fail mode and timeout.

    A registration fails closed when any of its rules does; its timeout covers the slowest canonical event it serves,
    whose rules run one after another, plus 5 s, so crew-hook answers before the harness stops it.
    """
    spec, rules = manifest(harness), contract(hooks)["rules"]
    found: dict[str, dict] = {}
    for event, mapped in spec["events"].items():
        served = [rule for rule in rules if rule["event"] == event]
        if not served:
            continue
        for native in natives(mapped):
            entry = found.setdefault(native, {"event": native, "matchers": [], "rules": [], "closed": False, "timeout": 0})
            entry["matchers"].append(mapped.get("matcher"))
            entry["rules"] += [rule["name"] for rule in served]
            entry["closed"] = entry["closed"] or any(rule["fail"] == "closed" for rule in served)
            entry["timeout"] = max(entry["timeout"], sum(rule["timeout"] for rule in served))
    for entry in found.values():
        matchers = entry.pop("matchers")
        entry["matcher"] = None if None in matchers else "|".join(dict.fromkeys("|".join(matchers).split("|")))
        entry["command"], entry["timeout"] = f"{ENTRY} {harness} {entry['event']}", entry["timeout"] + 5
    return list(found.values())


def rules(checkout: Path) -> list[Path]:
    return sorted((checkout / "rules").glob("*.mdc"))


def always_on(checkout: Path) -> list[str]:
    """The rule stems every session loads: `alwaysApply: true`."""
    return [path.stem for path in rules(checkout) if re.search(r"^alwaysApply:[ \t]*true[ \t]*$", path.read_text(encoding="utf-8"), re.M)]


def skills(checkout: Path) -> list[Path]:
    return sorted(path.parent for path in (checkout / ".cursor" / "skills").glob("*/SKILL.md"))


def agents(checkout: Path) -> list[Path]:
    return sorted((checkout / ".cursor" / "agents").glob("*.md"))


def access(agent: Path) -> str:
    """The agent's frontmatter `access:` class: `inline` (an orchestrator), `readonly`, `probe` or `worker`."""
    from crew.lib.markdown import frontmatter

    return str((frontmatter(agent.read_text(encoding="utf-8"))[0] or {}).get("access"))


def mcp_server_names(home: Path) -> tuple[list[str], str | None]:
    """The servers `~/.agent/config.json` names in `mcp.docs`, then `mcp.code_search`, each once; with a reason when
    the file is unreadable or invalid (then none)."""
    path = home / ".agent" / "config.json"
    if not path.exists():
        return [], None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        return [], f"cannot read {path}: {error}"
    section = data.get("mcp") if isinstance(data, dict) else None
    if section is None:
        return [], None
    names: list[str] = []
    for key in ("docs", "code_search"):
        value = section.get(key, []) if isinstance(section, dict) else None
        if not (isinstance(value, list) and all(isinstance(name, str) and SERVER_NAME.fullmatch(name) for name in value)):
            return [], f"{path}: mcp.{key} must be a list of MCP server names"
        names += [name for name in value if name not in names]
    return names, None


def placeholder_line(text: str) -> re.Match | None:
    """The frontmatter `tools:` line when it ends with the placeholder comment; the placeholder in prose is not one."""
    if not text.startswith("---\n"):
        return None
    end = text.find("\n---\n", 4)
    found = TOOLS_LINE.search(text, 4, end) if end > 0 else None
    return found if found and PLACEHOLDER_COMMENT.search(found.group(0)) else None


def render_agent(text: str, servers: list[str]) -> str:
    """The agent with its placeholder comment replaced by one `, mcp__<server>__*` per server (or removed)."""
    found = placeholder_line(text)
    if not found:
        return text
    line = PLACEHOLDER_COMMENT.sub("".join(f", mcp__{name}__*" for name in servers), found.group(0))
    return text[: found.start()] + line + text[found.end() :]


def agent_entries(checkout: Path, home: Path, directory: str) -> dict[str, tuple[str, str]]:
    """Each agent under `directory` (relative to HOME): a link, or a file rendered with the MCP servers when its
    `tools:` line carries the placeholder; the sibling directories its relative links read are linked beside it."""
    servers = mcp_server_names(home)[0]
    found: dict[str, tuple[str, str]] = {}
    for agent in agents(checkout):
        text = agent.read_text(encoding="utf-8")
        found[f"{directory}/{agent.name}"] = ("file", render_agent(text, servers)) if placeholder_line(text) else ("link", str(agent))
    for name in AGENT_DIRS:
        if (checkout / ".cursor" / "agents" / name).is_dir():
            found[f"{directory}/{name}"] = ("link", str(checkout / ".cursor" / "agents" / name))
    return found


def shared(checkout: Path) -> dict[str, tuple[str, str]]:
    """What every harness reads: the hook rules and their contract, copied into ~/.agent/hooks so they change only at
    install, with the registrations; the reference store every prompt reads by path (the agents' reference directories
    and the skills under ~/.cursor, which Cursor also loads natively)."""
    hooks, source = hooks_dir(checkout), checkout / ".cursor" / "agents"
    found = {
        f".agent/hooks/{path.relative_to(hooks)}": ("file", path.read_text(encoding="utf-8"))
        for path in sorted(hooks.rglob("*"))
        if path.is_file() and "fixtures" not in path.relative_to(hooks).parts and "__pycache__" not in path.parts
    }
    # The file guard's Status reader (stdlib only) beside it, so the copy needs no checkout.
    found[".agent/hooks/lib/task_status.py"] = ("file", (checkout / "src" / "crew" / "task" / "task_status.py").read_text(encoding="utf-8"))
    found.update({f".cursor/agents/{name}": ("link", str(source / name)) for name in AGENT_DIRS if (source / name).is_dir()})
    for skill in skills(checkout):
        found[f".cursor/skills/{skill.name}/SKILL.md"] = ("link", str(skill / "SKILL.md"))
        for reference in sorted((skill / "references").glob("*")) if (skill / "references").is_dir() else []:
            if reference.is_file():
                found[f".cursor/skills/{skill.name}/references/{reference.name}"] = ("link", str(reference))
    return found


def subagents_dirs(parent: object) -> list[Path]:
    """`subagents/` beside a conversation transcript, whether it is `<conv>/<conv>.jsonl` or `<conv>.jsonl`."""
    if not isinstance(parent, str) or not parent.strip():
        return []
    path = Path(parent)
    return list(dict.fromkeys([path.parent / "subagents", path.parent / path.stem / "subagents"]))


def transcript_places(own: object, parents: list[object], ids: list[str], conversations: list[object], projects: Path) -> tuple[list[str], list[str]]:
    """The named transcript candidates in order, and the `subagents/` folders a nonce scan may search: `own`, then
    `<id>.jsonl` in each folder beside a parent transcript or under `projects/*/agent-transcripts/<conversation>`."""
    named = [Path(own)] if isinstance(own, str) and own.strip() else []
    folders: list[Path] = [folder for parent in parents for folder in subagents_dirs(parent)]
    for conversation in conversations:
        if isinstance(conversation, str) and conversation.strip() and "/" not in conversation:
            folders.extend(projects.glob(f"*/agent-transcripts/{conversation}/subagents"))
    folders = list(dict.fromkeys(folders))
    named.extend(folder / f"{name}.jsonl" for folder in folders for name in ids)
    return [str(path) for path in dict.fromkeys(named)], [str(folder) for folder in folders]


def count(value: object) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0


def text(value: object) -> str:
    return value if isinstance(value, str) else ""
