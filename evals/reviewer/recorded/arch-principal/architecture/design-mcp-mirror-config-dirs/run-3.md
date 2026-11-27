Assessment: request-changes — the change copies live, credential-bearing server definitions into other `.claude.json` files, a state file Claude Code owns, when a supported way to register servers per config dir exists.

Read beyond the package: none (the working directory holds only `.agent/config.json`, `install_blocks.py` and `install.sh`)

Approach: redirect — registering servers through the supported CLI, or making the agents degrade when a server is absent, avoids hand-editing and duplicating `.claude.json`.
Alternatives considered:
- Run `CLAUDE_CONFIG_DIR=<dir> claude mcp add-json -s user <name> '<json>'` per config dir. It wins because Claude Code owns the file's schema and locking. It costs the same code size and needs no raw JSON surgery. Uninstall becomes `claude mcp remove`.
- Render the `tools:` lists per config dir, and only list servers that dir actually has. It wins on the stated problem, because the agents' fallback to text search is a rendering problem and no credentials get copied. The cost is that the second dir still has no MCP servers.
- Don't build it and document the manual step. It loses, because the owner has to repeat it for every server and every dir.
- Symlink or include the servers file. It loses, because `.claude.json` mixes in per-dir session state and has no include mechanism.

1. [attention · 4] **`.claude/install_blocks.py:52`** — rewrites a Claude-owned state file unconditionally, with no lock
```
        path.write_text(json.dumps(target, indent=2) + "\n")
```
`.claude.json` holds history, project trust and OAuth state, and a running session on `~/.claude-work` rewrites it often. Install reads it, a session writes it, then install writes its stale copy back, so the session's changes are lost. The write also happens when nothing was copied, and it creates a `{}` file for a dir that had none.
Fix: write only when a server was added, and write atomically through a temp file and rename. Better, use `claude mcp add-json` under `CLAUDE_CONFIG_DIR`.

2. [attention · 4] **`.claude/install_blocks.py:49`** — copying definitions gives each server two owners and spreads secrets
```
                into[name] = servers[name]
```
A server definition holds `env` values and `headers` such as API tokens. The copy puts them in a second plaintext file. When the owner rotates a token or changes a URL in `~/.claude.json`, the copy goes stale. A rerun skips it at `if name in into`, so the mirrored dir keeps the old definition and fails to authenticate.
Fix: use the supported CLI, or record a hash of the copied definition and refresh the entry when it still matches the hash. State in the output that secrets are copied.

3. [attention · 3] **`.claude/install_blocks.py:50`** — the manifest scope string cannot be parsed back
```
record("mcp_mirror", {"dir": str(directory), "scope": "/".join(keys) or "user", "name": name})
```
A project scope is stored as `projects//Users/me/app`, where the project path itself contains slashes. Uninstall cannot split that back into keys. A project literally named `user` would also collide with the user-level scope. No uninstall consumer is in the package, so I could not check what it expects.
Fix: store `"keys": list(keys)` (`["projects", project]`, or `[]` for user level) and have uninstall read that.

4. [attention · 3] **`.claude/install_blocks.py:34`** — missing inputs abort the whole install
```
    source = json.loads((home / ".claude.json").read_text())
```
A missing `~/.claude.json` or `~/.agent/config.json` raises `FileNotFoundError`. A target file that is corrupt or mid-write raises `JSONDecodeError`. `install.sh` calls this through `run` as its last step, so under `set -e` the install fails after everything else has finished. Nothing in this step is needed for the rest of the install to work.
Fix: return early with a message when a source file is missing, and skip any target dir whose JSON cannot be parsed. Do not overwrite that file.

5. [needs more info · 2] **`install.sh:7`** — does `run` honour a dry-run or uninstall mode?
The Python step writes files itself. If `run` only echoes the command in dry-run mode, this is safe. If it ignores dry-run, a dry run edits other config dirs. Does uninstall also read `mcp_mirror`, and does it remove only entries whose content still matches what install wrote? Without that, uninstall either leaves the copies behind or deletes servers the user later edited.