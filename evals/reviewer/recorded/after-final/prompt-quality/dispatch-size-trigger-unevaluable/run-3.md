Assessment: comment — the change fits the problem (a duplicate-output cost), but the size trigger can't be evaluated and the gate it depends on isn't in the package.
Read beyond the package: none. The working directory holds only `dispatch.md`, and a grep for `check-packages` and `Package delivery` found only this file.

1. [attention · 4] **`.cursor/agents/references/dispatch.md:13`** (h1) — "too large to embed" gives the orchestrator no measurable trigger
```
**Package delivery: inline by default, by path when a package is too large to embed.**
...
Use it when embedding would push the orchestrator's own output past what the harness accepts —
one measured five-persona review was 640 KB, roughly 160k tokens of duplicate output.
```
The orchestrator doesn't know the harness's output limit, and the only number given is one past incident. A 100 KB package may go inline in one run and by path in another. Some orchestrators will never switch, and others will switch on every review, which removes the inline default. The 640 KB figure is a single anecdote, so it reads as a threshold and invites agents to copy it.
Fix: state a concrete rule, such as an embed ceiling in KB or tokens, or a rule like "by path whenever the total across personas exceeds N". Name the owner of that number, and keep the incident out of the rule or label it as background.

2. [needs more info · 3] **`.cursor/agents/references/dispatch.md:18`** — `check-packages` gate and `crew-reviewer` dispatch step don't resolve in this package
```
passed the `check-packages` gate of
   `crew-reviewer`'s dispatch step, so the file read is byte-for-byte the package the protocol checked.
```
Condition 1 depends on a gate and on a step of another file. If `check-packages` doesn't run before dispatch, or isn't named that way, the orchestrator can't satisfy condition 1. It then either always embeds or skips the check. Does `crew-reviewer` define a `check-packages` gate that runs before dispatch and writes `<persona>.in.md` under `$REVIEW_ROOT`? If it doesn't, the path route is unusable and the instruction dangles.

3. [attention · 3] **`.cursor/agents/references/dispatch.md:22`** — the path-delivery prompt drops the PR-mode restriction, and the read-only sentence lost "repository reads"
```
3. The dispatch prompt names the absolute package path, ... and repeats only the delivery-independent
   instructions: reply text only, no artifact writes, the finding shape, and the mode.
```
The old text said read-only personas lose repository reads. The new text drops that and says a `readonly` subagent "still reads". A persona that now has file access, plus "repeats only" these four items, may read the local checkout. In PR mode that violates "A persona must not use the local…". PR mode appears only as "the mode", so the restriction may not be repeated.
Fix: add "and the PR-mode rule that the package is the only repository evidence" to the list in condition 3, or have the rule point to the PR-mode paragraph.

4. [nit · 2] **`.cursor/agents/references/dispatch.md:28`** — the `persist --strict` pair requirement is restated here
```
`<persona>.in.md` and `<persona>.out.md` stay the pair
`persist --strict` requires
```
The pair requirement belongs to `persist`. If it changes, this copy goes stale, though the cost is small. Fix: point to `persist` instead of restating it.