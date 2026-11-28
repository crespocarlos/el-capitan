# Shared dispatch instructions

Run orchestrators inline. Dispatch personas only from the main session: use Cursor Task or Claude
Agent, and preserve inherited model selection. `REVIEW_ROOT` is the review directory `crew-reviewer`
resolved.

**Dispatch a persona by its agent type.** In Claude Code, pass `subagent_type: reviewer-<name>` (the
critics and explorers by their own names), so the persona's frontmatter applies: its `tools:`
allowlist grants the read tools and the docs and code-search MCP servers install rendered into it,
and nothing else. A generic agent told to read the persona file gets every session tool instead, so
never dispatch that way. When the agent type is not registered in this session, stop: tell the user
the agents are not installed for this config dir and to re-run `install.sh`.

**The `claude -p` fallback** is only for a harness with no native subagent dispatch at all. It runs a
top-level session that does not read the persona's frontmatter, so the persona gets that session's
tools, not its allowlist; name that in the report's `### Reviewers` section.

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
rejected for size, or when the package exceeds **120,000 bytes**, above which an inline failure is
predictable. Below the threshold, send inline rather than guess an output bound; a failure is how to
find out. A package delivered by path is still the audit artifact: `<persona>.in.md` and
`<persona>.out.md` stay the pair `persist` requires, and the recorded package remains the one
the persona read. Name the delivery, and for a by-size delivery its byte count, in the report's
`### Reviewers` section.

**PR mode:** the package is the only repository evidence a persona may use. Every code excerpt must
identify `path:line@headSHA7` and come from `gh api` at that head. A persona must not use the local
checkout — no file reads, repository search, code-index search, or Explorer output, whatever the
harness names those tools — to verify a PR claim. It may return `[needs more info]` only when it
names the missing PR-head path or excerpt. The one exception, repository guidance the orchestrator
collects, is in [PR review mode](~/.cursor/agents/crew-reviewer/references/pr-mode.md).

**The reply text is the only thing the orchestrator receives.** A persona that writes findings into
a file, a scratch artifact, or a summary block ("findings delivered above", "see next") hands back
nothing. Classify the run as incomplete and resume it once under the rule below — a summary block that
points backwards is the pointer case, so it gets a resume, not a relaunch.

**A reply that points at an earlier turn is not a reply.** A Cursor Task persona can put its findings
in an intermediate turn and end with a summary that says the list appeared earlier; the orchestrator
receives only the final message, so that run looks empty while the work was done. Resume that persona
once — a resume keeps the conversation, a relaunch does not — with one instruction: re-emit the
complete list in this final message, in the finding shape, nothing else. The resumed turn's list
replaces the pointer (the hook below), so the audit trail holds the findings rather than a reference
to them. If the resume also points backwards, persist
the failure artifact and name the gap under `### Reviewers`.

**A dispatch that ends with no reply is resumed once, never re-dispatched.** This holds for every
persona and spec critic, from `crew-reviewer` and `crew-specwriter` alike. A persona stopped by its
turn limit still holds what it read, and a relaunch starts cold and spends the budget again. Resume
it once with `deliver now: write your findings (a critic: your critique) from what you have read,
and name what you did not check`. If it again returns nothing,
persist the failure artifact and name the gap (`crew-specwriter`: name the lens and what it could not
check). Cursor's Task call resumes too (`resume`). Only a harness that cannot resume re-dispatches
once, with that `deliver now` line before the same prompt, as its one retry.

**The hook saves the reply, in Claude Code and Cursor.** Each dispatch carries the marker line from
`crew-review-findings.py expect` ([packaging](~/.cursor/agents/crew-reviewer/references/packaging.md),
"The reply marker"), and the subagent-stop hook saves the reply with its harness, agent id and
model. The latest reply to a marker is the reply: a resume's becomes `<persona>.out.md`, the earlier
one `<persona>.prev.md`. A dispatch is answered when `<persona>.out.md` exists and no
`<persona>.unanswered` sits beside it; otherwise it is pending, so resume it (rule above), and save
by hand only an `.out.md` still missing after the agent stops. The hook keeps an `.out.md` that
answers another marker (it logs a name collision): re-dispatch under a free name or directory, never
`save-out` over it. `--degraded` stays a manual flag.

**Saving replies with `save-out`** (Codex, the `claude -p` fallback, and a missing `.out.md`).
Personas never write their own artifacts, and the orchestrator
does not re-type a reply into `<persona>.out.md` either: it pipes the reply to the tool, which stores
the raw bytes and a provenance record beside them:

```bash
~/.agent/bin/crew-review-findings.py save-out --review-dir "$REVIEW_ROOT" --persona <persona> \
  --harness <cursor|claude-code|codex> [--agent-id <id>] [--model <id>] [--resume] [--degraded] < <reply file>
```

- The source is a file the harness already holds for the persona's final message when it has one
  (a Task or background-agent output file), so the reply is not emitted a second time. With none,
  write the reply verbatim to a scratch file first. Never a digest or a hand-edited copy: `persist` refuses a condensed digest
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

A persona that judges the artifact outside its lane (no prompt files, no user-facing surface) emits
the `### Findings: none` line plus one sentence of reason. It does not end with a bare statement of disinterest,
because the orchestrator treats a response with neither a finding nor this sentinel line as
incomplete and relaunches it.

A persona may not treat an unverified absence or a claim that depends on blocked reads as a grounded
finding; mark it `[needs more info]` and name the blocked read. The orchestrator remains responsible
for verifying findings against the authoritative repository before consolidation.

**The handoff trailer is one line** at the very end of a reply, `> Next: …`, naming `crew <verb>`
commands and nothing else: no summary of the work, no reassurance, no second sentence. A PR review's
trailer names a person's action instead ([output
formats](~/.cursor/agents/crew-reviewer/references/output-formats.md)). Authoring rule, for editing
this repository's prompts: the shape `crew-lint` enforces is in `.agent/tools/AGENTS.md`.
