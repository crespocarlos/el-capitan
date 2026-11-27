Assessment: request-changes — the problem is real, but copying credential-bearing server definitions between separate config dirs is the wrong mechanism. It also silently skips the plugin-provided code-search server, so it does not fully solve the stated problem.

Read beyond the package: none (the working directory held only `.claude/install_blocks.py` and `.agent/config.json`; a grep for `mcp_mirror`, `manifest` and `.claude.json` found no uninstall code)

Approach: redirect — Register the servers through Claude's own CLI, `CLAUDE_CONFIG_DIR=<dir> claude mcp add-json`, and ask before copying anything. Do not hand-edit another account's `.claude.json`.
Alternatives considered:
- Don't build it, and keep the text-search fallback. This costs little and breaks nothing. The missing code search is a real loss, though, so I would offer mirroring as an opt-in step instead of doing it by default.
- Register through the CLI per config dir, with `CLAUDE_CONFIG_DIR=<dir> claude mcp add-json <name> '<json>' --scope user`. Claude owns the file format and its locking, so this wins. It also leaves no hand-written JSON merge, and a `claude mcp remove` could serve as the uninstall path.
- A shared `.mcp.json` or plugin install in each project. This avoids touching the account-level file, but it does not cover the user scope, so it only partly reaches the goal.
- Copy the files directly, as the diff does. It is the smallest code, but it has the problems below.

Next changes and what they cost:
- Updating a server after it changes in `~/.claude.json`: the mirror never refreshes a copy, so the copies drift. Updating needs a "managed by install" marker, or a comparison against the recorded manifest entries.
- Adding another config dir, or a server type such as a plugin: the plugin case needs a new code path.
- Uninstall: it must now learn the `mcp_mirror` section.

1. [attention · 4] **`.claude/install_blocks.py:42`** — Plugin-provided servers are never mirrored, so the code-search goal is silently missed
```
for name in (n for n in names if n in servers):
```
`configured_servers` returns `plugin_codeindex_codeindex` alongside `code-search`. A name that starts with `plugin_` is supplied by an enabled plugin, not by an entry in `mcpServers`. It never appears in `servers`, so the filter skips it with no output. The second config dir still has no code search, and the install reports success.
Fix: handle plugin servers separately, either by enabling the plugin in the other dir or by printing "not mirrored: <name>" for every configured name that was not found.

2. [attention · 4] **`.claude/install_blocks.py:49`** — Credentials and the account boundary are crossed without consent
```
into[name] = servers[name]
```
MCP definitions carry `env` tokens, `headers` and API keys. A separate `~/.claude-work` dir usually exists to keep a work account apart from a personal one. Running install copies the personal secrets and endpoints into the work dir, and does the reverse when the work dir is the source. Nothing is printed beforehand and there is no opt-out. Rewriting the file also leaves those secrets in a second place that uninstall may not clean.
Fix: make mirroring opt-in with a per-dir confirmation or a flag, list what will be copied, and prefer `claude mcp add-json` so Claude handles storage.

3. [attention · 4] **`.claude/install_blocks.py:52`** — Whole-file rewrite of a live, Claude-owned file
```
path.write_text(json.dumps(target, indent=2) + "\n")
```
`.claude.json` holds the session state, history, project trust and OAuth data, and a running Claude session rewrites it often. Read-modify-write without a lock can lose a concurrent update from that session. The write also happens for every dir, even when nothing was copied. A dir whose `.claude.json` does not exist yet raises `FileNotFoundError`, or gets a fresh file that contains only `mcpServers`.
Fix: skip the write when nothing changed, write atomically with a temp file and rename, and ideally use the CLI instead. Create the directory if it is missing, or skip it.

4. [attention · 3] **`.claude/install_blocks.py:50`** — Manifest records are written but have no consumer, and a crash leaves them inconsistent
```
record("mcp_mirror", {"dir": str(directory), "scope": "/".join(keys) or "user", "name": name})
```
I found no uninstall code that reads `mcp_mirror`. If one exists outside this package, it would not know the new section. `record` also commits to the manifest before `path.write_text` succeeds. A failure between the two leaves a record for a server that was never written, or the reverse. Uninstall would then remove a server the user defined themselves, because the scope entry names only the server, not whether install created it.
Fix: update uninstall to remove only recorded `(dir, scope, name)` entries, and call `record` after the file is written.

5. [nit · 3] **`.claude/install_blocks.py:34`** — A missing `~/.claude.json` or `config.json` aborts the install
```
source = json.loads((home / ".claude.json").read_text())
```
Reading either file when it is absent raises an uncaught exception, so a fresh machine or an owner with no `mcp` block fails the whole install. Failure here costs the rest of the install steps after `run`.
Fix: return early with an empty list when either file is missing or `names` is empty.