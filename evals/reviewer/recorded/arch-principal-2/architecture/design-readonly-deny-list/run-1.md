Assessment: request-changes — the goal (reach the docs and code-search MCP servers) is right, but an open-ended deny list for "read-only" agents fails open. An allowlist built from `config.json` meets the goal and fails closed.

Read beyond the package: `.agent/config.json`, and a grep for `tools:` and `disallowedTools:` across the working directory.

Approach: redirect — keep the explicit `tools:` allowlist and add the MCP servers that `config.json` names, instead of inheriting everything and denying a guessed list.
Alternatives considered:
- Allowlist `tools: Read, Grep, Glob, mcp__docs-internal__*, mcp__docs-public__*, mcp__plugin_codeindex_codeindex__*, mcp__code-search__*`, generated from `config.json` `mcp`. This wins. Claude Code's `tools:` field accepts MCP tool names, so the claim that an explicit list shuts every server out looks wrong, and I could not verify it here. An allowlist fails closed, so a newly installed MCP server stays out of the agents until someone adds it.
- Keep the diff's inherit-and-deny design. It loses. The denylist names `github`, `gitlab`, `slack`, `linear`, `jira`, `notion` and `filesystem`. Any other server in a session (a `mcp__jenkins__*`, `mcp__postgres__*`, `mcp__aws__*`, a browser or a deploy tool) is inherited with write power. New built-in tools are inherited too. A reviewer that is meant to be read-only then depends on a list nobody can keep complete.
- Don't build it and leave `Read, Grep, Glob`. This leaves the stated need unmet: the agents cannot reach the docs and code-search servers.

Next changes and their cost:
- A new MCP server is added. Under the allowlist, one edit to `config.json`. Under the diff, every session is exposed until `READONLY_AGENT_DENY` is edited, and the same string is edited again in all 10 agent files.
- Claude Code adds a write-capable built-in tool. Under the diff, it is inherited silently.
- A new read-only agent is added. Each one needs a 600-character frontmatter line copied in, so a reader has to diff it by eye.

1. [attention · 4] **`.agent/tools/maintenance/lint_prompts.py:15`** — the deny list fails open for "read-only" agents
```
READONLY_AGENT_DENY = ("Write", "Edit", "NotebookEdit", "Bash", "Agent", ...
                       "mcp__github__*", "mcp__gitlab__*", "mcp__slack__*", "mcp__linear__*", "mcp__jira__*",
                       "mcp__notion__*", "mcp__filesystem__*")
```
A session has an MCP server not on the list, for example a database, cloud or deploy server. Every reviewer persona inherits its write tools, and the lint passes because it only compares the deny string. The read-only guarantee holds only for the servers someone remembered to name.
Fix: replace the deny list with an allowlist, `READONLY_AGENT_TOOLS = ("Read", "Grep", "Glob", + mcp__<name>__* for each name in config.json mcp)`. If inheritance is truly required, keep a deny of `mcp__*` plus an allow for the configured servers.

2. [attention · 3] **`.agent/tools/maintenance/lint_prompts.py:17`** — the MCP server names have two owners
```
"mcp__github__*", ... "mcp__filesystem__*")
```
`config.json` lists `docs-internal`, `docs-public`, `plugin_codeindex_codeindex` and `code-search` as the servers agents may use. The lint hardcodes a separate list of servers to block. The two lists share no input, so they cannot be checked against each other. A server added to one is invisible to the other. For example, the owner could name a server in `config.json` that already matches a denied glob such as `mcp__filesystem__*`. The agent is then denied a server the owner configured, and nothing flags it.
Fix: derive the MCP part of the agent tool list from `config.json` in the lint, and have the lint fail if a configured server collides with the denied globs.

3. [needs more info · 3] **`.agent/tools/maintenance/lint_prompts.py:28`** — the other nine read-only agents are not in the package
```
for stem in READONLY_AGENTS:
    path = root / ".cursor/agents" / f"{stem}.md"
    text = path.read_text(errors="replace")
```
Only `specwriter-scope.md` is in the working directory, and my grep found `disallowedTools:` only there. The other nine files are missing or unchanged. If they were not migrated, the lint fails with `agents-inherit-tools` for each. If they are missing, `read_text` raises `FileNotFoundError` and the lint crashes. Were the other nine agent files migrated in this change? If not, the lint is red for nine agents and the stated goal is not met for them.

4. [nit · 3] **`.cursor/agents/specwriter-scope.md:5`** — rollback and platform
The `tools:` to `disallowedTools:` swap is a one-line revert. But `disallowedTools` is a Claude Code key, and Cursor reads the same `.cursor/agents` directory. Cursor would ignore the key and rely only on `readonly: true`. The cost is that under Cursor the tool restriction is gone with no lint to notice.
Fix: add a note that Cursor enforces only `readonly: true`, or keep the allowlist, which both harnesses honour.