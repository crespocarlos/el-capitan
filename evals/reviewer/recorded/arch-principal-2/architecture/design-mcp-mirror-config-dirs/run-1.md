Assessment: request-changes — the mirror edits and copies secrets into another config dir's live `.claude.json`. That file belongs to Claude Code, and the stated need is only for agent `tools:` lists to resolve.
Read beyond the package: none (the package holds only the three changed files, which I read in full)

Approach: redirect — mirroring by copying credential-bearing definitions into a file Claude Code owns is the wrong layer. Ask the owner to register servers per dir with `claude mcp add`, or print the exact command for them.
Alternatives considered:
- Don't build it: tell the user to run `claude mcp add` under `CLAUDE_CONFIG_DIR=~/.claude-work`, and have install print that command when a recorded dir lacks a configured server. This leaves the copy step manual. It uses the supported write path, never touches secrets, and needs no manifest section or uninstall logic.
- Invoke `claude mcp add-json` with `CLAUDE_CONFIG_DIR` set for each other dir, taking the definition from the source. This automates the copy and lets the CLI own the file format, locking and scopes. It costs one subprocess per server and wins over the hand-rolled JSON merge.
- Make the render step tolerant: `render_readonly_agents` emits MCP tool names only when the dir has the server, and falls back to text search otherwise. The agents are linked into every dir, so a per-dir render would need separate files, which costs more.
- Chosen: direct JSON merge into `.claude.json`. It is the smallest code, but it hand-edits a live, undocumented-schema file and clones secrets.

1. [attention · 4] **`.claude/install_blocks.py:52`** — Unconditional rewrite of another config dir's live `.claude.json`
```
        path.write_text(json.dumps(target, indent=2) + "\n")
    return copied
```
Claude Code rewrites `.claude.json` constantly (history, project state, tokens). If a `~/.claude-work` session is open during install, it can overwrite the mirrored entries, or install can overwrite the session's newer state with the stale copy it read. The write also happens when nothing was copied. It rewrites the whole file, reformats it, and creates `{}` files in dirs that had none. A malformed target file raises, and the traceback is not handled.
Fix: write only when `copied` grew for that dir, and write atomically (temp file plus rename). Better, replace the merge with `claude mcp add-json` under `CLAUDE_CONFIG_DIR`.

2. [attention · 3] **`.claude/install_blocks.py:49`** — Secrets cloned into a second file, and the copies are never refreshed
```
                into[name] = servers[name]
```
Definitions often hold `env` tokens or auth `headers`. Each copy duplicates them into another file with no permission check. The `name in into: continue` guard also means a later change or rotation in `~/.claude.json` never reaches the copy. After a token rotation, the work dir keeps the stale credential and the servers fail with no signal. The manifest records the name but not the copied value, so uninstall cannot tell whether the entry is still the one install wrote.
Fix: record a hash of the copied definition in the manifest entry. On rerun, update entries whose current value still matches the recorded hash. Alternatively, drop copying and print the `claude mcp add` commands.

3. [attention · 3] **`.claude/install_blocks.py:26`** — Configured names that are not `mcpServers` entries are skipped silently
```
    return [*mcp.get("docs", []), *mcp.get("code_search", [])]
```
`.agent/config.json` lists `plugin_codeindex_codeindex`, which is provided by a plugin and has no `mcpServers` definition. The `n in servers` filter drops it silently. The second dir therefore still has no code search, and the agents' `tools:` lists reference a server that dir does not have. The goal, code search plus docs in the second dir, is only partly met. The install output also gives no sign of it.
Fix: report configured names that were not mirrored, with the reason (plugin-provided, or not defined), and tell the user to install the plugin in that dir.

4. [attention · 3] **`.claude/install_blocks.py:50`** — The new `mcp_mirror` manifest section has no visible consumer
```
                record("mcp_mirror", {"dir": str(directory), "scope": "/".join(keys) or "user", "name": name})
```
The docstring says "recorded for uninstall", but no uninstall code is in the package. The diff adds none, and I could not check for an existing uninstall elsewhere. If it ignores the new section, uninstall leaves credentialed servers behind in the work dir, so the manifest's "undo exactly what install did" promise breaks. The fact that `mcp.docs` and `mcp.code_search` are the server list is also now read in two places: `render_readonly_agents`, which I could not see, and `configured_servers`.
Fix: add the uninstall handler for `mcp_mirror` in the same change. It should remove an entry only if it still equals the recorded value. Have `render_readonly_agents` and `configured_servers` share one reader.

5. [nit · 3] **`.claude/install_blocks.py:34`** — A missing `~/.claude.json` aborts install
```
    source = json.loads((home / ".claude.json").read_text())
```
A user with only `~/.claude` and no `.claude.json`, or with no `.agent/config.json`, gets a `FileNotFoundError` traceback at the end of install, after the linking has already run. The cost is a half-failed install for a purely optional step.
Fix: return early with a one-line notice when either file is absent.