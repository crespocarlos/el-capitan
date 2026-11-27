Assessment: request-changes — the old opt-in scope on product facts was dropped, so every agent, builders included, must now verify any product or API claim against a docs server that indexes only one vendor's documentation.

1. [blocking · 5] **`.cursor/agents/references/lookups.md:21`** — Docs-check rule is unscoped but the docs server covers one vendor

```
Any claim about product, API, query-language or configuration behaviour that your work depends on
...
Never settle such a claim from memory: a guessed option reads the same as a verified one.
```

The old contract section was "opt-in: applies when the package says the artifact has content for the docs server's product". The new rule drops that boundary and applies to any product or API claim. Because the router rule and every agent now point here, a builder touching a third-party library or a different vendor's API must check a server that cannot answer. The fallback then tells it to mark the claim `unverified (docs server unreachable)` and "leave it unsettled rather than deciding it from code or memory". That wrongly treats "out of coverage" as "unreachable", and it blocks work that the code itself could settle.

Fix: restore the scope in `lookups.md`. For example: "Applies only when the claim concerns the product the docs server indexes (named in `~/.agent/config.json`), or the package says the artifact has content for it. For other products, this rule does not apply." Add a separate marker, such as `not covered by docs server`, that doesn't forbid using the code. Use "unreachable" only for failures.

2. [attention · 4] **`.cursor/agents/references/lookups.md:11`** — "Never"/"Any claim" absolutes with no reason for the boundary, and "unsettled" has no output slot

```
Search the code index before a text search
...
leave it unsettled rather than deciding it from code or memory.
```

"Unsettled" is not an observable artifact. It does not say whether a reviewer should raise a finding, a builder should stop, or the claim should be reported. The file defers only the code-search note to "Your own file says where that line goes", so the `unverified` marker has no defined place. Different agents will handle it differently.

Fix: state where the `unverified` marker goes, for example in the same slot as the code-search line. State what the agent does next: continue and flag it, or stop.

3. [attention · 3] **`rules/crew-router.mdc:5`** — Always-loaded rule gets a lookup pointer that is irrelevant to routing, and the path is unverified

```
Lookups: follow `~/.cursor/agents/references/lookups.md` when you need code you cannot locate or a product or API fact.
```

The router loads in every session in every repository, and it is the widest-reaching place to add this pointer. Combined with finding 1, it extends an unscoped mandate to repositories that have no code index or docs server. The same pointer sits in both the contract and the router, so the sentence is duplicated with no single owner. The path also uses `~/.cursor/...`, while the files live under `.cursor/agents/references/` in the repo. I could not verify that these resolve to the same place.

Fix: scope the router pointer to sessions where those servers are configured, or drop it and let the agents' own files point to it. Confirm that the `~` path resolves in every repository.

4. [nit · 3] **`.cursor/agents/references/lookups.md:9`** — Hard-coded config path and tool name

```
`code_search` for the code index,
`docs` for the docs server.
```
and `Search the docs (`search_internal_docs`)`

The file names the server keys and the tool `search_internal_docs`. If the config renames them, the instruction dangles silently. Naming a harness tool in a shared prompt costs portability.

Fix: say "search the docs server, then fetch the page you cite", and keep the config mapping in one place.