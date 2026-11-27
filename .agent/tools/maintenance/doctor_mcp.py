"""`crew-doctor.py`'s MCP checks: the rendered read-only agents, and the docs and code-search servers per harness.

Server names come only from `mcp` in `~/.agent/config.json`. A rendered agent that differs from what install would
write now is a FAIL; a missing capability is a WARN naming the server and the place, never a setup step. A Claude
Code config dir is checked at user level, from its installed plugins, and for projects with crew work (a task's
`repo_remote_url` is the project's origin). claude.ai connectors are not checked.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

from doctor_checks import RERUN, ROOT, Line, capped, config_dirs, install_blocks
from task_gc import shown as tilde

from lib.git import slug_from_url

CAPABILITIES = (("docs", "docs server"), ("code_search", "code search"))
MCP_HOWTO = ('no mcp section in ~/.agent/config.json, so no MCP server is checked; add '
             '"mcp": {"docs": ["<server>"], "code_search": ["<server>"]} with your server names')
MCP_INVALID = "the mcp section of ~/.agent/config.json is not valid (see the config line), so no MCP server is checked"
UNCHECKED = "servers from claude.ai connectors are not checked"
NONE_IN_DIR = "no configured MCP servers in {}: crew agents in sessions on it use text search"


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


def crew_remotes(home: Path) -> set[str]:
    """The repository key (`repo_key`) of every task's `repo_remote_url` under ~/.agent/tasks."""
    return {repo_key(url) for path in (home / ".agent" / "tasks").glob("*/.task-id")
            if isinstance(url := read_object(path).get("repo_remote_url"), str)}


def repo_key(url: str) -> str:
    """One spelling per repository: `owner/repo` (lowercase) when the URL names one, so ssh, https, a `.git` suffix
    or a trailing slash compare equal; the URL itself otherwise."""
    return (slug_from_url(url) or url.strip()).lower()


def git_config(path: Path) -> list[tuple[str, str, str]]:
    """(section, key, value) rows of one git config file, the section as `name` or `name "sub"`; [] when unreadable."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []
    rows, section = [], ""
    for line in text.splitlines():
        if header := re.match(r'\s*\[\s*([\w.-]+)(?:\s+"((?:[^"\\]|\\.)*)")?\s*\]', line):
            name, sub = header.group(1).lower(), header.group(2)
            section = f'{name} "{sub}"' if sub is not None else name
        elif entry := re.match(r"\s*([\w-]+)\s*=\s*(.*?)\s*$", line):
            rows.append((section, entry.group(1).lower(), entry.group(2).strip('"')))
    return rows


def git_dir_of(project: Path) -> Path | None:
    """The git directory holding the config for `project` or its nearest parent with `.git`; a worktree's `.git`
    file is followed to the main repository through its `commondir`."""
    top = repo_root(project)
    if top is None:
        return None
    dot = top / ".git"
    if not dot.is_file():
        return dot
    try:
        pointer = re.match(r"gitdir:\s*(.+)", dot.read_text(encoding="utf-8"))
        git_dir = top / pointer.group(1).strip() if pointer else None
        if git_dir and (git_dir / "commondir").is_file():
            git_dir = git_dir / (git_dir / "commondir").read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return git_dir


def origin_url(project: Path, home: Path) -> str | None:
    """`remote.origin.url` as git would use it, read without running git: the repository's config, with the
    `url.<base>.insteadOf` rules of that config and the user's (`~/.gitconfig`, `~/.config/git/config`) applied."""
    git_dir = git_dir_of(project)
    rows = git_config(git_dir / "config") if git_dir else []
    urls = [value for section, key, value in rows if section == 'remote "origin"' and key == "url"]
    if not urls:
        return None
    rules = [(value, section[5:-1]) for config in (home / ".gitconfig", home / ".config" / "git" / "config")
             for section, key, value in git_config(config) + rows
             if section.startswith('url "') and key == "insteadof"]
    matches = [(prefix, base) for prefix, base in rules if urls[-1].startswith(prefix)]
    if not matches:
        return urls[-1]
    prefix, base = max(matches, key=lambda rule: len(rule[0]))
    return base + urls[-1][len(prefix):]


