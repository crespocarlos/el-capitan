Assessment: request-changes — the lint now requires the new frontmatter on all 10 read-only agents, but the diff migrates only `specwriter-scope`. The new deny-list design is also fail-open.

1. [blocking · 4] **`.agent/tools/maintenance/lint_prompts.py:33`** (h1) — lint fails for 9 of 10 agents because the diff migrates only one
```python
if TOOLS_LINE.search(text):
    findings.append((rel(root, path), 1, "agents-inherit-tools", "drop the tools: line so MCP is inherited"))
```
`READONLY_AGENTS` still lists 10 agents. The old lint required each of them to carry `tools: Read, Grep, Glob`, and the diff edits only `specwriter-scope.md`. The other nine (the `reviewer-*` agents, `specwriter-adversarial` and `specwriter-explorer`) will still have the `tools:` line and no `disallowedTools:`. Each fails both checks, and those nine agents still can't reach the MCP docs and code-search servers, so the change doesn't fix the problem it was written for. A Grep over the working directory finds `tools:` or `disallowedTools:` only in `specwriter-scope.md`. The other agent files aren't in the package, so I'm inferring their state from the old lint. If any are missing from the tree, `path.read_text` raises `FileNotFoundError` instead.
Fix: Apply the same frontmatter edit to all 10 agent files in this change. Alternatively, shrink `READONLY_AGENTS` to the migrated agents and migrate the rest in follow-ups.

2. [attention · 3] **`.agent/tools/maintenance/lint_prompts.py:14`** (h1) — the deny-list is fail-open for any MCP server not named in it
```python
"mcp__github__*", "mcp__gitlab__*", "mcp__slack__*", "mcp__linear__*", "mcp__jira__*",
"mcp__notion__*", "mcp__filesystem__*")
```
The old `tools: Read, Grep, Glob` was an allowlist, so a new tool was unreachable until someone granted it. The deny-list inverts that default. Any MCP server a session adds that isn't in this list (for example `mcp__postgres__*`, `mcp__sentry__*`, or a write-capable tool on the code-search server) is inherited by every "read-only" reviewer. The only coupling to what the owner actually configures is the hand-maintained list. `.agent/config.json` names the intended servers: `docs-internal`, `docs-public`, `plugin_codeindex_codeindex` and `code-search`. The allowlist is therefore small and known. Claude Code's `tools:` field may not accept `mcp__*` entries in the way this change needs, and I haven't confirmed that. If it doesn't, the deny-list is a reasonable fallback, but the gap should be stated.
Fix: If `tools:` can name MCP servers, use an allowlist, either `Read, Grep, Glob` plus `mcp__<docs/search server>__*` entries derived from `.agent/config.json`, or an allowlist in the lint. If not, add a lint check that flags any MCP server in the session config that is neither in the deny list nor in the `config.json` `mcp` section, and note the residual risk in the comment above `READONLY_AGENT_DENY`.