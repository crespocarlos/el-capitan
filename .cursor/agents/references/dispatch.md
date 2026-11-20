# Shared dispatch instructions

Run orchestrators inline. Dispatch personas only from the main session: use Cursor Task or Claude
Agent, preserve inherited model selection, and use the documented fallback only when native dispatch
is unavailable.

Reviewer personas may run read-only: Cursor Ask mode, or a Claude Code read-only subagent, where
artifact writes are unavailable, and the `claude -p` fallback likewise returns only stdout. Dispatch
prompts must carry the immutable evidence the assigned lens needs — diff, contract, relevant file
excerpts, and explorer findings — delivered inline, or by path under **Package delivery** below.
Never rely on a persona writing its own artifact. A path to a diff file on its own is never evidence:
it is either the whole written package under that section's conditions, or nothing.

**Package delivery: inline by default; by path only after an inline send fails.** Inline means the
package is the dispatch prompt. Reading the written `<persona>.in.md` back is a sanctioned
alternative, not a deviation, when all three hold:

1. The package was written to `$REVIEW_ROOT` and passed the `check-packages` gate in
   `crew-reviewer`'s dispatch step, so the file read is byte-for-byte the package the protocol
   checked.
2. The persona can read files — Cursor, or Claude Code with `Read` (a `readonly` subagent still
   reads). A run with no file access, such as the `claude -p` fallback, must embed.
3. The dispatch prompt names the absolute package path, states that this file is the persona's whole
   package and must be read in full before judging, and repeats only the delivery-independent
   instructions: reply text only, no artifact writes, the finding shape, and the mode.

**When:** attempt inline first. By path only after that inline send truncates, fails to arrive, or is
rejected for size — an observable event, and self-correcting where guessing at an output bound is not.
A five-persona review measured at 640 KB (about 160k tokens of duplicate output) is the shape that
triggers it. A package delivered by path is still the audit artifact: `<persona>.in.md` and
`<persona>.out.md` stay the pair `persist --strict` requires, and the recorded package remains the one
the persona read. Name the delivery in the report's `### Reviewers` section.

**PR mode:** the package is the only repository evidence a persona may use. Every code excerpt must
identify `path:line@headSHA7` and come from `gh api` at that head. A persona must not use the local
checkout — no file reads, repository search, code-index search, or Explorer output, whatever the
harness names those tools — to verify a PR claim. It may return `[needs more info]` only when it
names the missing PR-head path or excerpt.

One exception, and it belongs to the orchestrator rather than the persona: `crew-reviewer` may run
`agent-context.py` to collect repository guidance (`AGENTS.md`, `CLAUDE.md`) and place the result in
the package. Guidance describes the reviewer's own conventions rather than the change, so it is
legitimate context. It also comes from the local checkout, not the PR head, and therefore is **not
PR-head evidence**: when the PR itself changes a guidance file, treat the collected text as
approximate and cite a head excerpt for any conclusion that depends on the rule being added. A
persona reads guidance from its package, never the working tree, so the evidence trail in
`<persona>.in.md` stays complete.

**The reply text is the only thing the orchestrator receives.** A persona that writes findings into a
file, a scratch artifact, or a summary block ("findings delivered above", "see next") hands back
nothing. Classify the run as incomplete and resume it once under the rule below — a summary block that
points backwards is the pointer case, so it gets a resume, not a relaunch.

**A reply that points at an earlier turn is not a reply.** A Cursor Task persona can put its findings
in an intermediate turn and end with a summary that says the list appeared earlier; the orchestrator
receives only the final message, so that run looks empty while the work was done. Resume that persona
once — a resume keeps the conversation, a relaunch does not — with one instruction: re-emit the
complete list in this final message, in the finding shape, nothing else. Then write what it returns to
`<persona>.out.md`; the resumed turn's list replaces the pointer in place, so the audit trail holds the
findings rather than a reference to them. If the resume also points backwards, persist the failure
artifact and name the gap under `### Reviewers`.

Every dispatch prompt therefore states the required shape and requires a flat numbered list of
findings, each beginning with its
severity label and carrying a `path:line` anchor. A conversational summary is never a zero-findings
verdict; only the `### Verdict: no findings` line is.

When the package has a hunk index, each `[blocking]` and `[attention]` finding also names the hunk
ids that cause it after its anchor (`src/a.ts:42 (h7)`). A Reading map orders those ids; without
one, the package still supplies a compact hunk-to-file reference.

The compact reference comes from `hunks.index.md` (ids, files, line ranges, size flags), never from
`hunks.md`, whose per-hunk bodies re-quote a diff the package already carries. `hunks.md` is for the
layer-mapping pass, which sees the index only and no diff. The dispatch prompt states this.

A persona with no findings ends its response with the line `### Verdict: no findings`.

A persona that judges the artifact outside its lane (no prompt files, no user-facing surface) emits
the same line plus one sentence of reason. It does not end with a bare statement of disinterest,
because the orchestrator treats a response with neither a finding nor this verdict line as
incomplete and relaunches it.

A persona may not treat an unverified absence or a claim that depends on blocked reads as a grounded
finding; mark it `[needs more info]` and name the blocked read. The orchestrator remains responsible
for verifying findings against the authoritative repository before consolidation.
