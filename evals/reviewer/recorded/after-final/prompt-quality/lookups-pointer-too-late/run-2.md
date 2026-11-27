Assessment: request-changes — the move drops the old opt-in scope on product facts and the pointer only fires "when you need" a lookup, so the code-index-first intent is weaker than before.
Read beyond the package: none (the directory holds only the two changed files; a Grep found no other referrers)

1. [attention · 4] **`.cursor/agents/references/lookups.md:22`** — Product-fact check lost its opt-in scope and now applies to every review
```
Any claim about product, API, query-language or configuration behaviour that your work depends on
(writing it, reviewing it, or answering a comment about it) is checked on the docs server and cited
by URL.
```
The old contract section read "Product facts (opt-in: applies when the package says the artifact has content for the docs server's product)". The new text applies to any product, API or configuration claim, and the contract pointer no longer carries the opt-in. A reviewer on an unrelated diff now has to cite docs URLs or mark claims `unverified (docs server unreachable)`. Where no docs server exists, as in this eval, it will mark many claims unsettled. The change is not flagged as deliberate.
Fix: restore the trigger in `lookups.md`, for example "Applies when the package says the artifact has content for the docs server's product", or state in the contract pointer that the product-facts part is opt-in.

2. [attention · 3] **`.cursor/agents/references/reviewer-contract.md:7`** — The pointer's trigger is vague, and the code-index-first rule is no longer stated where reviewers read it
```
Lookups: follow `~/.cursor/agents/references/lookups.md` when you need code you cannot locate or a product or API fact.
Its `code search unreachable` line goes on the line after your `Assessment:` line.
```
The contract used to state the rule: search the code index before a text search. Now it only points to a file. A reviewer that feels it knows the right words, or whose package has no reference loaded, will go straight to Grep. The pointer also tells reviewers to read the file "when you need" a lookup, which they decide after already searching. The "unreachable" line is also a partial rule that lives in the contract and in `lookups.md`. Both say where it goes, and `lookups.md` says "Your own file says where that line goes; without such a place, put it at the end", so the two placements conflict.
Fix: keep one imperative sentence in the contract, such as "Search the code index before a text search; see lookups.md for fallbacks", and keep the placement of the line in one file only. The contract is the owner, since `lookups.md` already defers to "your own file".

3. [attention · 3] **`.cursor/agents/references/lookups.md:7`** — The server names and the docs tool are unresolved
```
The servers are the ones named in `~/.agent/config.json` `mcp`: `code_search` for the code index,
`docs` for the docs server.
```
The text points to a config file the reader may not be able to read. It names `search_internal_docs` as a tool but gives no tool name for the code index. Meanwhile the contract says "No code index or docs server in this eval". A reader cannot tell whether "not in your tools" applies, and it may call a tool that does not exist.
Fix: name the capability, not a config path, and say what to do when the config is unreadable. The existing fallback line covers a failed call but not an unresolved server name.

4. [nit · 3] **`.cursor/agents/references/lookups.md:24`** — "Never settle such a claim from memory" is emphasis with a reason that is cut off by the broad scope
The reason ("a guessed option reads the same as a verified one") is given, but the rule is "never" and covers writing and answering. It forces `unverified` marks on trivial well-known facts, which adds noise to the output. Narrow it to claims the work turns on.