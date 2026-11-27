Assessment: request-changes — the move drops the docs-check opt-in gate and points at a path that may not resolve, so the "intent unchanged" claim doesn't hold.

1. [attention · 4] **`.cursor/agents/references/lookups.md:23`** — Opt-in gate on product-fact checks was dropped
```
Any claim about product, API, query-language or configuration behaviour that your work depends on
(writing it, reviewing it, or answering a comment about it) is checked on the docs server and cited
by URL.
```
The removed contract section was gated: "opt-in: applies when the package says the artifact has content for the docs server's product". The shared file has no gate and says "Never settle such a claim from memory". Every reviewer must now run docs lookups for any product or API claim, or mark it `unverified (docs server unreachable)`, even when the artifact has nothing to do with that product. The change is described as "unchanged", so this is an unintended scope widening. It also adds findings noise and spends tool budget.
Fix: Restore the condition in `lookups.md`, e.g. "When the package says the artifact has content for the docs server's product, check any claim about …". Alternatively, keep the gate in the contract pointer and say it there.

2. [attention · 3] **`.cursor/agents/references/reviewer-contract.md:7`** — Pointer path may not resolve, and the lookup rule is now only reachable through it
```
Lookups: follow `~/.cursor/agents/references/lookups.md` when you need code you cannot locate or a product or API fact.
```
The file is added at the repo-relative `.cursor/agents/references/lookups.md`, but the pointer uses a home-directory `~/.cursor/...` path. That resolves only if the files are installed there. If the recipient can't read it, the rule "search the code index before a text search" is gone from the contract, which the old text stated directly. `lookups.md` also says the servers are named in `~/.agent/config.json`, another home path.
Fix: Use the same path form the other references use, and keep the one-line core rule ("search the code index before a text search") in the contract next to the pointer.

3. [nit · 3] **`.cursor/agents/references/lookups.md:17`** — Harness tool names in a shared prompt
```
use the equivalent `Grep`/`Glob`/`Read` call and
say so in one line of your output
```
`Grep`, `Glob`, `Read` and `search_internal_docs` are harness-specific names. A Cursor run may expose different tool names. Name the capability instead ("text search", "read the file", "search the docs").
Fix: Replace the tool names with capability wording.