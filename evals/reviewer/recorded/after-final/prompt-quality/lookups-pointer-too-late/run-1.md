Assessment: request-changes — the contract's own "code index first" rule is now only a conditional pointer, and the opt-in scope of the docs rule was dropped without a decision.
Read beyond the package: none found (Grep and Glob over the working directory show only these two files).

1. [attention · 3] **`.cursor/agents/references/reviewer-contract.md:7`** — the code-index-first rule now sits behind a conditional pointer

```
Lookups: follow `~/.cursor/agents/references/lookups.md` when you need code you cannot locate or a product or API fact.
```

The old contract stated "Search the code index before reaching for a text search" directly, so every reviewer saw it. Now the rule is in `lookups.md`, and the contract only says to follow that file "when you need code you cannot locate". An agent decides it needs code at the moment it runs a first `Grep`. Unless it opens the second file before that, it never sees the rule and starts with text search. The stated intent, "an agent searches the code index before a text search", then depends on a read the agent only does after it has already chosen the wrong tool.
Fix: keep the one-sentence rule in the contract, "Search the code index before a text search; when you cannot, see `lookups.md` for the fallback line", and let `lookups.md` hold the detail.

2. [attention · 4] **`.cursor/agents/references/lookups.md:22`** — the opt-in condition on docs lookups was dropped, so the rule now applies to every claim

```
Any claim about product, API, query-language or configuration behaviour that your work depends on
... is checked on the docs server and cited by URL. ... Never settle such a claim from memory
```

The old section was headed "Product facts (opt-in: applies when the package says the artifact has content for the docs server's product)". The new contract pointer and `lookups.md` have no such condition. A reviewer on any diff that touches a config option or a query-language detail must now look it up and cite a URL, or mark it `unverified (docs server unreachable)`. When no docs server is configured, such as in this eval, those claims can no longer be settled from code. Reviews fill with `unverified` marks, and findings the code alone settles get left open.
Fix: restore the gate at the top of the section: "Applies only when the package says the artifact has content for the docs server's product."

3. [attention · 3] **`.cursor/agents/references/lookups.md:17`** — two placement rules for the fallback line, and a path that may not resolve

```
Your own file says where that line goes; without such a place, put it at the end.
```
```
Its `code search unreachable` line goes on the line after your `Assessment:` line.
```

The contract is not "your own file", so a reader can't tell which rule wins. Following `lookups.md` literally, the reader looks for a placement in its persona file, finds none, and puts the line at the end. The contract says it goes after `Assessment:`. A parser or reader that looks for the line after `Assessment:` then misses it.
The contract also points at `~/.cursor/agents/references/lookups.md`, while the file is added under the repo's `.cursor/agents/references/`. If the home-directory copy isn't installed, the pointer does not resolve. Separately, `lookups.md` names `~/.agent/config.json` and the tool `search_internal_docs`, which the capability alone would cover.
Fix: drop the "put it at the end" fallback from `lookups.md` and state the Assessment-line placement once, in the contract. Use a repo-relative pointer path, or confirm the install location.