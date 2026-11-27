Assessment: request-changes — the by-path option has no trigger the orchestrator can evaluate, and the text it adds conflicts with the PR-mode rule and with the "audit artifact" claim.
Read beyond the package: none (grep of the working directory found only dispatch.md; `crew-reviewer`, `check-packages` and `persist` are not in the package)

1. [attention · 4] **`.cursor/agents/references/dispatch.md:25`** — "too large to embed" has no measurable trigger
```
Use it when embedding would push the orchestrator's own output past what the harness accepts —
one measured five-persona review was 640 KB, roughly 160k tokens of duplicate output.
```
The orchestrator cannot tell when it is past "what the harness accepts". The threshold appears nowhere, and the only anchor is a single 640 KB incident. Agents will either embed until the call fails or take the path route for any package that is moderately large. The "inline by default" wording and the use-when sentence also differ. The rule is written from one incident, which makes it overfit.
Fix: State a size threshold, for example "package over N KB", and a fallback for when an embed fails. Alternatively, allow path delivery whenever conditions 1–3 hold, and say so.

2. [attention · 3] **`.cursor/agents/references/dispatch.md:18`** — condition 2 relies on a capability the orchestrator may not be able to see
```
2. The persona can read files — Cursor, or Claude Code with `Read` (a `readonly` subagent still
reads). A run with no file access, such as the `claude -p` fallback, must embed.
```
The old text said "repository reads ... are unavailable" for read-only runs, and the edit removes that phrase. Cursor Ask mode was previously named as a read-only mode, and the new text now claims Cursor can read. A persona in Ask mode, or a subagent whose `tools:` line omits `Read`, receives a path it cannot open. It then reviews nothing, or it guesses from the task description. The text gives no way to tell, and no handling for a persona that reports it could not read the file.
Fix: Require the persona to open with `status: failed` if it cannot read the path. Have the orchestrator re-dispatch inline in that case. Name which Cursor modes count as able to read.

3. [attention · 3] **`.cursor/agents/references/dispatch.md:31`** — PR-mode rule and the new path delivery are not reconciled
```
**PR mode:** the package is the only repository evidence a persona may use.
```
Path delivery tells the persona to "read in full" a file in `$REVIEW_ROOT`. Meanwhile PR mode says the package is the only evidence allowed and that the persona "must not use the local" checkout, and the persona now has live file access. It is unclear whether reading the `.in.md` file counts as using the package or as using local files. A persona with `Read` may also wander into the checkout.
Fix: Add one line saying that in PR mode the persona reads only the named package path and nothing else.

4. [nit · 3] **`.cursor/agents/references/dispatch.md:22`** — the list of instructions to repeat in the dispatch prompt is partly redundant
```
repeats only the delivery-independent instructions: reply text only, no artifact writes, the finding shape, and the mode.
```
The finding shape and mode are also stated in the contract inside the package. This restates content that another loaded file owns, so the copies can drift apart.
Fix: Point to the contract as the owner of the finding shape. Repeat only the path, "read in full", and "reply text only".

5. [needs more info · 2] **`.cursor/agents/references/dispatch.md:27`** — nothing in the change measures this rule
```
`<persona>.in.md` and `<persona>.out.md` stay the pair `persist --strict` requires, and the recorded package remains the one the persona read.
```
The claim that `check-packages` gives a "byte-for-byte" guarantee, and that `persist --strict` still passes, depends on tooling outside this package. Is there a check or test that a path-delivered run produces a valid pair? If the persona reads a stale or truncated file, nothing detects it. The audit trail would then record a package that the persona never saw in full.