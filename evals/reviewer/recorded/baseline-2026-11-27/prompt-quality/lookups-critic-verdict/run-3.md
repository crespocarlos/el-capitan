Assessment: request-changes — the critic contract's output format collides with the new reference's "put it at the end" fallback, and the pointer may not resolve for a dispatched critic.

1. [blocking · 4] **`.cursor/agents/references/lookups.md:19`** — fallback note placement collides with the critic's Verdict-last rule
```
say so in one line of your output: `code search unreachable: used text search`. Your own file says
where that line goes; without such a place, put it at the end.
```
`critic-contract.md` says "a reply whose last line is not the Verdict line is treated as incomplete, not as approval." It names no place for the note, so a critic follows the default and puts the note at the end, after `Verdict:`. The specwriter then reads the reply as incomplete. The note also isn't a finding, so it fits none of the Critical/Important/Consider groups. Related: the pointer carries no placement rule of its own.
Fix: In `critic-contract.md`, say where the note goes, for example "put lookup notes before the Verdict line; they do not count toward the 5-finding cap." Alternatively, change the default in `lookups.md` to "before any closing outcome line".

2. [blocking · 4] **`.cursor/agents/references/lookups.md:30`** — "leave it unsettled rather than deciding it from code" contradicts the contract's codebase verification
```
`unverified (docs server unreachable)` and leave it unsettled rather than deciding it from code or
memory.
```
`critic-contract.md` says "Verify the spec's claims against the codebase, and flag a claim you could not verify instead of assuming it." A critic checking a spec claim about query behaviour is told both to verify against the code and not to settle it from code. The contract's unverifiable-claim path and the reference's `unverified` marker are also two different flags. The output has no slot for either, because findings are capped at 5 and grouped by severity.
Fix: Scope the rule: "Code may show what the code does, but it does not confirm documented product behaviour; mark the claim `unverified (docs server unreachable)` and do not report it as confirmed." Then make the contract's flag the same marker.

3. [attention · 3] **`.cursor/agents/references/critic-contract.md:8`** — the pointer path may not resolve
```
Lookups: follow `~/.cursor/agents/references/lookups.md` when you need
```
The new file lives at the repo-relative `.cursor/agents/references/lookups.md`, but the pointer uses a home-directory `~/.cursor/...` path. A critic dispatched in another workspace may not have that file, and the instruction fails silently. The contract is appended to the dispatch prompt, so the recipient only sees the path, not the content.
Fix: Confirm how the other references are addressed, and use that convention. Otherwise have the specwriter inline the file into the dispatch.

4. [attention · 3] **`.cursor/agents/references/lookups.md:17`** — harness tool names in a shared prompt
```
use the equivalent `Grep`/`Glob`/`Read` call
```
`Grep`/`Glob`/`Read` are Claude Code names, and this reference is loaded by agents under `.cursor`. `search_internal_docs` and the config path `~/.agent/config.json` are likewise hardcoded.
Fix: Name the capabilities, for example "text search, file search, read the file". Keep the MCP tool names only if they are the real server contract.

5. [nit · 2] **`.cursor/agents/references/critic-contract.md:8`** — the lookup guidance is added to the Evidence section with no purpose
The trigger "when you need code you cannot locate" sits as a bare "Lookups:" label ahead of the existing verification rule. A reader may skip the pointer when a claim is plainly about the code. The cost is inconsistent lookups.
Fix: Put the pointer after the verification sentence and tie it to it.