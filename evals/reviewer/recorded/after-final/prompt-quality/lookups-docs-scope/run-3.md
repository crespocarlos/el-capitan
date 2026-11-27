Assessment: request-changes — the shared reference widens the docs-server rule from opt-in to every agent in every repository, but the server covers one vendor's docs, so most claims can't be checked there.

Read beyond the package: none (the working directory holds only the three changed files)

1. [blocking · 4] **`.cursor/agents/references/lookups.md:21`** — Docs-check rule now applies to every claim, but the server covers one vendor
```
Any claim about product, API, query-language or configuration behaviour that your work depends on
... is checked on the docs server and cited by URL. ... Never settle such a claim from memory
```
The removed contract text was opt-in: "applies when the package says the artifact has content for the docs server's product". The new text drops that condition and reaches builders and every main session through the router. A builder working on an unrelated library's API can't verify the claim on a one-vendor docs index. It must either mark it `unverified (docs server unreachable)`, which is also the wrong reason, or run pointless searches. Reviewers also lose a scoping trigger they could recognise. The fallback "rather than deciding it from code or memory" forbids settling a claim from the code that implements it.
Fix: Restore the scope in `lookups.md`, for example "applies only when the artifact touches <vendor>'s product, named by the package or task". Say that other claims are judged from the code or the task, and marked unverified only if they matter.

2. [attention · 4] **`.cursor/agents/references/reviewer-contract.md:8`** — The contract's pointer restates the placement rule that `lookups.md` also states
```
Its `code search unreachable` line goes on the line after your `Assessment:` line.
```
`lookups.md` says "Your own file says where that line goes; without such a place, put it at the end." The contract places the line right after `Assessment:`, and the shared file defers to the agent file. This is one rule in two places, so it will drift. The pointer also carries a partial rule of its own. A reviewer that reads the wording from `lookups.md` has to work out that the contract is its "own file".
Fix: Keep the placement only in `lookups.md` and add `Reviewers: after the Assessment line` there. Reduce the contract to the bare pointer, or keep the placement only in the contract and drop the end-of-output default from `lookups.md`.

3. [attention · 3] **`rules/crew-router.mdc:5`** — Always-loaded rule adds a pointer whose mandatory behaviour assumes agent-specific outputs
```
Lookups: follow `~/.cursor/agents/references/lookups.md` when you need code you cannot locate or a product or API fact.
```
Every main session, in every repository, now carries this pointer. The referenced file demands a docs-server citation for each product claim, and says to emit a line that sits "after your `Assessment:` line". A main session has no such line. With no budget carve-out, the rule makes sessions spend tool calls on lookups.
Fix: Decide whether main sessions should follow the rule at all. If so, say how it applies to them, or state in `lookups.md` that its lookup is bounded by the agent's own budget.

4. [attention · 3] **`.cursor/agents/references/lookups.md:21`** — Mandatory search and fetch collides with fixed tool budgets
```
Search the docs (`search_internal_docs`), then fetch the page you cite.
```
The file claims "Your own file still sets your budget". A reviewer with a "stop at N tools" budget cannot both check every product claim and stop at N. It's unclear which rule wins. The text also names a harness tool, `search_internal_docs`, where "docs search" would do.
Fix: Say the lookup is subject to the agent's budget. When the budget runs out, mark the claim `unverified (budget)` instead of continuing. Refer to the capability rather than the tool name.

5. [needs more info · 3] **`.cursor/agents/references/lookups.md:7`** — Config path and "every agent gets a pointer" are unverified
`The servers are the ones named in `~/.agent/config.json` `mcp`: `code_search` for the code index, `docs` for the docs server.`
The change description says every agent gets the pointer, but the diff adds it only to the contract and the router. No other agent files appear in it. The config file and its key names are not in the package. Question: do the `mcp` keys `code_search` and `docs` exist in that file, and do the builder and other agent files get the pointer in another change? If not, the pointer dangles for agents that never load it, or the names mismatch at run time.