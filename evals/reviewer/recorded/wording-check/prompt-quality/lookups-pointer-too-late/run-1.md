Assessment: request-changes — the move drops the opt-in scope for docs lookups and the pointer sits where the lookup rule has to be applied, so the intent "search the code index first" is not preserved.

Read beyond the package: none (grep over the case directory found only the two changed files)

1. [attention · 4] **`.cursor/agents/references/reviewer-contract.md:7`** — docs-server check lost its opt-in scope and now applies to every review
```
Lookups: follow `~/.cursor/agents/references/lookups.md` when you need code you cannot locate or a product or API fact.
```
The old heading was "Product facts (opt-in: applies when the package says the artifact has content for the docs server's product)". The new pointer fires on any "product or API fact", and lookups.md says "Any claim about product, API, query-language or configuration behaviour … is checked on the docs server and cited by URL. … Never settle such a claim from memory". A reviewer of a non-Elastic diff, or one with no docs tool, now has to mark claims `unverified (docs server unreachable)`. Those marks are noise, and the budget goes on docs calls the old rule never required. The change was meant to keep the intent, but this is a silent scope change.
Fix: restore the condition in the pointer, e.g. "Product and API facts: only when the package says the artifact has content for the docs server's product, follow the 'Product and API facts' section of `~/.cursor/agents/references/lookups.md`."

2. [attention · 3] **`.cursor/agents/references/reviewer-contract.md:7`** — the pointer's trigger is "when you need code you cannot locate", which comes after the first search
```
follow `~/.cursor/agents/references/lookups.md` when you need code you cannot locate or a product or API fact.
```
The old text put the rule itself in the contract: "Search the code index before reaching for a text search". Now the rule lives only in a file that is read on demand. An agent that has already decided to `Grep` has no reason to open lookups.md, so it skips the index and never says "unreachable". Both the "Grep before the index" case and the lost "used text search" note go unnoticed. The pointer also uses a `~/.cursor/...` path, while the file is at `.cursor/agents/references/`. I could not check whether that resolves.
Fix: keep the one-line rule in the contract ("Search the code index (`code_search`) before a text search; details and fallback in lookups.md"), so the deciding instruction is always loaded.

3. [attention · 3] **`.cursor/agents/references/lookups.md:17`** — the placement of the fallback line is stated in two files, with conflicting defaults
```
Your own file says
where that line goes; without such a place, put it at the end.
```
The contract says "Its `code search unreachable` line goes on the line after your `Assessment:` line." The reference defers to "your own file" and then defaults to "at the end". A reviewer who sees both cannot tell which wins. The `Read beyond the package:` line in the contract also claims the position after `Assessment:`. The same 'one thing, two placements' problem applies to the docs mark, which the old contract never defined.
Fix: have lookups.md say only "put the line where your reviewer contract says" and drop the "at the end" default. The contract is the owner.

4. [nit · 3] **`.cursor/agents/references/lookups.md:7`** — it names `~/.agent/config.json` `mcp` and a tool, `search_internal_docs`, by harness name
```
The servers are the ones named in `~/.agent/config.json` `mcp`: `code_search` for the code index,
```
The reviewer is told it has "No code index or docs server in this eval", so the agent cannot resolve these. A capability description ("the docs search tool") would not break if a tool is renamed. The cost is drift when the config changes.
Fix: describe the capability and drop the config path.

5. [needs more info · 2] **`.cursor/agents/references/lookups.md`** — no eval or check covers the changed `code search unreachable` line or the `unverified` mark
Does a regression row or a consolidation check read these strings? If `crew-review-findings.py` or an eval expects the line right after `Assessment:`, the moved rule could break it unnoticed.