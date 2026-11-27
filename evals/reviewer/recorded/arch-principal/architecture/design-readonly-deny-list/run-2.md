Assessment: request-changes — the change swaps a fail-closed read-only allow-list for an open-ended deny-list, when the allow-list could have named the MCP servers directly.

Read beyond the package: `.agent/config.json`, and a grep of `tools:`, `disallowedTools:` and `readonly:` across the working directory.

Approach: redirect — keep an allow-list (`tools: Read, Grep, Glob` plus the MCP servers named in `config.json`) instead of a deny-list that every new tool escapes.
Alternatives considered:
- Allow-list with explicit MCP names (`tools: Read, Grep, Glob, mcp__docs-internal__*, mcp__code-search__*, …`), generated from `config.json` `mcp` — wins. It reaches the same goal of MCP access, and the lint can derive the expected line from `config.json`. Any tool that is not listed stays denied.
- Don't build it: a session-level or harness-level permission mode for review agents. This would be better if the harness supports it, but I could not confirm that from the package. It loses as the immediate fix.
- Chosen deny-list — loses. Read-only is now whatever the session has minus 19 names. The set of tools a session can carry is open.

1. [blocking · 4] **`.agent/tools/maintenance/lint_prompts.py:15`** — a deny-list turns "read-only" from fail-closed into fail-open
```
READONLY_AGENT_DENY = ("Write", "Edit", "NotebookEdit", "Bash", "Agent", "Skill", ...
                       "mcp__github__*", "mcp__gitlab__*", ... "mcp__filesystem__*")
```
A session with an MCP server that isn't listed, such as `mcp__jenkins__*`, `mcp__sentry__*` or `mcp__aws__*`, hands that server's write tools to all ten reviewers. The same happens with any new native tool such as WebFetch, a cron tool or a future file writer. The lint passes because it only compares the deny string. The inheritance goal is only for the docs and code-search servers, and `config.json` already names them (`docs-internal`, `docs-public`, `plugin_codeindex_codeindex`, `code-search`). Fix: list `Read, Grep, Glob` plus those servers' `mcp__<server>__*` entries in `tools:`. Have the lint build the expected line from `config.json`. If MCP is truly shut out by any `tools:` line, state that evidence in the PR, since the allow-list for MCP names is the documented way in.

2. [attention · 3] **`.cursor/agents/specwriter-scope.md:5`** — the other nine agents are not migrated
```
.cursor/agents/specwriter-scope.md:5:disallowedTools: Write, Edit, ...
```
The only `tools:` or `disallowedTools:` frontmatter I could find in the working directory is in `specwriter-scope.md`. `lint_readonly_tools` iterates all ten `READONLY_AGENTS`. If the other nine files still carry `tools: Read, Grep, Glob` or are absent, the lint fails on each, or `read_text` raises on a missing file. The goal of MCP access is also not reached for them. Fix: migrate every file in `READONLY_AGENTS` in the same change, or confirm that they are already migrated.

3. [attention · 3] **`.agent/tools/maintenance/lint_prompts.py:34`** — the deny list has two owners, plus a third source in `config.json`
```
if listed != READONLY_AGENT_DENY:
```
The 19-name list is copied verbatim into each of ten agent files and into the lint's constant. Any edit needs eleven synchronized changes, and the lint requires exact order. Reordering the names, or adding one, fails every agent. The next likely changes cost this much. Adding a server to `config.json` means no agent file changes under an allow-list, while under this design the new server is silently inherited. Adding a write-capable MCP server means editing the list in eleven places. Fix: compare as sets, and keep one owner for the list, such as a generated frontmatter block or a lint `--fix`.

4. [attention · 2] **`.cursor/agents/specwriter-scope.md:5`** — `disallowedTools` is Claude Code frontmatter inside the `.cursor/agents` directory
```
readonly: true
disallowedTools: Write, Edit, ...
```
`readonly: true` is the field the other harness honours. If Cursor ignores `disallowedTools`, it still enforces the read-only flag. In Claude Code, `readonly` may be ignored, so only the deny-list protects the agent, and finding 1 is where it leaks. I could not verify either harness's behaviour from the package. Fix: confirm which key each harness enforces, and document it next to the constant.