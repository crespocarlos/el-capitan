"""`crew-doctor.py`'s MCP checks: the docs and code-search servers per harness.

Server names come only from `mcp` in `~/.agent/config.json` (the rendered read-only agents are
`check_harness_files`'s). A missing capability is a WARN naming the server and the place, never a setup step. A Claude
Code config dir is checked at user level, from its plugins (`lib/claude_plugins.py`), and for projects with crew
work (a task's `repo_remote_url` is the origin `lib/git_config.py` reads). claude.ai connectors are not checked.
"""

from __future__ import annotations

import os
from pathlib import Path

from crew.lib.claude_plugins import enabled_plugins, plugin_installs, provided, read_object
from crew.lib.git import slug_from_url
from crew.lib.git_config import origin_url, repo_root
from crew.maintenance.doctor_checks import Line, capped, config_dirs
from crew.task.task_gc import shown as tilde

CAPABILITIES = (("docs", "docs server"), ("code_search", "code search"))
MCP_HOWTO = (
    'no mcp section in ~/.agent/config.json, so no MCP server is checked; add "mcp": {"docs": ["<server>"], "code_search": ["<server>"]} with your server names'
)
MCP_INVALID = "the mcp section of ~/.agent/config.json is not valid (see the config line), so no MCP server is checked"
UNCHECKED = "servers from claude.ai connectors are not checked"
NONE_IN_DIR = "no configured MCP servers in {}: crew agents in sessions on it use text search"


def names_in(entry: dict, key: str) -> set[str]:
    """The names under `key`: the keys of an object (`mcpServers`) or the strings of a list (the approval lists)."""
    value = entry.get(key)
    if isinstance(value, dict):
        return set(value)
    return {name for name in value if isinstance(name, str)} if isinstance(value, list) else set()


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
    return [(directory, home / ".claude.json" if real == default and real != chosen else directory / ".claude.json") for real, directory in found.items()]


def crew_remotes(home: Path) -> set[str]:
    """The repository key (`repo_key`) of every task's `repo_remote_url` under ~/.agent/tasks."""
    return {repo_key(url) for path in (home / ".agent" / "tasks").glob("*/.task-id") if isinstance(url := read_object(path).get("repo_remote_url"), str)}


def repo_key(url: str) -> str:
    """One spelling per repository: `owner/repo` (lowercase) when the URL names one, so ssh, https, a `.git` suffix
    or a trailing slash compare equal; the URL itself otherwise."""
    return (slug_from_url(url) or url.strip()).lower()


def available(
    config: dict, settings: dict, repo: Path | None, installs: list[tuple[str, str | None, set[str]]], home: Path
) -> tuple[set[str], dict[str, set[str]]]:
    """The user-level servers, and per project with crew work the servers it can reach: user ones it did not
    disable, its own, its enabled plugins', and the repo `.mcp.json` ones that are approved (by name, or all) and
    not disabled."""
    remotes, projects = crew_remotes(home), config.get("projects")
    user = names_in(config, "mcpServers") | provided(installs, enabled_plugins(settings, None), None)
    pairs = projects.items() if isinstance(projects, dict) else []
    entries = {key: value for key, value in pairs if isinstance(value, dict)}
    if repo:
        entries.setdefault(str(repo), {})
    shared = names_in(read_object(repo / ".mcp.json"), "mcpServers") if repo else set()
    reach = {}
    for project, entry in entries.items():
        url = origin_url(Path(project), home)
        if url is None or repo_key(url) not in remotes:
            continue
        approve_all = True in (entry.get("enableAllProjectMcpServers"), settings.get("enableAllProjectMcpServers"))
        approved = shared if approve_all else shared & (names_in(entry, "enabledMcpjsonServers") | names_in(settings, "enabledMcpjsonServers"))
        approved = approved - names_in(entry, "disabledMcpjsonServers") if project == str(repo) else set()
        enabled = enabled_plugins(settings, Path(project))
        plugged = provided(installs, enabled, None) | provided(installs, enabled, os.path.realpath(project))
        inherited = (names_in(config, "mcpServers") | plugged) - names_in(entry, "disabledMcpServers")
        reach[project] = inherited | names_in(entry, "mcpServers") | approved
    return user, reach


def claude_capability(where: str, names: set[str], user: set[str], reach: dict[str, set[str]]) -> Line:
    """One capability in one config dir: ok when every crew project (or, with none, the user level) reaches a
    server; otherwise a WARN naming the server and the projects that lack it."""
    missing = sorted(project for project, servers in reach.items() if not servers & names)
    if not missing and (reach or user & names):
        found = "at user level" if user & names else f"in every project ({len(reach)})"
        return Line("ok", "mcp", f"{where} {found}")
    gaps = f" for {len(missing)} of {len(reach)} projects with crew work: {capped(missing)}" if reach else " at user level"
    return Line("WARN", "mcp", f"{where} missing{gaps}")


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
    configured = set().union(*(names for _, names in capabilities))
    lines = []
    for index, (directory, config_file) in enumerate(claude_files(home, environ)):
        settings = read_object(directory / "settings.json")
        installs = plugin_installs(directory, configured)
        user, reach = available(read_object(config_file), settings, repo, installs, home)
        # The primary dir keeps its WARNs; an extra dir with nothing configured is a note.
        if index and not (user | set().union(*reach.values())) & configured:
            lines.append(Line("note", "mcp", NONE_IN_DIR.format(tilde(directory, home))))
            continue
        lines += [
            claude_capability(f"Claude Code {tilde(directory, home)}: {label} ({', '.join(sorted(names))})", names, user, reach)
            for label, names in capabilities
        ]
    cursor = set().union(*(names_in(read_object(base / ".cursor" / "mcp.json"), "mcpServers") for base in (home, repo) if base))
    sources = "~/.cursor/mcp.json" + (" or the repo's .cursor/mcp.json" if repo else "")
    lines += [
        Line("ok", "mcp", f"Cursor: {label} ({', '.join(sorted(cursor & names))})")
        if cursor & names
        else Line("WARN", "mcp", f"Cursor: {label} missing: none of {', '.join(sorted(names))} in {sources}")
        for label, names in capabilities
    ]
    return [*lines, Line("note", "mcp", UNCHECKED)]
