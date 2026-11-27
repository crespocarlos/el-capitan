Assessment: request-changes — the deny-list is open by default, so any write-capable tool not named in it is inherited. The change also migrates only one of the ten agents the lint checks.

Read beyond the package: `.agent/config.json`, and a grep for `tools:`/`disallowedTools:` across the working directory.

Approach: redirect — keep the goal of MCP access, but use an allowlist (`Read, Grep, Glob` plus the MCP servers named in `.agent/config.json`) instead of inheriting everything minus a deny-list.
Alternatives considered:
- Allowlist in `tools:` with MCP patterns (`Read, Grep, Glob, mcp__docs-internal__*, …`) — the premise "an explicit `tools:` list shuts out every MCP server" is only true for servers you leave out. Listing them re-admits them, and unknown tools stay closed. This is the safer default and wins, with one condition: I did not test that Claude Code accepts the `mcp__server__*` pattern in `tools:`. That should be checked first, and if it is rejected the deny-list is the fallback.
- Keep `tools: Read, Grep, Glob` (don't build it) — loses the docs and code-search access that the change exists to provide.
- Chosen: inherit minus deny-list — it gives MCP access, but every new write-capable tool is silently granted to the "read-only" agents.

Price of next changes: adding a tool to the session, such as a new MCP server or a new built-in like `TaskCreate` or `WebFetch`, means a security decision is made implicitly in the agents' favour. Someone must remember to extend `READONLY_AGENT_DENY` and then edit ten frontmatter lines by hand. Under an allowlist, a new server is added in one place and everything else stays denied.

1. [blocking · 4] **`.agent/tools/maintenance/lint_prompts.py:15`** — deny-list defaults to open for a read-only guarantee
```
READONLY_AGENT_DENY = ("Write", "Edit", "NotebookEdit", "Bash", "Agent", ...
                       "mcp__github__*", "mcp__gitlab__*", "mcp__slack__*", ...
```
   A session with an MCP server not on this list (for example `mcp__elastic__*`, `mcp__jenkins__*` or a deploy server) gives every reviewer and spec critic that server's write tools. The same applies to any new built-in tool. The list only blocks the names someone thought of in advance. It also leaves other outward-reaching built-ins open, such as `WebFetch` and `WebSearch`. Reviewers read untrusted diffs, so prompt injection is the realistic path to misuse.
   Fix: switch to an allowlist built from `.agent/config.json` `mcp.docs` and `mcp.code_search`, for example `tools: Read, Grep, Glob, mcp__<server>__*`. Note that the `plugin_codeindex_codeindex` server probably appears as `mcp__plugin_codeindex_codeindex__*`. Have the lint derive the expected line from the config.

2. [blocking · 4] **`.cursor/agents/specwriter-scope.md:5`** — only 1 of 10 agents is migrated, so the new lint fails on the rest
```
disallowedTools: Write, Edit, NotebookEdit, Bash, ...
```
   The diff touches only `specwriter-scope.md`. The grep of the working directory shows no other agent file with a `disallowedTools:` line. If the other nine still carry `tools: Read, Grep, Glob`, `lint_readonly_tools` reports two `agents-inherit-tools` findings for each of them. Those nine also still have no MCP access, so the stated goal is not met for them. The working directory holds only the changed files, so I could not read the other nine.
   Fix: migrate all ten `READONLY_AGENTS` in the same change, or confirm they were updated outside this diff.

3. [attention · 4] **`.agent/tools/maintenance/lint_prompts.py:16`** — the same list is kept in two places, in code and in ten frontmatters
```
READONLY_AGENT_DENY = (...)   # and a hand-copied "disallowedTools: ..." line in every agent
```
   The lint enforces equality, so any edit to the list means ten file edits, and the lint fails until all of them are done. The server names in `.agent/config.json` are a third owner of related facts: nothing ties the deny entries to the servers the owner actually configured.
   Fix: have the lint generate the expected line, and offer a `--fix` mode that rewrites it. Better still, move to the allowlist in finding 1, where the config is the single source.

4. [attention · 3] **`.agent/tools/maintenance/lint_prompts.py:33`** — the harness assumption is not checked
```
if TOOLS_LINE.search(text): ... "drop the tools: line so MCP is inherited"
```
   The `.cursor/agents` files keep `readonly: true`, which is the only restriction Cursor reads, and `disallowedTools` is a Claude Code key. Under Cursor, dropping `tools:` and denying nothing relies entirely on `readonly`. Nothing in the lint or its docs says the guarantee differs per harness.
   Fix: state the per-harness guarantee in the lint docstring and keep `readonly: true` under test. If Cursor ignores `disallowedTools`, say so.