Assessment: request-changes — The lint now requires all 10 read-only agents to have the new frontmatter, but the diff migrates only `specwriter-scope`. The deny-list design also lets any unlisted write-capable MCP server through.

Read beyond the package: `.agent/config.json`, a grep of `.cursor/agents` frontmatter, a grep for other users of `lint_readonly_tools`.

Approach: redirect — Keep inheriting MCP, but allowlist the tools instead of denying a hand-written list of known-bad ones.
Alternatives considered:
- Keep `tools: Read, Grep, Glob` and append the MCP tool names from `config.json` (`mcp__docs-internal__*`, `mcp__code-search__*`, and so on) — This wins on safety, because a new server stays blocked until someone adds it. It loses only if the platform can't match server names that are configured per user. Check that before dropping it.
- Don't build it (leave `tools:` as it was) — This leaves the stated need unmet: the agents never reach docs or code search.
- Deny list inheriting everything (chosen) — This is the least work per agent. But the read-only guarantee now depends on knowing every dangerous tool name ahead of time.

1. [blocking · 4] **`.agent/tools/maintenance/lint_prompts.py:34`** — The lint demands a migration that only one of ten agents received
```
if TOOLS_LINE.search(text):
    findings.append((..., "agents-inherit-tools", "drop the tools: line so MCP is inherited"))
```
The grep of `.cursor/agents` finds `disallowedTools` only in `specwriter-scope.md`. The diff touches no other agent file. If the other nine still have `tools: Read, Grep, Glob`, the lint reports 18 findings on the next run, two per agent. If instead the diff left them untouched because they were already migrated, the working directory should show it, and it doesn't. In that case the change cannot ship with the lint passing. If the other nine have the old line, the lint also leaves those agents without MCP access, which defeats the point.
Fix: Apply the same frontmatter change to the other nine agent files in this change, then run the lint.

2. [attention · 4] **`.agent/tools/maintenance/lint_prompts.py:15`** — A deny list lets any unlisted write-capable tool through
```
READONLY_AGENT_DENY = ("Write", "Edit", ... "mcp__github__*", "mcp__gitlab__*", ... "mcp__filesystem__*")
```
Read-only agents now inherit everything the session has except the names listed here. Suppose a user adds an MCP server such as `mcp__confluence__*`, `mcp__postgres__*` or `mcp__sentry__*`, or Claude Code adds a new built-in write tool. Every reviewer and critic can then call it, and the lint still passes because it checks only the list text. `config.json` already names the two server groups the agents need (`docs`, `code_search`), so an allowlist is cheap to build.
Fix: Use `tools: Read, Grep, Glob` plus MCP globs for the docs and code-search servers named in `config.json`. Have the lint generate and check that line from `config.json`. If the premise that `tools:` blocks MCP is firm, at least add a lint check that fails on any inherited MCP server not in the allow or deny sets.

3. [attention · 3] **`.agent/tools/maintenance/lint_prompts.py:15`** — The same list is owned in 11 places, and the MCP server names in a second, separate place
The list lives in `lint_prompts.py` and is copied as a literal into each agent's frontmatter. The server names are separately owned by `config.json`. Adding a tool to the deny list means editing the constant and ten files in step. The lint checks equality, so a missed file fails the lint, but nothing helps the person fix it.
Fix: Add a `--fix` mode to the lint, or a generator that writes the frontmatter line from `READONLY_AGENT_DENY`.

4. [needs more info · 2] **`.cursor/agents/specwriter-scope.md:5`** — Does the Cursor harness honor `disallowedTools`?
The files sit in `.cursor/agents` and carry `readonly: true`, which looks like Cursor frontmatter. If Cursor ignores `disallowedTools` and has no `tools:` to fall back on, agents that were restricted before now run with full tools, and `readonly: true` is the only guard left. Which harness actually loads these files? If both do, the deny list needs a Cursor-side equivalent or a test.