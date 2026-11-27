Assessment: request-changes — the mirror copies from `~/.claude.json` only. A plugin-provided server such as `plugin_codeindex_codeindex` isn't defined there, so the stated problem is only partly solved. It also writes secrets into other dirs and is not idempotent or reversible.

1. [blocking · 4] **`.claude/install_blocks.py:34`** — Plugin-provided servers are not in `~/.claude.json`, so they are never mirrored
```
source = json.loads((home / ".claude.json").read_text())
scopes = [((), source.get("mcpServers", {}))]
```
The config names `plugin_codeindex_codeindex`, whose `plugin_` prefix marks a plugin-provided MCP server. Those servers come from the plugin's own manifest in `~/.claude/plugins`, not from `mcpServers` in `.claude.json`. The `n in servers` filter silently skips them, so the second dir still falls back to text search for code search. This is the case the change was written for. Separately, a missing `~/.claude.json` raises an uncaught exception that aborts the install after `render_readonly_agents`.
Fix: Decide whether plugins belong in scope. Either mirror the plugin enablement (`enabledPlugins` in the second dir's `settings.json`) or report a skipped-name warning. Guard the missing or invalid source file.

2. [blocking · 4] **`.claude/install_blocks.py:50`** — Nothing consumes the `mcp_mirror` records, and re-runs are not idempotent
```
record("mcp_mirror", {"dir": str(directory), "scope": ..., "name": name})
...
path.write_text(json.dumps(target, indent=2) + "\n")
```
The docstring promises "recorded for uninstall", but grep finds no uninstall code reading `mcp_mirror`. The records are therefore inert. The "skip if present" check cannot tell a server the user defined from one install copied earlier. After a re-run or an uninstall, ownership is lost. If uninstall later removes by name, it can delete a user-defined entry. If the user edits the mirrored copy, the data is stale and is never re-synced.
Fix: Write the uninstall counterpart in the same change. Record the copied value, or a hash of it, so uninstall removes only unmodified copies. De-duplicate records on re-run.

3. [attention · 4] **`.claude/install_blocks.py:52`** — Whole-file rewrite of a live `.claude.json`, and the file is written even when nothing changed
```
path.write_text(json.dumps(target, indent=2) + "\n")
```
`.claude.json` is Claude Code's volatile state file (history, projects, auth). It is rewritten non-atomically on every install, including when no server was added. This risks clobbering concurrent session writes and creating the file for dirs that don't have one. A malformed target file raises mid-loop, leaving earlier dirs mirrored and recorded but later dirs not.
Fix: Write only when something was added. Write to a temp file and `os.replace`. Handle `JSONDecodeError` per dir.

4. [attention · 3] **`.claude/install_blocks.py:49`** — Copies full server definitions, including secrets, to other dirs
```
into[name] = servers[name]
```
Server definitions carry `env` and `headers` values such as tokens. Copying them spreads credentials to additional files. Those dirs may be deliberately separate, for example a work account kept apart from a personal one. `~/.claude-work` suggests exactly that separation, and the change mirrors personal servers into it without asking. Project-scoped entries are also copied for paths that may not exist for the other account.
Fix: Make mirroring opt-in per dir. Print what will be copied. Consider limiting it to the user scope.

5. [nit · 3] **`.claude/install_blocks.py:42`** — The loop over scopes recomputes `into` for every name, and the data flow is nested deeply
The inner loop re-walks the key path for each name. Resolve the target scope once per `(keys, dir)` pair. The cost is readability, because the stale-copy and ownership bugs above are hard to see in this shape.
Fix: Hoist the `setdefault` walk out of the per-name loop, and only create the scope when at least one name is missing.