Assessment: request-changes — the mirror skips plugin-provided servers, so `plugin_codeindex_codeindex` is never copied. The "uninstall" half of the contract has no consumer, and the copies are written non-atomically into Claude's live state file.

1. [attention · 4] **`.claude/install_blocks.py:42`** — plugin-provided servers are never mirrored, so the code-search case is only partly solved
```python
for name in (n for n in names if n in servers):
```
`.agent/config.json` lists `plugin_codeindex_codeindex`. The `plugin_` prefix suggests a server supplied by an enabled plugin. Plugin servers are not defined under `mcpServers` in `~/.claude.json`, so the `n in servers` filter drops them without any output. The second config dir therefore still lacks the code-search plugin. The change statement lists it as a target, so the `~/.claude-work` text-search fallback is only partly fixed. Nothing tells the user that a configured name was skipped.
Fix: report each configured name that matched no scope as "not mirrored (plugin-provided or undefined)". Decide separately whether plugin enablement (`enabledPlugins` in settings) needs mirroring.

2. [attention · 4] **`.claude/install_blocks.py:50`** — `mcp_mirror` manifest entries have no uninstall consumer
```python
record("mcp_mirror", {"dir": str(directory), "scope": ..., "name": name})
```
The docstring says "each copy is recorded for uninstall". A grep of the working directory finds `record` and the `"mcp_mirror"` section only in this file. Nothing reads that section back, so uninstall will leave the copied servers, and their credentials, in the second dir's `.claude.json`. The manifest also records only the name. It does not record the copied value, so uninstall cannot tell an untouched copy from one the user has since edited. Deleting by name alone could then remove user changes.
Fix: add the uninstall handler in the same change. Store a hash of the copied definition in the entry and remove the entry only if it still matches.

3. [attention · 4] **`.claude/install_blocks.py:52`** — unconditional, non-atomic rewrite of a live state file
```python
path.write_text(json.dumps(target, indent=2) + "\n")
```
`.claude.json` is Claude Code's own state file (projects, history, auth). A running session on the second dir rewrites it often, so this read-modify-write can lose its updates. Reformatting also changes the file when nothing was copied, and the write creates `.claude.json` in dirs that had none. A malformed existing file raises in `json.loads` and aborts the install midway.
Fix: write only when something was copied. Write to a temp file in the same directory and `os.replace` it. Catch `JSONDecodeError`, skip that dir, and warn.

4. [attention · 3] **`.claude/install_blocks.py:47`** — "skip if the name exists" leaves stale copies and does not tell user-defined servers apart from earlier mirrors
```python
if name in into:
    continue
```
On re-install, a mirrored server whose source definition has changed (a rotated token or a new URL) is never refreshed, because the name is already present. The check also cannot distinguish a user-defined server from a copy install made earlier. The rule "never overwrite a user's server" therefore blocks the one case where overwriting is safe, which is an entry the manifest says install owns. The copies also duplicate any `env` or `headers` secrets into a second file.
Fix: consult the `mcp_mirror` manifest entries. Refresh an entry install recorded and still unchanged. Skip anything else.

5. [nit · 3] **`.claude/install_blocks.py:34`** — a missing source file crashes `mirror-mcp`
```python
source = json.loads((home / ".claude.json").read_text())
```
A missing `~/.claude.json` or `~/.agent/config.json` raises `FileNotFoundError`. `install.sh` runs this step last through `run`, so a user with no MCP configuration gets a traceback at the end of an otherwise successful install.
Fix: return `[]` when either file is absent.