def manifest_servers(install_path: object, plugin: str) -> set[str] | None:
    """The server names a plugin install declares: its `.mcp.json`, the `mcpServers` of its `plugin.json`, or its
    entry in the marketplace manifest beside it; None when none of them is readable."""
    if not isinstance(install_path, str):
        return None
    base = Path(install_path)
    found, read = set(), False
    for candidate in (base / ".mcp.json", base / ".claude-plugin" / "plugin.json"):
        data = read_object(candidate)
        read = read or bool(data)
        servers = data.get("mcpServers", data if candidate.name == ".mcp.json" else {})
        if isinstance(servers, str):
            servers = read_object(base / servers).get("mcpServers", {})
        found |= set(servers) if isinstance(servers, dict) else set()
    market = read_object(base / ".claude-plugin" / "marketplace.json").get("plugins")
    for entry in market if isinstance(market, list) else []:
        if isinstance(entry, dict) and entry.get("name") == plugin and isinstance(entry.get("mcpServers"), dict):
            read, found = True, found | set(entry["mcpServers"])
    return found if read else None


def plugin_installs(directory: Path, names: set[str]) -> list[tuple[str, str | None, set[str]]]:
    """(plugin id, project path or None for user scope, the configured names it provides) per install in the dir's
    `plugins/installed_plugins.json`. The names come from the install's manifest; with none readable, a configured
    `plugin_<plugin>_<server>` goes to the installed plugin with the longest matching name."""
    installed = read_object(directory / "plugins" / "installed_plugins.json").get("plugins")
    pairs = [(plugin_id, install) for plugin_id, installs in (installed.items() if isinstance(installed, dict) else [])
             if isinstance(installs, list) for install in installs if isinstance(install, dict)]
    plugins = {plugin_id.split("@")[0] for plugin_id, _ in pairs}

    def by_prefix(plugin: str) -> set[str]:
        owners = {name: max((p for p in plugins if name.startswith(f"plugin_{p}_")), key=len, default=None)
                  for name in names}
        return {name for name, owner in owners.items() if owner == plugin}

    found = []
    for plugin_id, install in pairs:
        plugin = plugin_id.split("@")[0]
        declared = manifest_servers(install.get("installPath"), plugin)
        served = (names & {f"plugin_{plugin}_{server}" for server in declared} if declared is not None
                  else by_prefix(plugin))
        scope = None if install.get("scope") == "user" else install.get("projectPath")
        if served and (scope is None or isinstance(scope, str)):
            found.append((plugin_id, os.path.realpath(scope) if scope else None, served))
    return found


def enabled_plugins(settings: dict, project: Path | None) -> dict:
    """`enabledPlugins` for one place: the config dir's settings, overridden for a project by its
    `.claude/settings.json`, then its `.claude/settings.local.json`. A plugin absent from every one is enabled."""
    local = ("settings.json", "settings.local.json")
    layers = [settings] + ([read_object(project / ".claude" / name) for name in local] if project else [])
    merged: dict = {}
    for layer in layers:
        value = layer.get("enabledPlugins")
        merged.update(value if isinstance(value, dict) else {})
    return merged


def provided(installs: list[tuple[str, str | None, set[str]]], enabled: dict, project: str | None) -> set[str]:
    """The names the enabled installs provide at user level (`project` None) or in that project."""
    return set().union(*(served for plugin_id, scope, served in installs
                         if enabled.get(plugin_id) is not False and scope in (None, project)))


def available(config: dict, settings: dict, repo: Path | None, installs: list[tuple[str, str | None, set[str]]],
              home: Path) -> tuple[set[str], dict[str, set[str]]]:
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
        approved = shared if approve_all else shared & (names_in(entry, "enabledMcpjsonServers")
                                                        | names_in(settings, "enabledMcpjsonServers"))
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
    gaps = (f" for {len(missing)} of {len(reach)} projects with crew work: {capped(missing)}" if reach
            else " at user level")
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
        lines += [claude_capability(f"Claude Code {tilde(directory, home)}: {label} ({', '.join(sorted(names))})",
                                    names, user, reach) for label, names in capabilities]
    cursor = set().union(*(names_in(read_object(base / ".cursor" / "mcp.json"), "mcpServers")
                           for base in (home, repo) if base))
    sources = "~/.cursor/mcp.json" + (" or the repo's .cursor/mcp.json" if repo else "")
    lines += [Line("ok", "mcp", f"Cursor: {label} ({', '.join(sorted(cursor & names))})") if cursor & names
              else Line("WARN", "mcp", f"Cursor: {label} missing: none of {', '.join(sorted(names))} in {sources}")
              for label, names in capabilities]
    return [*lines, Line("note", "mcp", UNCHECKED)]
