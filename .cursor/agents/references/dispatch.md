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

**When:** attempt inline first. By path only when that inline send truncates, fails to arrive, or is
rejected for size, or when the package exceeds **120,000 bytes** — above that the inline send is a
call whose failure is predictable rather than a measurement worth paying for. A five-persona review
measured at 640 KB (about 160k tokens of duplicate output) is the shape that hits both. Below the
threshold, a failure is still the way to find out: guessing an output bound is the mistake this rule
exists to prevent. A package delivered by path is still the audit artifact: `<persona>.in.md` and
`<persona>.out.md` stay the pair `persist` requires, and the recorded package remains the one
the persona read. Name the delivery, and for a by-size delivery its byte count, in the report's
`### Reviewers` section.

**PR mode:** the package is the only repository evidence a persona may use. Every code excerpt must
identify `path:line@headSHA7` and come from `gh api` at that head. A persona must not use the local
checkout — no file reads, repository search, code-index search, or Explorer output, whatever the
harness names those tools — to verify a PR claim. It may return `[needs more info]` only when it
names the missing PR-head path or excerpt.

One exception, and it belongs to the orchestrator rather than the persona: `crew-reviewer` may run
`crew-agent-context.py` to collect repository guidance (`AGENTS.md`, `CLAUDE.md`) and place the result in
the package. Guidance describes the reviewer's own conventions rather than the change, so it is
legitimate context. It also comes from the local checkout, not the PR head, and therefore is **not
PR-head evidence**: when the PR itself changes a guidance file, treat the collected text as
approximate and cite a head excerpt for any conclusion that depends on the rule being added. A
persona reads guidance from its package, never the working tree, so the evidence trail in
`<persona>.in.md` stays complete.

**The reply text is the only thing the orchestrator receives.** A persona that writes findings into
a file, a scratch artifact, or a summary block ("findings delivered above", "see next") hands back
nothing. Classify the run as incomplete and resume it once under the rule below — a summary block that
points backwards is the pointer case, so it gets a resume, not a relaunch.

**A reply that points at an earlier turn is not a reply.** A Cursor Task persona can put its findings
in an intermediate turn and end with a summary that says the list appeared earlier; the orchestrator
receives only the final message, so that run looks empty while the work was done. Resume that persona
once — a resume keeps the conversation, a relaunch does not — with one instruction: re-emit the
complete list in this final message, in the finding shape, nothing else. Then save what it returns
(`save-out --resume`, below); the resumed turn's list replaces the pointer in place, so the audit
trail holds the findings rather than a reference to them. If the resume also points backwards, persist
the failure artifact and name the gap under `### Reviewers`.

**Saving replies with `save-out`.** Personas still never write their own artifacts and the reply text is still the only thing the
orchestrator receives. What `save-out` removes is the second write: the orchestrator no longer
re-types each reply into `<persona>.out.md`. It pipes the reply to the tool, which stores the raw
bytes and a provenance record beside them:

```bash
~/.agent/bin/crew-review-findings.py save-out --review-dir "$REVIEW_ROOT" --persona <persona> \
  --harness <cursor|claude-code|codex> [--agent-id <id>] [--model <id>] [--resume] [--degraded] < <reply file>
```

- The source is a file the harness already holds for the persona's final message when it has one
  (a Task or background-agent output file), so the reply is not emitted a second time; with none,
  pass the reply on stdin. Never a digest or a hand-edited copy: `persist` refuses a condensed digest
  and a reply whose hash no longer matches its record.
- Record the agent id and model the harness reports; leave a flag out when it reports nothing (stored
  as `null`, never guessed). `--resume` marks the one allowed re-emission of the same persona.
- Fewer agents than lenses (one fork playing every lens, or two personas answered by one agent id)
  is a degraded review: pass `--degraded` when you played the lens yourself. The review then opens
  with `Degraded: 1 agent, N lenses` and its verdict is capped at `WARN`; `BLOCK` stays `BLOCK`.
- A review directory without records (created before `save-out`) still persists; its report says
  `provenance: absent (legacy)`. Tamper evidence applies to new reviews only.

Every dispatch prompt therefore states the required shape and requires a flat numbered list of
findings, each beginning with its
severity label and carrying a `path:line` anchor. A conversational summary is never a zero-findings
verdict; only the `### Findings: none` line is.

When the package has a hunk index, each `[blocking]` and `[attention]` finding also names the hunk
ids that cause it after its anchor (`src/a.ts:42 (h7)`). A Reading map orders those ids; without
one, the package still supplies a compact hunk-to-file reference.

The compact reference comes from `hunks.index.md` (ids, files, line ranges, size flags), never from
`hunks.md`, whose per-hunk bodies re-quote a diff the package already carries. `hunks.md` is for the
layer-mapping pass, which sees the index only and no diff. The dispatch prompt states this.

A persona with no findings ends its response with the line `### Findings: none`.

A persona that judges the artifact outside its lane (no prompt files, no user-facing surface) emits
the same line plus one sentence of reason. It does not end with a bare statement of disinterest,
because the orchestrator treats a response with neither a finding nor this sentinel line as
incomplete and relaunches it.

A persona may not treat an unverified absence or a claim that depends on blocked reads as a grounded
finding; mark it `[needs more info]` and name the blocked read. The orchestrator remains responsible
for verifying findings against the authoritative repository before consolidation.

## The handoff trailer

A handoff is one line at the very end of a reply, written as `> Next: …`. It names one or more
`crew <verb>` commands and nothing else: no summary of the work, no reassurance, no second sentence
about what the reader might also consider. `crew-lint` reads every skill, agent, and rule file and
fails one whose trailer is missing from the end, duplicated, or names a verb `crew-router.mdc` has no
row for, so a handoff that survives review is one a session can act on by pasting it.

A stage with several outcomes quotes one trailer per outcome in its own documentation instead of
emitting an unquoted one — `crew-address-review` prints a different line per mode, and each of
those sits inside backticks. A `Next:` outside a quoted trailer, or anywhere in a file that emits no
trailer at all, is not a handoff: the lint reports it, because a reader cannot tell it from one.

The single exception is a PR review, whose findings are someone else's to apply: its trailer is
`paste the bodies from comments.md onto PR #<n>`, naming a person's action rather than a command.

