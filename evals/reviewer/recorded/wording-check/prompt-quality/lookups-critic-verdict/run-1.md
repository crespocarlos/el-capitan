Assessment: request-changes — the shared lookups file collides with the critic contract's last-line rule and its 5-finding cap, and its fallback notes have no place in the critic output.

Read beyond the package: none (the contract was read in full; a grep for the lookup terms found no other files)

1. [blocking · 4] **`.cursor/agents/references/lookups.md:18`** — fallback note placement collides with the critic contract's last-line rule
```
say so in one line of your output: `code search unreachable: used text search`. Your own file says
where that line goes; without such a place, put it at the end.
```
The critic contract says "a reply whose last line is not the Verdict line is treated as incomplete, not as approval." The critic's own file may not name a place for the note, and the contract does not name one either. The default "put it at the end" then puts the note after `Verdict: N finding(s)`. The specwriter treats that reply as incomplete and relaunches the critic, or drops the review.
Fix: In `critic-contract.md`, say where the note goes, for example "put lookup notes before the Verdict line; the Verdict line stays last". Alternatively, change the default in `lookups.md` to "before any closing outcome line".

2. [attention · 3] **`.cursor/agents/references/lookups.md:28`** — `unverified` marking has no slot in the critic output
```
`unverified (docs server unreachable)` and leave it unsettled rather than deciding it from code or
memory.
```
The critic output is grouped as Critical, Important or Consider, with at most 5 findings. A critic with no docs server must mark claims unverified, but the contract does not say whether such a claim is a finding, which severity it takes, or whether it uses up one of the 5 slots. Critics will handle it differently, or will drop the claim to save a slot.
Fix: Add one line to the critic contract's Evidence section, for example "An unverified claim is a Consider finding and counts toward the 5."

3. [attention · 3] **`.cursor/agents/references/critic-contract.md:10`** — the contract keeps its own evidence rule next to the pointer
```
Verify the spec's claims against the codebase, and flag a claim you could not verify instead of
assuming it.
```
`lookups.md` says "Never settle such a claim from memory" and "rather than deciding it from code". The contract tells the critic to verify product claims "against the codebase". For a product or API claim, a critic cannot tell whether code or the docs server wins. The pointer reads as an extra rule, not a replacement for the old one.
Fix: Scope the contract line to spec claims about this repo's code, and say the lookups file governs product and API facts.

4. [attention · 3] **`.cursor/agents/references/lookups.md:7`** — pointers that may not resolve for the recipient
```
The servers are the ones named in `~/.agent/config.json` `mcp`: `code_search` for the code index,
`docs` for the docs server.
```
`lookups.md` sends the critic to `~/.agent/config.json` for server names. The contract points to `~/.cursor/agents/references/lookups.md`, but the file is added under the repo's `.cursor/agents/`. The two are the same path only if the repo is installed at `~`. The `docs` server name does not match the tool name `search_internal_docs`, and no fetch tool is named. I found no `config.json` in the package, so I could not check it.
Fix: Name the tool names the agents actually get, or say "capability" instead of a server name. Confirm the install path, or use a path relative to the repo.

5. [attention · 3] **`.cursor/agents/references/critic-contract.md:8`** — nothing measures the change
```
Lookups: follow `~/.cursor/agents/references/lookups.md` when you need code you cannot locate or a product or API fact.
```
The diff changes critic behaviour (it adds docs lookups and a fallback note) and the parsed Verdict-last gate, with no eval case or check. Finding 1 would go unnoticed until a run came back incomplete.
Fix: Add a case where code search or docs is unavailable and check that the reply still ends with the Verdict line.