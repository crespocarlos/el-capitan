Assessment: request-changes — the by-path option is sound, but its size trigger can't be evaluated at dispatch time, and the new rule collides with the PR-mode rule.
Read beyond the package: dispatch.md (full), grep for check-packages/REVIEW_ROOT (only dispatch.md; `crew-reviewer` is not in the package)

1. [attention · 4] **`.cursor/agents/references/dispatch.md:26`** — Size trigger has no threshold, and "too large to embed" is unevaluable
```
Use it when embedding would push the orchestrator's own output past what the harness accepts —
one measured five-persona review was 640 KB, roughly 160k tokens of duplicate output.
```
The orchestrator doesn't know what the harness accepts. The only anchor is one 640 KB incident, so agents will either never use path delivery or copy that figure as the cutoff. The header says "by path when a package is too large to embed", while the body says to use it when the total output of all personas would overflow. Those are two different tests, one per package and one per dispatch. A 100 KB package sent to five personas is 500 KB of output, and it is unclear which test applies. Fix: state a concrete, general threshold, such as a per-package byte count or a total across personas. Name where the number lives (for example, a `crew-reviewer` constant), and say which quantity is measured. Drop the incident as the definition.

2. [attention · 3] **`.cursor/agents/references/dispatch.md:22`** — Condition 3 conflicts with the "PR mode" rule and with the contract's evidence rules
```
3. The dispatch prompt names the absolute package path, states that this file is the persona's whole
   package ... 
**PR mode:** ... A persona must not use the local checkout — no file reads, repository search...
```
PR mode forbids file reads "whatever the harness names those tools". Path delivery requires the persona to read a local file with `Read`. A literal reader in PR mode with a by-path package can't tell whether reading `<persona>.in.md` counts as a forbidden file read. It may refuse to read the package, or it may read it and then also search the checkout. Fix: add to PR mode an exception for the package file only, for example "the one named package path is the sole permitted read; no other file reads".

3. [attention · 3] **`.cursor/agents/references/dispatch.md:15`** — Delivery rule is split between this file and `crew-reviewer`, with a dangling reference
```
passed the `check-packages` gate of `crew-reviewer`'s dispatch step
```
`crew-reviewer` and `check-packages` are not in this package, so I couldn't confirm that the gate or step exists. This file also restates the artifact pair (`<persona>.in.md` / `.out.md`, `persist --strict`) that `crew-reviewer` presumably owns, which can drift. Fix: confirm that `crew-reviewer` defines the gate. Replace the restatement in the last sentence with a pointer to that owner.

4. [nit · 3] **`.cursor/agents/references/dispatch.md:23`** — The list of instructions to repeat is partial, with no handling for an unreadable file
```
repeats only the delivery-independent instructions: reply text only, no artifact writes, the finding shape, and the mode.
```
The list omits the lens and label vocabulary. It also doesn't say what the persona should do if the path read fails or is truncated. A persona that can't read the file may review from nothing and issue `### Findings: none`. Fix: add "if the file can't be read in full, reply `status: failed`".