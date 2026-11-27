Assessment: request-changes — the opt-in docs rule becomes an unconditional rule for every agent and session, but the docs server covers only one vendor's product.
Read beyond the package: none found (Grep and Glob over the working directory show only the three changed files)

1. [blocking · 5] **`.cursor/agents/references/lookups.md:22`** — The docs check lost its product scope and now applies to every claim
```
Any claim about product, API, query-language or configuration behaviour that your work depends on
... is checked on the docs server and cited by URL. ... Never settle such a claim from memory
```
The old contract applied this only "when the package says the artifact has content for the docs server's product". The new text drops that condition. The router rule loads it into every session in every repository, builders included, and the docs server indexes one vendor's documentation. A builder working with an unrelated API (Postgres, React, a cloud SDK) hits the rule, searches a server that cannot answer, and fails the lookup. The fallback then tells it to mark the claim `unverified (docs server unreachable)` and "leave it unsettled rather than deciding it from code or memory". Work stalls, or every unrelated claim is mislabelled as a server outage. The text also forbids deciding from code, so the agent cannot resolve a claim by reading the repository.
Fix: restore the scope in `lookups.md`: "Applies only when the work touches the product the docs server indexes (name it here). For any other product, ignore this section." Keep the pointer's trigger equally narrow.

2. [attention · 4] **`rules/crew-router.mdc:5`** — The pointer carries its own partial rule and a trigger broader than the reference's
```
Lookups: follow `~/.cursor/agents/references/lookups.md` when you need code you cannot locate or a product or API fact.
```
The same sentence appears in the contract. The trigger "a product or API fact" is the unscoped wording from finding 1, and it sits in an always-on rule. The two copies will drift, because each restates the triggers that `lookups.md` already owns. A router-level pointer also sends builders to a file whose "Your own file still sets your budget… where a note goes in your output" framing assumes an agent file with an output section.
Fix: point to the file without restating triggers ("Lookups: see `lookups.md`"). Alternatively, drop the router pointer and let only the agents that need lookups load it.

3. [attention · 4] **`.cursor/agents/references/lookups.md:15`** — The fallback line has two homes and the "end of output" default conflicts with the contract
```
Your own file says
where that line goes; without such a place, put it at the end.
```
The contract says the line goes "on the line after your `Assessment:` line". A reviewer reads both files and sees "at the end" and "after Assessment". The contract's wording is the more specific one and presumably wins, but the shared file does not say so. A parser expecting the line after `Assessment:` can miss it.
Fix: in `lookups.md`, say "A reviewer follows the contract's placement; other agents put it at the end".

4. [attention · 3] **`.cursor/agents/references/lookups.md:7`** — The file names an MCP config key and a tool name that nothing in the package resolves
```
`~/.agent/config.json` `mcp`: `code_search` ... `docs`
Search the docs (`search_internal_docs`)
```
The rest of the package uses `~/.cursor/...` paths, and I found no `~/.agent/config.json` in it. If that file or those names are wrong, agents look for a config they cannot read, or call a tool that does not exist. The tool name is also a harness tool required by name where the capability "search the docs server" would do.
Fix: describe the capability ("the docs server's search and fetch tools") and drop the config path, or confirm both names against the real config.

5. [attention · 3] **`.cursor/agents/references/reviewer-contract.md:7`** — The behaviour change has no eval or regression check
```
Lookups: follow `~/.cursor/agents/references/lookups.md` when you need code you cannot locate or a product or API fact.
```
The change turns an opt-in rule into an always-on one, widens the trigger, and moves a parsed note line. No eval case or check in the diff covers a non-vendor artifact, which is the case that should skip the docs lookup. A check that gives a reviewer a non-vendor diff and asserts it does not emit `unverified (docs server unreachable)` would catch the regression in finding 1.
Fix: add that case to the reviewer eval set.