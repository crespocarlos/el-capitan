Assessment: request-changes — the change copies MCP server definitions, including any secrets, across config dirs that are deliberately isolated. It also misses the plugin-provided code-search server, and it writes a manifest section that nothing reads back.

Read beyond the package: `.claude/install_blocks.py` (full file), `.agent/config.json`, and a grep of the working directory for `mcp_mirror`, `record` and uninstall consumers.

Approach: redirect — mirroring rewrites another dir's `.claude.json` and crosses an isolation boundary. The better design is to leave those files alone and either make the second dir's server set an explicit opt-in or let the agents degrade gracefully.
Alternatives considered:
- Don't build it: the agents already fall back to text search when a server is missing. This leaves one need unmet, which is that the work session never gets the servers. It would be enough if the owner only wants the fallback to be reliable.
- Delegate to the CLI: run `CLAUDE_CONFIG_DIR=<dir> claude mcp add-json <name> '<json>' --scope user` for each server. The CLI owns the file format, locking and project scopes. It is a smaller change, with no hand-written JSON merge, and the install stays correct if the format changes. I would pick this one.
- Opt-in per dir: record in the manifest which dirs should receive which servers, for example `config_dirs` entries with `mirror_mcp: true`. This keeps the work/personal separation by default and is cheap to add.
- Mirroring as built: simple, but it silently copies credentials and rewrites a live, Claude-owned state file.

1. [blocking · 4] **`.claude/install_blocks.py:49`** — Server definitions are copied verbatim into other config dirs, including their secrets
```
into[name] = servers[name]
```
A second config dir such as `~/.claude-work` usually exists to keep accounts and credentials separate. An `env` or `headers` block in an MCP definition often holds API tokens. After install, the personal tokens for `docs-internal` sit in the work dir's `.claude.json`, and the work session can call personal-scoped servers. Nothing asks the owner first, and the install never says it did this beyond one printed line.
Fix: make mirroring opt-in per dir, and copy only definitions the owner has explicitly approved.

2. [blocking · 4] **`.claude/install_blocks.py:42`** — The plugin-provided server `plugin_codeindex_codeindex` is not mirrored, so the goal is only partly met
```
for name in (n for n in names if n in servers):
```
`.agent/config.json` lists `plugin_codeindex_codeindex`. The `plugin_` prefix suggests a plugin-provided server. Plugin servers are not in `mcpServers` in `.claude.json`. They come from an enabled plugin in `settings.json`. The membership test skips that name without any message. The work session still has no code search, and install reports success.
Fix: enable the plugin in the other dir's `settings.json` through the CLI (`claude plugin install`). Warn about any configured name that was not found in the source.

3. [attention · 4] **`.claude/install_blocks.py:50`** — `mcp_mirror` is recorded in the manifest, but nothing uninstalls it
```
record("mcp_mirror", {"dir": str(directory), "scope": ..., "name": name})
```
A search of the working directory found no uninstall code and no reader of `mcp_mirror`. The change claims each copy is "recorded for uninstall". The copies will therefore survive uninstall, including any secrets in them. The entry also stores no hash or definition of what was copied. If the user edits the copy later, uninstall cannot tell whether the entry is still the one install wrote.
Fix: add the uninstall reader in the same change. Record a hash of the copied definition, and remove an entry only when it still matches.

4. [attention · 4] **`.claude/install_blocks.py:52`** — Every other dir's `.claude.json` is rewritten wholesale, and a malformed file crashes the install
```
path.write_text(json.dumps(target, indent=2) + "\n")
```
`.claude.json` is Claude Code's live state file. It is rewritten while sessions run, and the write here is not atomic. The write also runs when nothing was copied. A concurrent Claude write between the read and the write is lost. Alternatively, a half-written file makes `json.loads` raise, and the install aborts partway through.
Fix: write only when `copied` is non-empty, use a temp file plus `os.replace`, and handle a parse error by skipping that dir with a warning. Better still, use the CLI as in alternative 2.

5. [attention · 3] **`.claude/install_blocks.py:34`** — A missing `~/.claude.json` or `~/.agent/config.json` crashes the install step
```
source = json.loads((home / ".claude.json").read_text())
```
A fresh machine, or one with no `mcp` section, raises `FileNotFoundError`. `install.sh` calls `run python3 ... mirror-mcp` after `render_readonly_agents`, so the failure surfaces as a failed install even when there are no second dirs to mirror to. `config_dirs` and `record` already use `is_file()` guards, so this breaks the established pattern.
Fix: return `[]` early when either file is missing or `names` or `config_dirs(home)[1:]` is empty.

6. [attention · 3] **`.claude/install_blocks.py:41`** — A project-scoped copy lands in a path the other dir may not use
```
scopes += [(("projects", project), entry.get("mcpServers", {})) ...]
```
Project keys are absolute paths. They are copied to every other dir regardless of whether that dir's sessions ever open those projects. This adds entries for projects that dir never uses, and each one carries a copy of the definition. The user-scope copy already covers the stated need.
Fix: mirror user scope only, or mirror project scope only for projects already present in the target.