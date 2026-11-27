Assessment: request-changes — the change swaps a fail-closed allowlist for a fail-open denylist to gain MCP access, and an allowlist that names the MCP tools would do both.
Read beyond the package: `.agent/config.json`, a grep of `.cursor/agents` frontmatter, and a grep for other users of the lint symbols.

Approach: redirect — keep an explicit allowlist and add the configured read-only MCP servers to it, instead of inheriting every session tool and denying a hand-kept list.
Alternatives considered:
- Allowlist with MCP names (`tools: Read, Grep, Glob, mcp__docs-internal__*, mcp__docs-public__*, mcp__plugin_codeindex_codeindex__*, mcp__code-search__*`) — wins. It is fail-closed, and it is exactly the set `config.json` names, so a new write-capable MCP server is not reachable by default. It also puts back the guarantee the old lint held, "exactly these tools". I could not confirm from the package that Claude Code accepts `mcp__server__*` patterns in `tools:`, so that should be checked first.
- Keep the old `Read, Grep, Glob` list and do not build this — loses. It leaves the agents without the docs and code-search servers, which is the need.
- Denylist as built — loses. It works only while every dangerous tool is already on the list.

1. [blocking · 4] **`.agent/tools/maintenance/lint_prompts.py:16`** — fail-open denylist grants every unlisted tool to read-only agents
```
READONLY_AGENT_DENY = ("Write", "Edit", "NotebookEdit", "Bash", "Agent", ...
                       "mcp__github__*", "mcp__gitlab__*", "mcp__slack__*", ... "mcp__filesystem__*")
```
Read-only agents now inherit every session tool. A session with an MCP server not on the list (`mcp__elasticsearch__*`, `mcp__aws__*`, `mcp__jenkins__*`, a custom one), or a new built-in write tool, hands that tool to a reviewer persona. Nothing fails, and the lint passes because it only checks that the list text matches. Reviewers can then act outside the review. The old design could not leak this way.
Fix: use an allowlist in `tools:` that names the Read, Grep and Glob built-ins and the four read-only servers from `config.json`. Have the lint hold the agents to that list.

2. [attention · 4] **`.agent/tools/maintenance/lint_prompts.py:12`** — the read-only server names have two owners, and the denylist has ten copies
```
# outside the review; the search servers are read-only and stay available.
READONLY_AGENT_DENY = (...)
```
`.agent/config.json` `mcp` names the servers the owner wants available. The denylist separately guesses which servers are dangerous. The deny string is also copied into each of the 10 agent files and into the lint. A server added to `config.json` that writes, or a server renamed, is not noticed by the denylist. Nothing derives one list from the other.
Fix: derive the allowlist from `config.json`, so the lint checks the frontmatter against that one source.

3. [attention · 4] **`.cursor/agents/specwriter-scope.md:5`** — only one of ten agents migrated, so the lint fails on the rest
```
disallowedTools: Write, Edit, NotebookEdit, Bash, ...
```
`READONLY_AGENTS` lists 10 stems. The grep over `.cursor/agents` finds `disallowedTools` only in `specwriter-scope.md`. The package shows no other agent files. If the other nine still carry `tools: Read, Grep, Glob`, they get both `agents-inherit-tools` findings and keep their MCP lockout. If they are missing, `read_text` raises `FileNotFoundError` and the lint crashes.
Fix: migrate all ten in the same change, or confirm they were already migrated.

4. [nit · 3] **`.agent/tools/maintenance/lint_prompts.py:34`** — the lint compares the deny string by exact order
`listed != READONLY_AGENT_DENY` is a tuple comparison, so a reordered but equivalent list fails with the same message as a missing entry. The message does not say what differs. Reporting the set difference would make the fix obvious.