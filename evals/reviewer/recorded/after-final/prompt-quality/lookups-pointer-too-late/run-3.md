Assessment: request-changes — the move drops the opt-in scope on product-fact checks and replaces it with an unconditional rule, and the pointer is a conditional "when you need" that the reader may never follow.
Read beyond the package: none (searched the working directory for references to lookups.md; only the two changed files matched)

1. [attention · 4] **`.cursor/agents/references/lookups.md:22`** — The opt-in docs check became unconditional, so scope silently widened
```
Any claim about product, API, query-language or configuration behaviour that your work depends on
(writing it, reviewing it, or answering a comment about it) is checked on the docs server and cited
by URL.
```
The old contract text was `## Product facts (opt-in: applies when the package says the artifact has content for the docs server's product)`. The new text applies to any product, API or configuration claim. A reviewer looking at an unrelated diff that mentions a config option now has to run docs searches, or mark the claim `unverified (docs server unreachable)`. The docs server may not cover that product, and the reviewer has no budget for these lookups. The contract's tool budget counts docs lookups, so this also competes with the budget cap.
Fix: Restore the trigger in lookups.md, for example "Applies when the package says the artifact has content for the docs server's product."

2. [attention · 4] **`.cursor/agents/references/reviewer-contract.md:7`** — The pointer is conditional and the unreachable-line rule is partly duplicated
```
Lookups: follow `~/.cursor/agents/references/lookups.md` when you need code you cannot locate or a product or API fact.
Its `code search unreachable` line goes on the line after your `Assessment:` line.
```
The old text said "Search the code index before reaching for a text search" directly in the contract, so an agent that read only the contract saw it. Now that rule sits in a file the agent opens only if it decides it "needs" code it cannot locate. An agent that reaches straight for Grep never sees "search the code index first", so the stated intent is lost. The contract also carries part of the unreachable-line rule (its placement) while lookups.md carries the wording and the fallback, so the rule now lives in two places.
Fix: Keep the one-line rule in the contract: "Search the code index before a text search; read `lookups.md` for the fallback and docs-server rules." Make the placement the contract's own statement, and point to lookups.md for the wording only.

3. [attention · 3] **`.cursor/agents/references/lookups.md:17`** — Two placements for the unreachable line
```
Your own file says
where that line goes; without such a place, put it at the end.
```
The contract says the line goes "on the line after your `Assessment:` line". lookups.md says the agent's own file decides, and otherwise the line goes at the end. A reviewer loading both cannot tell which wins. The contract's own note defers to the persona, but the persona file may say nothing, so the reviewer may follow "at the end" and the line lands after `### Findings: none`.
Fix: Delete the placement sentence from lookups.md and leave placement to the loading file. The contract's line already covers reviewers.

4. [nit · 3] **`.cursor/agents/references/lookups.md:6`** — Config pointer with no fallback
```
The servers are the ones named in `~/.agent/config.json` `mcp`
```
The agent may not be able to read that file, and the tools list already tells it which servers it has. The extra pointer adds a file the reader may not be able to resolve. It also leaves open whether the tool names in the file match the real ones, such as `search_internal_docs`.
Fix: Drop the sentence, or name the tools directly.

5. [needs more info · 2] **`.cursor/agents/references/lookups.md:22`** — No eval covers the change
The change alters a parsed line (`code search unreachable: used text search`), its placement, and the docs-check trigger. Is there a regression row or check that parses the placement after `Assessment:` or the `unverified (docs server unreachable)` marker? If not, a placement drift would only show up when `crew-review-findings.py` fails on a real review.