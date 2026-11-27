Assessment: request-changes — the shared reference's fallback rule ("without such a place, put it at the end") collides with the critic contract's "last line must be the Verdict line", so a critic that follows both is marked incomplete.

Read beyond the package: critic-contract.md (full file), grep for lookups/code_search/search_internal_docs

1. [blocking · 4] **`.cursor/agents/references/lookups.md:17`** — fallback note placement collides with the Verdict-last rule
```
say so in one line of your output: `code search unreachable: used text search`. Your own file says
where that line goes; without such a place, put it at the end.
```
The critic contract says "a reply whose last line is not the Verdict line is treated as incomplete, not as approval", and it names no place for the note. A critic whose code index is down follows lookups.md and puts the note at the end. That makes the note the last line, so the specwriter reads the reply as truncated and relaunches the critic. The Verdict instruction is also weakened if the critic puts the note after it.
Fix: Add a slot to the contract, e.g. "Put any lookup note on its own line before the Verdict line." Change the lookups.md default to "before your final outcome line, if your file defines one, otherwise at the end".

2. [attention · 4] **`.cursor/agents/references/critic-contract.md:8`** — the critic's "unverified" marker has no place in the Critical/Important/Consider format and the 5-finding cap
```
Lookups: follow `~/.cursor/agents/references/lookups.md` ...
```
The reference says to mark a claim `unverified (docs server unreachable)` and "leave it unsettled". The contract allows only severity-grouped findings, capped at 5, and the line after it says "flag a claim you could not verify". It doesn't say whether an unverified claim is a finding, which severity it takes, or whether it counts toward the cap. Critics will handle it differently: some drop the claim, some spend cap slots on it, some put it outside the grouping and break the Verdict count.
Fix: In the contract's Evidence section, add: "An unverified claim is a Consider finding that counts toward the cap, and the Verdict count includes it."

3. [attention · 3] **`.cursor/agents/references/critic-contract.md:8`** — the pointer's `~` path may not resolve, and the critic's budget is unaddressed
```
follow `~/.cursor/agents/references/lookups.md`
```
The file is added under the repo's `.cursor/agents/references/`. A `~/` path resolves to the user's home directory, which holds this file only if the repo is installed there. The critic also needs a read for it, and a critic with a tight tool budget may skip it. lookups.md itself says "Your own file still sets your budget". The contract sets the budget, but this diff gives no cost for the extra read. Further, `~/.agent/config.json` is cited as a source of server names, and the agent may be unable to read it.
Fix: Use the same path form as other references in this repo. State that the lookups read doesn't count against the budget, or inline the two-line fallback rule in the contract.

4. [attention · 3] **`.cursor/agents/references/lookups.md:24`** — "Never settle such a claim from memory" and "Search the docs... then fetch the page you cite" force docs calls on every spec claim
```
Any claim about product, API, query-language or configuration behaviour that your work depends on ... is checked on the docs server and cited by URL.
```
A critic reviewing a spec that has many such claims is capped at 5 findings and a tool budget. Under this rule it must make two docs calls per claim, and it has no way to prioritise. The rule has no scope or stopping point. The reason ("a guessed option reads the same as a verified one") is given, but no handling exists for a budget that runs out first.
Fix: Say "check the claims that decide a finding first; when the budget runs out, mark the rest unverified".

5. [nit · 3] **`.cursor/agents/references/lookups.md:20`** — the shared reference names the `search_internal_docs` tool and the `mcp` config key
Tool names are pinned in a shared file while the surrounding text says "the docs server". If the server renames the tool, every agent that loads this file reads a stale name. Say "the docs server's search tool" and let the harness supply the name.

6. [needs more info · 2] **no eval or check covers the contract change**
The Verdict line is parsed by the specwriter, and this diff changes what critics may emit near it. Is there a check, such as a critic-output regression case with the code search down, that catches a reply ending on the lookup note? Without one, finding 1 would show up only as relaunch loops in production.