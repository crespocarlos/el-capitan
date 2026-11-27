Assessment: request-changes — the deny-list swaps a closed read-only allowlist for an open one, and an allowlist built from `config.json` would reach the same goal without that gap.

Read beyond the package: `.agent/config.json`. I also grepped for `tools:` and `disallowedTools` across the working directory.

Approach: redirect — keep an allowlist, `tools: Read, Grep, Glob` plus the MCP servers named in `config.json`, instead of inheriting everything and denying a hand-kept list.
Alternatives considered:
- Deny-list with inheritance (chosen) — it reaches MCP with one edit. It fails open: every tool or server not on the list is writable by a read-only agent. That list already guesses at server names (`mcp__github__*` and others) and cannot know about future ones.
- Allowlist with MCP wildcards, generated from `config.json` — `tools: Read, Grep, Glob, mcp__docs-internal__*, mcp__docs-public__*, mcp__code-search__*, mcp__plugin_codeindex_codeindex__*`. It keeps the closed-world guarantee and still reaches the servers. The lint can derive the expected line from `config.json`, the existing owner of the server names. This wins.
- Do nothing, keeping `Read, Grep, Glob` — it is safe but cannot reach docs or code search, which is the problem being fixed. It loses.

Next changes, and their cost under this design:
- A new tool or MCP server appears, such as a new write-capable server or a new Claude Code built-in. Under the deny-list, every read-only agent silently gains it until someone edits `READONLY_AGENT_DENY` and all 10 agent files. Under an allowlist it is denied by default.
- A new read-only agent is added. It needs the same long line copied by hand. The lint catches drift, but the line is 20 entries long.

1. [attention · 4] **`.agent/tools/maintenance/lint_prompts.py:16`** — fail-open deny-list lets read-only agents inherit any unlisted write-capable tool
```
READONLY_AGENT_DENY = ("Write", "Edit", "NotebookEdit", "Bash", "Agent", "Skill", ...
                       "mcp__github__*", "mcp__gitlab__*", "mcp__slack__*", ... "mcp__filesystem__*")
```
A session has a write-capable MCP server not on the list, for example `mcp__confluence__*` or a custom server, or Claude Code ships a new built-in that mutates state. Every reviewer, explorer and spec critic inherits it, although the lint passes and the agent is marked `readonly: true`. The list also names servers that may not exist in this repo (`config.json` has only docs and code-search servers), so it is a guess at the session's tools.
Fix: use an allowlist, `tools: Read, Grep, Glob` plus `mcp__<server>__*` for each server in `config.json` `mcp.docs` and `mcp.code_search`. Have the lint build the expected line from `config.json`. If MCP wildcards in `tools:` do not behave as expected under the target harness, keep the deny-list only as a documented fallback.

2. [attention · 3] **`.agent/tools/maintenance/lint_prompts.py:16`** — the set of safe MCP servers has two owners
```
"mcp__github__*", "mcp__gitlab__*", "mcp__slack__*", ...
```
`.agent/config.json` names the servers read-only agents should use: `docs-internal`, `docs-public`, `plugin_codeindex_codeindex` and `code-search`. The lint separately lists the servers to block. If someone adds a server to `config.json`'s docs or code-search lists whose name collides with a denied pattern, such as a `mcp__filesystem__*`-style code index, it is denied. If a new write server is added elsewhere, it is allowed. The two lists drift apart without anything noticing.
Fix: derive the policy from `config.json` with an allowlist, so there is one owner.

3. [needs more info · 3] **`.cursor/agents/specwriter-scope.md:5`** — only 1 of 10 agent files is shown converted
```
disallowedTools: Write, Edit, NotebookEdit, Bash, ...
```
The lint iterates all 10 `READONLY_AGENTS`. The diff touches only `specwriter-scope.md`, and the working directory holds only that agent file. If the other nine still have `tools: Read, Grep, Glob`, the lint reports `agents-inherit-tools` for nine files and any CI gate on it fails. If they were converted elsewhere, this is fine. Which is it? Also, do the agents run under Cursor, given the `.cursor/agents` path and the `readonly: true` key? If so, the question is whether Cursor honours `disallowedTools` or ignores it and leaves the agents unrestricted.