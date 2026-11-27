Assessment: request-changes — the shared lookups.md makes the vendor-docs check unconditional for every agent, including builders and the router, though the docs server indexes only one vendor's product.

1. [blocking · 4] **`.cursor/agents/references/lookups.md:21`** — Docs-server rule lost its opt-in scope and now applies to every product claim

```
Any claim about product, API, query-language or configuration behaviour that your work depends on
(writing it, reviewing it, or answering a comment about it) is checked on the docs server and cited
by URL. ... Never settle such a claim from memory
```

The old contract section was "opt-in: applies when the package says the artifact has content for the docs server's product". That boundary is gone. The new text covers any product or API claim, and the router rule loads it into every main session in every repository. The docs server indexes one vendor's documentation. An agent working on unrelated products or APIs (a builder using a third-party library, for example) will search the wrong corpus. It will then either mark correct claims `unverified (docs server unreachable)` and leave them unsettled, or cite irrelevant pages. The fallback line also forbids deciding from code, which blocks ordinary work. Nothing says which product the docs cover, so the model can't tell when the rule applies.

Fix: Name the product the docs server covers and restore the condition. For example: "When the claim concerns <vendor product> (the package or task says so), check it on the docs server and cite the URL. For any other product, this section does not apply." Say that "unverified" is for an unreachable server only, not for a product the server doesn't cover.

2. [attention · 3] **`rules/crew-router.mdc:6`** — The router pointer adds the lookups rule to builders and every session, and the reviewer-specific line collides with it

```
Lookups: follow `~/.cursor/agents/references/lookups.md` when you need code you cannot locate or a product or API fact.
```

The sentence is copied word for word into the reviewer contract and the router. lookups.md says "Your own file still sets your budget, your tools and where a note goes", but the router is not an agent file with an output slot. For a main session or a builder, the fallback line "put it at the end" has no defined meaning. The trigger "a product or API fact" is also broader than the old opt-in. The same sentence is now owned in two places, and the reviewer copy adds a partial rule: "Its `code search unreachable` line goes on the line after your `Assessment:` line". That duplicates the placement rule in lookups.md ("Your own file says where that line goes").

Fix: Keep the pointer in the router only if builders need it. Scope it to the product the docs cover, as in finding 1. Keep the Assessment-line placement in the reviewer contract only, worded as an override ("reviewers: the line goes after `Assessment:`") rather than as a second pointer.

3. [attention · 3] **`.cursor/agents/references/lookups.md:8`** — Fixed tool names and a path convention that may not resolve

```
`code_search` for the code index,
`docs` for the docs server.
```

The file requires `search_internal_docs`, `Grep`/`Glob`/`Read` and `~/.agent/config.json`. The pointers use `~/.cursor/agents/...`, while the file itself lives in `.cursor/agents/references/`. In a shared prompt, naming harness tools breaks portability. If the config path or tool names differ in a harness, the agent can't tell whether the server is "in your tools", so it falls to the fallback and wrongly reports "unreachable". The `~/.cursor` path also assumes a user-level install, but the diff adds the file under the repo's `.cursor/`, so the reference may dangle in other repositories.

Fix: Describe the capabilities instead: "the code-index search tool", "the docs search tool", "text search/read". Confirm that `~/.cursor/agents/references/lookups.md` is installed at that path, or reference it relative to the repo.