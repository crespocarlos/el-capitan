Assessment: request-changes — Copying definitions between `.claude.json` files duplicates secrets and cannot cover the plugin server. It also writes live state files and records entries that uninstall can't reverse.

Read beyond the package: none (the three files in the working directory were all that existed).

Approach: redirect — Mirroring copies server definitions into files that Claude itself owns, which makes a second owner of those facts. Referencing one shared definition, or just reporting the gap, avoids that.
Alternatives considered:
- Don't mirror; detect and report. Install would compare the configured names against each other dir's `.claude.json` and print "dir X lacks servers …; run `claude mcp add`". This leaves the actual copy to the user. It loses on convenience, but it wins on safety, because it never touches live state or credentials and nothing needs an uninstall.
- Render per-config-dir tools lists. Install would emit, for each dir, only the MCP tools that dir can actually reach, so a dir without servers keeps the text-search fallback explicitly. This fixes the symptom (agents listing tools that aren't there) without copying anything. It loses on coverage, since the second dir still has no MCP.
- Use a shared `--mcp-config` file or a project-level `.mcp.json`. Every config dir would read the same definition from one file. This wins on the "fact with two owners" point and on drift. It needs a launcher change.
- Mirror as built. It gives the second dir working MCP. In exchange it creates duplicated copies that go stale and duplicated secrets, and it writes files owned by running sessions.

1. [blocking · 4] **`.claude/install_blocks.py:50`** — the manifest scope string can't be parsed back, and nothing in this change undoes the entries
```
record("mcp_mirror", {"dir": str(directory), "scope": "/".join(keys) or "user", "name": name})
```
A project scope is recorded as `projects//Users/me/repo`, because the project key is itself an absolute path. A user-level server named `projects` can't be told apart from a project-level one. I found no uninstall consumer for `mcp_mirror` in the files provided. The summary says each copy is recorded for uninstall, but no code removes it. Uninstall can't tell which entries were installed and which the user later edited, so it either leaves the copies behind or deletes the wrong ones.
Fix: record `keys` as a JSON list, for example `{"scope": ["projects", path]}`. Add the uninstall step in the same change. It should delete the entry only if it still equals the recorded definition, so store a hash or the definition.

2. [attention · 4] **`.claude/install_blocks.py:49`** — credentials are copied and go stale
```
into[name] = servers[name]
```
MCP definitions hold `env` tokens and `headers`. Each copy puts those secrets in another file, and nothing refreshes them. Rotating a token in `~/.claude.json` leaves the old one in `~/.claude-work`. Rerunning install doesn't fix it, because `if name in into: continue` skips the entry. The user's own entries and our earlier copies look the same, so install can't update its own copies.
Fix: use the manifest to tell our copies from the user's. Refresh an entry only if it matches what we recorded, and refuse to copy definitions that carry secrets unless the user opts in.

3. [attention · 4] **`.claude/install_blocks.py:52`** — the whole state file is rewritten unconditionally
```
path.write_text(json.dumps(target, indent=2) + "\n")
```
`.claude.json` is Claude's live state file. A running session on `~/.claude-work` can write it between this read and write, and the session's change is lost. The write also happens when nothing was copied, and it creates the file in a directory that may not exist, so `write_text` raises `FileNotFoundError` and install aborts partway. The same applies to a corrupt JSON file, which crashes at `json.loads`.
Fix: write only when something changed. Do it atomically (temp file plus `os.replace`). Skip missing directories and unparseable files with a warning.

4. [attention · 3] **`.claude/install_blocks.py:26`** — a plugin-provided server in `mcp.code_search` is never mirrored
```
return [*mcp.get("docs", []), *mcp.get("code_search", [])]
```
The config lists `plugin_codeindex_codeindex`, which is a plugin-provided server. A plugin server is enabled through plugin settings, not through `mcpServers` in `.claude.json`, so `n in servers` never matches it. The second dir still has no code search, which is the stated goal, and the install output says nothing about the skip.
Fix: print the names that were configured but not found in the source. For plugins, enable the plugin in the other dir's settings, or report that it needs enabling.

5. [attention · 3] **`.claude/install_blocks.py:34`** — the source file is required, and the render step is not tied to the mirror
```
source = json.loads((home / ".claude.json").read_text())
```
A missing `~/.claude.json` raises, and `run` makes the whole install fail. `render_readonly_agents` still writes MCP tools into the agents' `tools:` lists. For a second dir where mirroring was skipped, those agents list tools that don't exist there, so the fallback to text search that the summary describes is lost.
Fix: tolerate a missing source. Have the render step check which servers each dir actually has.