Assessment: request-changes — the mirror only copies `mcpServers` entries from `~/.claude.json`, so the code-search plugin the change is meant to reach is probably never copied, and the manifest scope format can't be reversed.

1. [attention · 3] **`.claude/install_blocks.py:42`** (no hunk index) — plugin-provided servers are not in `mcpServers`, so they are silently skipped
```python
for name in (n for n in names if n in servers):
```
`.agent/config.json` lists `plugin_codeindex_codeindex`. The `plugin_<plugin>_<server>` naming suggests it comes from an installed plugin, not from an `mcpServers` entry. If so, it never appears in `servers`, and the filter drops it with no message. The change names "a code-search plugin" as part of the problem. The second config dir would therefore still fall back to text search for that server, while the install output reports success. This assumes plugin servers are absent from `~/.claude.json` `mcpServers`, which I couldn't check.
Fix: Decide how plugin servers reach a second dir, for example by enabling the plugin in that dir's settings. At minimum, print a warning for each configured name that was not found at any scope.

2. [attention · 4] **`.claude/install_blocks.py:50`** (no hunk index) — the manifest scope string is lossy, so uninstall can't reverse project-scoped copies
```python
record("mcp_mirror", {"dir": str(directory), "scope": "/".join(keys) or "user", "name": name})
```
Project keys are absolute paths such as `/Users/x/proj`. Joining gives `projects//Users/x/proj`, which can't be split back into `("projects", "/Users/x/proj")` when the path contains `/`. A project literally named `user` also collides with the user-level scope. The change says each copy is recorded "for uninstall", and this format defeats that.
Fix: Record the scope as structured data, for example `"scope": list(keys)`, or `{"project": project}` / `"user"`.

3. [attention · 4] **`.claude/install_blocks.py:52`** (no hunk index) — the target file is rewritten even when nothing was copied, and a missing source crashes the install
```python
path.write_text(json.dumps(target, indent=2) + "\n")
```
This write runs unconditionally for every other config dir. It reformats a live `.claude.json` that Claude Code rewrites itself, which risks losing a concurrent write. It also creates the file in dirs where nothing changed. `~/.claude.json` and `~/.agent/config.json` are read with no existence check, so a missing file raises and aborts `install.sh`. This new step is the last line of the script, so the rest of the install has already finished by then.
Fix: Write only when `target` changed. Write atomically through a temp file and `os.replace`. Return `[]` when either source file is missing.

4. [needs more info · 2] **`.claude/install_blocks.py:49`** (no hunk index) — copied server definitions may contain secrets and are never refreshed
Server definitions often hold `env` tokens or auth headers. The copy puts them in a second file, and later changes to `~/.claude.json` are never synced because an existing name is skipped. Is a one-time snapshot intended? If not, a rotated token in `~/.claude.json` leaves `~/.claude-work` with a stale credential and silent auth failures. Also, `record` runs before the file write, so a failed write leaves the manifest listing copies that were never made.