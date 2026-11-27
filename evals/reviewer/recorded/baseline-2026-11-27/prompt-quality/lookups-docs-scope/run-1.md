Assessment: request-changes — the change drops the docs-server rule's opt-in boundary. The server indexes one vendor's docs, but the rule now reaches every agent, builders included, and every main session in every repository.

1. [blocking · 4] **`.cursor/agents/references/lookups.md:23`** — Docs-verification rule lost its scope and now applies to every product claim
```
Any claim about product, API, query-language or configuration behaviour that your work depends on
...
With no docs server in your tools, or a failed lookup, mark the claim
`unverified (docs server unreachable)` and leave it unsettled rather than deciding it from code or
```
The old contract applied this only when "the package says the artifact has content for the docs server's product". The new text drops that condition, and the router and every agent now point to it. A builder working on any other product or library must "check on the docs server and cite by URL". The server only indexes one vendor, so every such lookup returns nothing or fails. The agent then marks the claim `unverified (docs server unreachable)`, which is also the wrong reason. The "leave it unsettled rather than deciding it from code" fallback blocks work that code or the library's own docs could settle. Because "Never settle such a claim from memory" is absolute, a model cannot recover. This is a new defect in the diff.

Fix: Restore the boundary. For example: "Applies only to claims about <vendor> products, which the docs server indexes. For any other product, use the repository's own sources and don't mark the claim unverified." Name the vendor, or say how an agent can tell, and keep the opt-in trigger in the contract. Also say that a docs search with no results is different from an unreachable server.

2. [attention · 3] **`rules/crew-router.mdc:5`** — Home-relative pointer may not resolve, and the new file sits at a different path
```
Lookups: follow `~/.cursor/agents/references/lookups.md` when you need code you cannot locate or a product or API fact.
```
The file is added at `.cursor/agents/references/lookups.md`, which is repo-relative. The pointers use `~/.cursor/...`. This rule loads "in every repository". If the file isn't installed under the user's home directory, the reference dangles and agents get no guidance. `lookups.md:7` also names `~/.agent/config.json`, a different harness directory, for the server names. The same pointer text appears in `reviewer-contract.md` (line 7).

Fix: Confirm that the install step places `lookups.md` at `~/.cursor/agents/references/`. If it doesn't, use a path that resolves for every consumer. Make the config path consistent or say why it differs.

3. [attention · 3] **`.cursor/agents/references/lookups.md:16`** — Shared reference names harness tools
```
use the equivalent `Grep`/`Glob`/`Read` call
```
`search_internal_docs` is also named at line 24. Cursor and Claude Code name their tools differently, and this file is loaded by every agent in every session. A harness without those exact names leaves the fallback ambiguous.

Fix: Name the capability instead: "use text search and file reading". Say that the docs search tool is the one the `docs` server provides.

4. [nit · 2] **`.cursor/agents/references/lookups.md:18`** — Fallback-line placement rule is split across two files
```
Your own file says
where that line goes; without such a place, put it at the end.
```
`reviewer-contract.md` fixes the placement for reviewers: the line after `Assessment:`. For other agents, "at the end" may conflict with a required output format, such as a parsed one. The cost is a stray line in parsed output.

Fix: Keep placement owned by each agent's own file. Have `lookups.md` say only what the line says.