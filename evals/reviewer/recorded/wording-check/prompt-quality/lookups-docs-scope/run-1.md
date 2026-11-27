Assessment: request-changes — the opt-in scope on the docs rule was removed, so every session, builders included, must now check any product claim on a server that indexes only one vendor's docs.

Read beyond the package: none (the working directory holds only the three changed files)

1. [blocking · 5] **`.cursor/agents/references/lookups.md:24`** — Docs rule is unconditional, but the server covers one vendor
```
Any claim about product, API, query-language or configuration behaviour that your work depends on
... is checked on the docs server and cited by URL.
... Never settle such a claim from memory
```
The old contract applied this only "when the package says the artifact has content for the docs server's product". The new text applies to any product or API, and the router rule loads it into every session in every repository. A builder using a non-vendor library (say, a React or Postgres option) cannot verify it on a server that indexes one vendor. The failure fallback is "mark the claim `unverified (docs server unreachable)` and leave it unsettled rather than deciding it from code or memory". So the agent labels the claim unverified and refuses to settle it, even when the code shows the answer. That stalls work and mislabels the cause as an outage.
Fix: Restore the scope in `lookups.md`: "Applies only when the artifact has content for the product the docs server indexes (name it here). For other products, use normal evidence and do not mark them unverified." Then say which server's index is meant.

2. [attention · 4] **`rules/crew-router.mdc:5`** — Always-loaded pointer carries a docs trigger without the scope
```
Lookups: follow `~/.cursor/agents/references/lookups.md` when you need code you cannot locate or a product or API fact.
```
"a product or API fact" is the trigger for every main session. It is broader than the old opt-in, so the pointer widens scope by itself. Builders get an obligation to use docs that were previously reviewer-only and conditional. The contract pointer repeats the same sentence, so the trigger now exists in two places and can drift.
Fix: Make the pointer name only the file ("Lookups: see `lookups.md`"). Keep the trigger and its scope in `lookups.md` only.

3. [attention · 4] **`.cursor/agents/references/lookups.md:14`** — The unreachable-note placement conflicts with the contract and reads as a default
```
Your own file says where that line goes; without such a place, put it at the end.
```
The contract says the line goes "on the line after your `Assessment:` line". The lookups file says "at the end" when the agent's own file has no place. A reviewer loading both could follow either. Also, `lookups.md` says "Your own file still sets ... where a note goes", and the contract is that file for reviewers, so "put it at the end" is the fallback only when the contract does not apply. The contract's `Assessment:` rule and its "first in your reply" requirement also make that placement load-bearing for parsers.
Fix: In `lookups.md`, drop the placement fallback, or say "reviewers: see the contract; other agents: the end of the output."

4. [attention · 3] **`.cursor/agents/references/lookups.md:6`** — A tool name and a config pointer that may not resolve
```
The servers are the ones named in `~/.agent/config.json` `mcp`: `code_search` for the code index,
`docs` for the docs server.
```
The agent is told to read a file under `~/.agent` that it may not be able to see. It also names `search_internal_docs` as the tool. An agent with a different server or tool name has nothing to map to. The doc requires the tool by name where the capability would do.
Fix: Describe the capability ("the docs search and page-fetch tools") and drop the config-path dependency.

5. [attention · 3] **`.cursor/agents/references/reviewer-contract.md:7`** — Nothing measures the removed opt-in
```
Lookups: follow `~/.cursor/agents/references/lookups.md` when ...
```
The behaviour change affects every reviewer and builder. No eval case or regression row checks that a non-vendor artifact is not forced onto the docs server. A case with a non-vendor API claim would catch the regression.
Fix: Add a case where the artifact has no content for the docs server's product, and assert the claim is not marked `unverified`.