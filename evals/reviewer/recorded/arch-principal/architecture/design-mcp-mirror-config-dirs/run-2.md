Assessment: request-changes — the mirror copies server definitions into files Claude Code owns, nothing reads the manifest entries it writes, and the plugin-provided code-search server in the config cannot be copied this way.

Read beyond the package: `.claude/install_blocks.py` (full file), `.agent/config.json`, and a grep for `mcp_mirror`, `uninstall` and `MANIFEST` across the working directory.

Approach: redirect — copying live definitions into another app's state file creates a second owner of each server and a rollback nobody has written. Registering through the supported CLI, and handling plugins separately, avoids both.
Alternatives considered:
- Don't build it: make the second dir's agents render with text-search fallback, and print a one-line notice naming the servers that dir lacks. This is cheapest, but it leaves the owner's stated gap (no MCP in `~/.claude-work`) open, so it loses on the goal.
- Register through the CLI: run `CLAUDE_CONFIG_DIR=<dir> claude mcp add-json -s user <name> '<json>'` per missing server. The CLI owns the file format, locking and scope handling, so it beats hand-editing `.claude.json`. The manifest entry would hold the same fields and the undo would be `claude mcp remove`. This is the recommended approach.
- Mirror by editing JSON directly (chosen): it has no dependency on the CLI, but it writes a file the app rewrites constantly and it duplicates definitions that can drift.

Next changes and their cost:
- **Add a server to `config.json`:** nothing mirrors it until install is re-run, and a changed definition is never updated, because `if name in into: continue` skips it.
- **Add uninstall:** it must parse `scope` strings and invert the walk, and no reader exists yet.
- **Add a third config dir:** this works, but every run rewrites every `.claude.json`.

1. [blocking · 4] **`.claude/install_blocks.py:50`** — `mcp_mirror` is written to the manifest but nothing reads it
```python
record("mcp_mirror", {"dir": str(directory), "scope": "/".join(keys) or "user", "name": name})
```
The docstring says each copy is "recorded for uninstall". A grep of the working directory finds no consumer of `mcp_mirror` and no uninstall code. The `scope` encoding is also lossy: `"projects/" + "/Users/a/b"` cannot be split back into keys, because project paths contain `/`. After install, the copied servers (some may carry tokens in `env`) stay in the second dir's `.claude.json` and nothing removes them. The manifest claims a rollback that does not exist.
Fix: Ship the uninstall that reads `mcp_mirror` in the same change, or don't record. Store `scope` as a structured value (`{"user": true}` or `{"project": path}`), and prefer `claude mcp remove` for the undo.

2. [blocking · 4] **`.claude/install_blocks.py:52`** — read-modify-write of a live `.claude.json`, and the write is unconditional
```python
target = json.loads(path.read_text()) if path.is_file() else {}
...
path.write_text(json.dumps(target, indent=2) + "\n")
```
Claude Code keeps rewriting this file (history, OAuth, project state). If a session on `~/.claude-work` is open during install, it can overwrite the mirrored servers, or the install can overwrite the session's newer state. A non-atomic write also leaves a truncated file if the process dies mid-write. The write runs even when nothing was copied, so every install rewrites and reformats every other dir's file. A corrupt existing file raises and aborts install partway.
Fix: Register through the CLI (see the alternatives). If keeping JSON editing, write only when something changed, write atomically (temp file plus `os.replace`), and catch `JSONDecodeError` per dir.

3. [attention · 4] **`.claude/install_blocks.py:27`** — plugin-provided servers are in the configured list but cannot be mirrored
```python
return [*mcp.get("docs", []), *mcp.get("code_search", [])]
```
`config.json` names `plugin_codeindex_codeindex`. That name is a plugin server, not an `mcpServers` entry. The plugin is enabled through `enabledPlugins` and the plugin cache, so `if n in servers` never matches it and it is skipped without a message. The second dir still falls back to text search for code search, which is the main case the change was meant to fix. The output prints only what was copied, so install looks successful.
Fix: Report every configured name that was not mirrored (not found in the source, or provided by a plugin). Handle plugins by enabling the plugin in the other dir's settings, or document them as out of scope.

4. [attention · 3] **`.claude/install_blocks.py:34`** — missing inputs crash the install step
```python
source = json.loads((home / ".claude.json").read_text())
```
`configured_servers` reads `config.json` the same way. A fresh machine with no `~/.claude.json`, or no `~/.agent/config.json`, raises `FileNotFoundError` from a step that is meant to be optional. If `install.sh` runs under `set -e`, that aborts the whole install after the agents have been rendered.
Fix: Return an empty list when either file is absent, and print which servers were skipped.

5. [attention · 3] **`.claude/install_blocks.py:47`** — a changed definition is never updated, and a user server of the same name is silently kept
```python
if name in into:
    continue
```
Keeping a user's own definition is correct. The skip also covers entries that install itself wrote earlier, so they are never refreshed after the source changes. The skip is never reported either. The copy and the original drift, and the agents' `tools:` lists then name tools the second dir's server may not provide.
Fix: Compare the existing entry with the source, and report "kept existing" or "differs" for each name. Refresh only entries that the manifest shows install created.