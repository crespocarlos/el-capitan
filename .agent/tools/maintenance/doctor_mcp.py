"""`crew-doctor.py`'s MCP checks: the rendered read-only agents, and the docs and code-search servers per harness.

The server names come only from `mcp` in `~/.agent/config.json` (`install_blocks.mcp_server_names`, the reader
install renders with). A rendered agent that differs from what install would write now is a FAIL; a capability
missing from a harness is a WARN. Plugin and claude.ai connector servers are not checked.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from doctor_checks import RERUN, ROOT, Line, capped, config_dirs, install_blocks
from task_gc import shown as tilde

CAPABILITIES = (("docs", "docs server"), ("code_search", "code search"))
MCP_HOWTO = ('no mcp section in ~/.agent/config.json, so no MCP server is checked; add '
             '"mcp": {"docs": ["<server>"], "code_search": ["<server>"]} with your server names')
MCP_INVALID = "the mcp section of ~/.agent/config.json is not valid (see the config line), so no MCP server is checked"
UNCHECKED = "servers from plugins and claude.ai connectors are not checked"


def check_rendered_agents(home: Path, root: Path = ROOT) -> list[Line]:
    """Each templated agent in ~/.cursor/agents is a regular file equal to its source (the checkout it was rendered
    from) rendered with the config now; the SessionStart hook repairs a stale one, a missing one needs install."""
    blocks = install_blocks(root)
    servers, _ = blocks.mcp_server_names(home)
    stale = []
    templates = blocks.templated_agents(blocks.rendered_source(home, root))
    for path in templates:
        target = home / ".cursor" / "agents" / path.name
        if target.is_symlink() or not target.is_file():
            stale.append(f"{path.name} not rendered")
        elif target.read_text(encoding="utf-8") != blocks.render_agent(path.read_text(encoding="utf-8"), servers):
            stale.append(f"{path.name} stale")
    listed = ", ".join(servers) or "none"
    if stale:
        text = f"read-only agents differ from the checkout and mcp config (servers: {listed}): {capped(stale)}{RERUN}"
        return [Line("FAIL", "agents", text)]
    return [Line("ok", "agents", f"{len(templates)} read-only agents rendered with MCP servers: {listed}")]


def read_object(path: Path) -> dict:
    """A JSON object file, or {} when it is absent, unreadable or not an object."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def names_in(entry: dict, key: str) -> set[str]:
    """The names under `key`: the keys of an object (`mcpServers`) or the strings of a list (the approval lists)."""
    value = entry.get(key)
    if isinstance(value, dict):
        return set(value)
    return {name for name in value if isinstance(name, str)} if isinstance(value, list) else set()


def repo_root(cwd: Path) -> Path | None:
    """The nearest directory at or above `cwd` holding `.git`, without running git."""
    return next((path for path in (cwd, *cwd.parents) if (path / ".git").exists()), None)


def claude_files(home: Path, environ: dict[str, str]) -> list[tuple[Path, Path]]:
    """(config dir, its `.claude.json`) for each existing config dir: the recorded ones and `$CLAUDE_CONFIG_DIR`.

    The dir `$CLAUDE_CONFIG_DIR` names keeps its config inside it; ~/.claude, used without the variable, keeps it
    in ~/.claude.json.
    """
    named = environ.get("CLAUDE_CONFIG_DIR", "")
    dirs = config_dirs(home) + ([Path(os.path.expanduser(named))] if named else [])
    found: dict[str, Path] = {}
    for directory in dirs:
        if directory.is_dir():
            found.setdefault(os.path.realpath(directory), directory)
    chosen = os.path.realpath(os.path.expanduser(named)) if named else None
    default = os.path.realpath(home / ".claude")
    return [(directory, home / ".claude.json" if real == default and real != chosen else directory / ".claude.json")
            for real, directory in found.items()]


def available(config: dict, settings: dict, repo: Path | None) -> tuple[set[str], dict[str, set[str]]]:
    """The user-level servers, and per project the servers it can reach: user ones it did not disable, its own, and
    the repo `.mcp.json` ones that are approved (by name, or all) and not disabled."""
    user, projects = names_in(config, "mcpServers"), config.get("projects")
    pairs = projects.items() if isinstance(projects, dict) else []
    entries = {key: value for key, value in pairs if isinstance(value, dict)}
    if repo:
        entries.setdefault(str(repo), {})
    shared = names_in(read_object(repo / ".mcp.json"), "mcpServers") if repo else set()
    reach = {}
    for project, entry in entries.items():
        approve_all = True in (entry.get("enableAllProjectMcpServers"), settings.get("enableAllProjectMcpServers"))
        approved = shared if approve_all else shared & (names_in(entry, "enabledMcpjsonServers")
                                                        | names_in(settings, "enabledMcpjsonServers"))
        approved = approved - names_in(entry, "disabledMcpjsonServers") if project == str(repo) else set()
        reach[project] = (user - names_in(entry, "disabledMcpServers")) | names_in(entry, "mcpServers") | approved
    return user, reach


def claude_capability(where: str, names: set[str], user: set[str], reach: dict[str, set[str]]) -> Line:
    """One capability in one config dir: ok when every project (or, with none, the user level) reaches a server."""
    missing = sorted(project for project, servers in reach.items() if not servers & names)
    if not missing and (reach or user & names):
        found = "at user level" if user & names else f"in every project ({len(reach)})"
        return Line("ok", "mcp", f"{where} {found}")
    gaps = f" for {len(missing)} of {len(reach)} projects: {capped(missing)}" if reach else ""
    return Line("WARN", "mcp", f"{where} missing{gaps}; add it at user level, enabled and approved")


def check_mcp(home: Path, wanted: dict[str, list[str]] | None, cwd: Path, environ: dict[str, str]) -> list[Line]:
    """The docs and code-search capabilities by the `mcp` config's server names, per harness; a gap is a WARN.

    `wanted` is None when the config is invalid: one note says so and nothing is checked.
    """
    if wanted is None:
        return [Line("note", "mcp", MCP_INVALID)]
    capabilities = [(label, set(wanted.get(key) or [])) for key, label in CAPABILITIES if wanted.get(key)]
    if not capabilities:
        return [Line("note", "mcp", MCP_HOWTO)]
    repo = repo_root(cwd)
    lines = []
    for directory, config_file in claude_files(home, environ):
        user, reach = available(read_object(config_file), read_object(directory / "settings.json"), repo)
        lines += [claude_capability(f"Claude Code {tilde(directory, home)}: {label} ({', '.join(sorted(names))})",
                                    names, user, reach) for label, names in capabilities]
    cursor = set().union(*(names_in(read_object(base / ".cursor" / "mcp.json"), "mcpServers")
                           for base in (home, repo) if base))
    sources = "~/.cursor/mcp.json" + (" or the repo's .cursor/mcp.json" if repo else "")
    lines += [Line("ok", "mcp", f"Cursor: {label} ({', '.join(sorted(cursor & names))})") if cursor & names
              else Line("WARN", "mcp", f"Cursor: {label} missing: none of {', '.join(sorted(names))} in {sources}")
              for label, names in capabilities]
    return [*lines, Line("note", "mcp", UNCHECKED)]
