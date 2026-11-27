Assessment: request-changes — the move quietly turns an opt-in docs check into a rule for every reviewer, and the pointer path may not resolve.

1. [attention · 4] **`.cursor/agents/references/lookups.md:23`** — the opt-in condition on docs checks was dropped, so the rule now applies to every review
```
Any claim about product, API, query-language or configuration behaviour that your work depends on
... is checked on the docs server and cited
by URL. ... Never settle such a claim from memory
```
The removed contract section was gated: "opt-in: applies when the package says the artifact has content for the docs server's product". The new text has no gate. A reviewer of any diff must now run `search_internal_docs`, fetch a page and cite it for every API or config claim, or mark the claim unverified. This spends the tool budget and adds unsupported `unverified` markers on unrelated artifacts. The change says "The intent is unchanged", but this behaviour is different. The pointer in the contract ("when you need ... a product or API fact") is not a gate either.
Fix: restore the condition in `lookups.md`, for example "Applies only when the package says the artifact has content for the docs server's product", or keep the opt-in heading and gate in the contract pointer.

2. [needs more info · 3] **`.cursor/agents/references/reviewer-contract.md:7`** — the pointer path may not resolve
```
Lookups: follow `~/.cursor/agents/references/lookups.md` when you need code you cannot locate
```
The file is added at repo-relative `.cursor/agents/references/lookups.md`, but the pointer uses a home-directory path. `lookups.md` also reads server names from `~/.agent/config.json`, which is a different directory (`.agent`, not `.cursor`). If agents run from a checkout and `~/.cursor` isn't installed there, the pointer dangles and the lookup rules silently vanish. Does the install step copy `.cursor/agents/references/` to `~/.cursor/`, and does `~/.agent/config.json` exist where reviewers run? If not, the reviewer loses both the code-index preference and the fallback line.

3. [attention · 3] **`.cursor/agents/references/lookups.md:16`** — placement of the fallback line is owned in three places
```
Your own file says
where that line goes; without such a place, put it at the end.
```
The contract pointer says "Its `code search unreachable` line goes on the line after your `Assessment:` line." `lookups.md` says the persona file decides, with a default of "at the end". The contract's header also says it wins on output. A reviewer gets three placement rules. "At the end" also collides with the `### Findings: none` sentinel the parser needs last.
Fix: keep placement only in the contract, and in `lookups.md` say "put the line where your output contract says".

4. [nit · 3] **`.cursor/agents/references/lookups.md:17`** — harness tool names in a shared prompt
```
use the equivalent `Grep`/`Glob`/`Read` call
```
The same file is loaded by Cursor and Claude Code agents, where tool names differ. Naming the capability ("text search", "read the file") ports better. `search_internal_docs` is a specific MCP tool name and has the same issue. The risk is a wrong tool call on a harness that names them differently.

5. [nit · 2] **`.cursor/agents/references/lookups.md:25`** — fetching a cited page costs budget the rule doesn't account for
```
Search the docs (`search_internal_docs`), then fetch the page you cite.
```
Reviewers have a fixed tool-call budget, and this mandates at least two calls per claim. The file doesn't say which wins when the budget runs out. An agent may stop at the budget without marking the claim, or overrun it.
Fix: say that a claim left unchecked at the budget is marked `unverified (budget)`.