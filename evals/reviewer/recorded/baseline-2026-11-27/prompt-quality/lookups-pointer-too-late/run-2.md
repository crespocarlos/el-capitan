Assessment: request-changes — the move drops the opt-in condition on docs lookups, and the pointer and the shared file disagree about where the fallback line goes.

1. [attention · 4] **`.cursor/agents/references/lookups.md:23`** — the opt-in scope on docs checks was dropped
```
Any claim about product, API, query-language or configuration behaviour that your work depends on
(writing it, reviewing it, or answering a comment about it) is checked on the docs server and cited
by URL. ... Never settle such a claim from memory
```
The removed section applied only "when the package says the artifact has content for the docs server's product". The new text covers any claim about any product, API or configuration, and the contract's pointer says to follow it "when you need ... a product or API fact". The diff says the intent is unchanged, but the new wording is unconditional, so a reviewer on an unrelated artifact now has to search docs, fetch a page and cite a URL for every such claim. Where the docs server is missing, every one of those claims is marked `unverified`. The "never from memory" rule also loses the boundary it had.
Fix: Restore the condition in lookups.md, e.g. "Applies only when the package says the artifact has content for the docs server's product; otherwise skip this section." Or keep the opt-in in the contract's pointer, and scope the "never from memory" sentence to that case.

2. [attention · 4] **`.cursor/agents/references/reviewer-contract.md:8`** — the pointer restates the placement rule and conflicts with the shared file
```
Its `code search unreachable` line goes on the line after your `Assessment:` line.
```
lookups.md says "Your own file says where that line goes; without such a place, put it at the end." This pointer gives its own placement, so the rule has two owners. The two also differ in how they read. The contract names a slot, while lookups.md defers to the caller's file and falls back to "the end". The contract's own wording is the only thing that settles this for reviewers. Meanwhile `unverified (docs server unreachable)` has no slot in the contract at all.
Fix: Let the contract own the placement for both markers, e.g. "Put the `code search unreachable` line after your `Assessment:` line. Put each `unverified` marker next to the claim it covers." Then have lookups.md only point to the caller's file for placement.

3. [needs more info · 3] **`.cursor/agents/references/reviewer-contract.md:7`** — the pointer path may not resolve
```
Lookups: follow `~/.cursor/agents/references/lookups.md`
```
The new file is at `.cursor/agents/references/lookups.md` in the repo, but the pointer uses a home-directory `~/.cursor/...` path. lookups.md also depends on `~/.agent/config.json` for its server names. Question: is the file installed to `~/.cursor` and is the config guaranteed to exist for every consumer? If not, the reviewer cannot load the reference and silently loses both the lookup order and the fallback lines.

4. [nit · 3] **`.cursor/agents/references/lookups.md:17`** — harness-specific tool names in a shared reference
```
use the equivalent `Grep`/`Glob`/`Read` call
```
The same file also names `search_internal_docs`. Cursor and Claude Code name these tools differently, so a reader in another harness may not map them. Fix: say "text search, file search and read", and name the docs tool by capability.