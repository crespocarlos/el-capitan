Assessment: request-changes — the lint now demands a frontmatter shape that only 1 of the 10 read-only agents has, and the deny-list design fails open for any tool it doesn't name.

1. [blocking · 4] **`.agent/tools/maintenance/lint_prompts.py:33`** — lint fails on the 9 agents the diff doesn't migrate
```python
if TOOLS_LINE.search(text):
    findings.append((..., "agents-inherit-tools", "drop the tools: line so MCP is inherited"))
...
if listed != READONLY_AGENT_DENY:
```
`READONLY_AGENTS` lists 10 stems. The diff edits only `.cursor/agents/specwriter-scope.md`. A grep for `tools:` and `disallowedTools:` across the working directory's `*.md` files matches only that file. The old lint required `tools: Read, Grep, Glob` on every agent, so the other nine presumably still carry that line and have no `disallowedTools`. The new lint then reports two findings for each of them, which is 18 in total. This also leaves the intent unmet. Those nine reviewer and explorer agents still shut out the MCP servers the change was written to reach (`docs-internal`, `code-search`, and the rest in `.agent/config.json`). Reviewers are likely among the agents that actually run, so the blast radius is the reviewer fleet.
Fix: migrate all ten agent files in the same change, or confirm they were migrated elsewhere.

2. [attention · 4] **`.agent/tools/maintenance/lint_prompts.py:15`** — the deny-list fails open, and the lint locks that in
```python
READONLY_AGENT_DENY = ("Write", "Edit", ..., "mcp__github__*", "mcp__gitlab__*", "mcp__slack__*", ...)
```
The old design was an allowlist of three tools. Now a read-only agent inherits every tool the session has, minus the names listed. Any new session tool is writable by default, for example another MCP server, a differently named plugin server such as `mcp__plugin_*`, or a new native tool like a task or cron tool. The `mcp__*` patterns also cover only the named vendors. A "read-only" agent can then act outside the review without any lint failure, because the lint only checks that the list matches itself. The lint compares the list to a constant, so it cannot detect a missing entry.
Fix: invert the MCP part to an allowlist if the runtime supports `mcp__docs-internal__*`-style entries. Otherwise add a lint or test that enumerates the session's tools and fails on any that is neither on the read-only allowlist nor in the deny list.

3. [nit · 3] **`.agent/tools/maintenance/lint_prompts.py:12`** — the 19-entry list is duplicated verbatim into each agent file
The same list is hand-copied into the Python constant and, once migrated, into ten markdown files. Every change to it becomes an 11-file edit. It is kept in sync only by the lint, which does an exact tuple comparison, so reordering entries also fails. Compare as a set, or generate the frontmatter from the constant, so that adding one deny entry is a single edit.