Assessment: request-changes — the docs rule drops its opt-in scope, so every agent in every repository must check any product or API claim on a server that indexes only one vendor's documentation.
Read beyond the package: none found. The working directory holds only the three changed files, and a grep for the new names found no other consumers.

1. [blocking · 5] **`.cursor/agents/references/lookups.md:21`** — the docs rule lost its opt-in scope and now applies to every product, API and configuration claim
```
Any claim about product, API, query-language or configuration behaviour that your work depends on
... is checked on the docs server and cited by URL. ... Never settle such a
claim from memory
```
The old contract text read "Product facts (opt-in: applies when the package says the artifact has content for the docs server's product)". That condition is gone. The router rule now sends builders in every repository here too. A builder working on Postgres, React or AWS has to search a server that indexes one vendor's docs. The search returns nothing relevant, so the agent either cites an unrelated page or marks the claim `unverified (docs server unreachable)` and leaves it unsettled. Most claims in unrelated repositories end up blocked or mislabelled as a server outage.
Fix: restore the scope in `lookups.md`, for example "Applies only when the package says the artifact has content for the docs server's product (the product the docs server indexes). For any other product, this section does not apply." Name the product once in that file as the owner. Do not use the "unreachable" marker for out-of-scope claims.

2. [attention · 4] **`.cursor/agents/references/lookups.md:28`** — one marker covers two different situations
```
With no docs server in your tools, or a failed lookup, mark the claim
`unverified (docs server unreachable)` and leave it unsettled rather than deciding it from code or
memory.
```
A claim that is out of scope or absent from the docs gets the same "unreachable" marker as a real outage, so a reader cannot tell which happened. "Leave it unsettled rather than deciding it from code" also stops a builder from relying on the code in front of it. A reviewer who has the code and the real behaviour can no longer settle a claim from it.
Fix: use a separate marker for "no matching page found", and limit "leave unsettled" to claims within the docs server's product.

3. [attention · 3] **`.cursor/agents/references/lookups.md:15`** — "say so in one line of your output … put it at the end" conflicts with the contract's placement
```
Your own file says
where that line goes; without such a place, put it at the end.
```
The contract places the line "on the line after your `Assessment:` line". The router rule gives no placement, and a builder with no output slot has no clear place to put it. A reviewer also has two rules: the contract says right after the Assessment line, and `lookups.md` says its own file decides. The contract does resolve this for reviewers, but the precedence is stated nowhere.
Fix: state in `lookups.md` that a persona or contract placement wins, and give builders an explicit slot.

4. [attention · 3] **`rules/crew-router.mdc:5`** — the always-loaded rule adds a pointer carrying its own partial rule, to a path that may not resolve
```
Lookups: follow `~/.cursor/agents/references/lookups.md` when you need code you cannot locate or a product or API fact.
```
The rule loads in every repository. The pointer uses a `~/.cursor/...` path, but the file is added under the repository's `.cursor/agents/references/`, and the router lives in `rules/`. If the home path is not where the file is installed, the reference dangles. Also, the trigger "a product or API fact" is broader than the old opt-in, and it is repeated in the contract. The same trigger sentence in two places will drift.
Fix: confirm the install path resolves for every session. Keep the trigger wording only in `lookups.md`, and have the pointers say "see lookups.md".

5. [attention · 3] **`.cursor/agents/references/lookups.md:7`** — a hard-coded tool name and config path
```
Search the docs (`search_internal_docs`), then fetch the page you cite.
```
The tool is named by its harness name, which is not a CLI command. The sentence also says "the servers are the ones named in `~/.agent/config.json` `mcp`" but this file has no way to tell a reader whether that config exists. No eval case or check covers the moved `code search unreachable` line or the unverified marker.
Fix: describe the capability ("search the docs server, then fetch the page") and add a regression row for the placement line and the opt-in scope.