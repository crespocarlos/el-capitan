"""Claude Code plugin manifests read from a config dir: which installs provide which MCP servers, and where.

An install's servers come from its own manifest (`.mcp.json`, `plugin.json`, the marketplace entry); `enabledPlugins`
is layered over user, project and local settings. A file that is missing or unreadable counts as empty.
"""
from __future__ import annotations

import json
import os
from pathlib import Path


def read_object(path: Path) -> dict:
    """A JSON object file, or {} when it is absent, unreadable or not an object."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


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
