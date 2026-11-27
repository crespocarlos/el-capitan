Assessment: request-changes — a deny-list is the wrong default for a read-only guarantee: any write-capable tool or MCP server not on the list is now allowed, and the lint can't catch that.

1. [blocking · 4] **`.agent/tools/maintenance/lint_prompts.py:12`** — the lint requires 10 agents to migrate, and the diff migrates only 1
```
READONLY_AGENTS = ("reviewer-adversarial", "reviewer-architecture", ... "specwriter-explorer", "reviewer-explorer")
...
if listed != READONLY_AGENT_DENY:
```
The diff changes only `specwriter-scope.md`. The other nine agents in `READONLY_AGENTS` are not in the diff. If they still carry `tools: Read, Grep, Glob`, the new lint fails nine times and the MCP goal is not met for them. The working directory holds only `specwriter-scope.md`, so I could not check the others. If they are absent from the repo, `path.read_text` raises `FileNotFoundError` and the lint crashes instead of reporting a finding.
Fix: migrate all ten agent files in the same change. Have the lint report a missing file as a finding.

2. [attention · 4] **`.agent/tools/maintenance/lint_prompts.py:15`** — the deny-list is open-ended, so the read-only guarantee is weaker than before
```
READONLY_AGENT_DENY = (..., "mcp__github__*", "mcp__gitlab__*", "mcp__slack__*", "mcp__linear__*", "mcp__jira__*", "mcp__notion__*", "mcp__filesystem__*")
```
The old allow-list of `Read, Grep, Glob` failed closed. The deny-list fails open. Any other MCP server with write or act tools is inherited, for example a new server, a differently named Slack or GitHub server, or a future built-in such as `WebFetch` or `TodoWrite`. `.agent/config.json` names only the docs and code-search servers, which are the ones these agents need. Names like `plugin_codeindex_codeindex` show server names are not predictable, so the enumerated prefixes will drift. The lint only checks that the list is spelled the same everywhere. It never checks that the list is complete.
Fix: if the harness supports it, keep an allow-list that includes the servers from `config.json` `mcp` (`mcp__docs-internal__*`, `mcp__docs-public__*`, and so on). If it does not, document the residual risk and add a lint that cross-checks the deny-list against the configured servers.

3. [attention · 3] **`.agent/tools/maintenance/lint_prompts.py:15`** — the same 19-entry list is copied into every agent file
The list lives in `lint_prompts.py` and is copied verbatim into up to ten frontmatter lines. The lint enforces an exact tuple match, so each change to the list means editing ten files in lockstep. The ordering is enforced too. A parse mismatch fails with the same generic message, "set disallowedTools to READONLY_AGENT_DENY".
Fix: add a `--fix` mode or a generator that rewrites the frontmatter from the constant. Alternatively, compare as a set and report the missing and extra entries.

4. [nit · 3] **`.agent/tools/maintenance/lint_prompts.py:8`** — the `readonly: true` field and `disallowedTools` can drift apart
Cursor's `readonly: true` stays alongside `disallowedTools`, which is a Claude Code field. Nothing links the two, and the lint checks only `disallowedTools`. The cost is that a Cursor-side agent could lose `readonly` unnoticed.
Fix: have the lint also assert `readonly: true`.