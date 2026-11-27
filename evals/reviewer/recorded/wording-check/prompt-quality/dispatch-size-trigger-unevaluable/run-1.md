Assessment: request-changes — the size trigger can't be evaluated by the orchestrator, and the path option conflicts with the PR-mode rule that bars file reads.

Read beyond the package: none (the directory holds only `dispatch.md`; `crew-reviewer` and `check-packages` are not in the package)

1. [blocking · 4] **`.cursor/agents/references/dispatch.md:31`** — PR mode forbids the file reads that path delivery requires
```
A persona must not use the local
checkout — no file reads, repository search, semantic search, or Explorer output, whatever the
```
Path delivery says "must be read in full before judging". A persona in PR mode that follows the PR-mode rule literally will not read `<persona>.in.md`, because that file sits in the local filesystem. It then reviews nothing, or returns `[needs more info]` that names a missing excerpt. The two rules collide, and the large packages that need path delivery are the ones most likely to be PR packages.
Fix: add to the PR-mode paragraph that reading the delivered package file is the one permitted file read, and that every other local read stays barred.

2. [attention · 4] **`.cursor/agents/references/dispatch.md:13`** — the size trigger has no threshold the orchestrator can check
```
**Package delivery: inline by default, by path when a package is too large to embed.**
...
Use it when embedding would push the orchestrator's own output past what the harness accepts —
```
"Too large" and "past what the harness accepts" give no number, and the orchestrator can't see the harness limit. The only evidence is one 640 KB example, which agents may copy as a threshold. Some orchestrators will embed and hit the limit. Others will switch to path delivery for small packages and lose the inline default.
Fix: state a byte or token threshold, for example "embed at or below N KB; above N KB use path delivery when conditions 1–3 hold". Put the 640 KB figure in as a rationale and say it is not the cutoff.

3. [attention · 3] **`.cursor/agents/references/dispatch.md:20`** — conditions 2 and the large-package case leave a gap
```
A run with no file access, such as the `claude -p` fallback, must embed.
```
If a package is too large to embed and the persona has no file access, the rule says to embed anyway. That is the case that fails the harness. No fallback is given, such as splitting the package, trimming excerpts, or stopping. The orchestrator is left to guess.
Fix: add what to do when the package is over the threshold and the run can't read files, for example "dispatch a file-capable persona or split the package per lens; do not drop evidence".

4. [attention · 3] **`.cursor/agents/references/dispatch.md:18`** — the rule leans on a gate that isn't in the package
```
passed the `check-packages` gate of
   `crew-reviewer`'s dispatch step
```
The text gives `check-packages` and `crew-reviewer`'s dispatch step as the owner of the package check. Neither is in the package, so I could not confirm that either exists or does what is claimed. If the gate does not check byte-for-byte equality, condition 1 promises more than it delivers.
Fix: point to the owning file and heading, and confirm the gate verifies the written file rather than the in-memory package.

5. [nit · 3] **`.cursor/agents/references/dispatch.md:22`** — the "delivery-independent" list restates rules held elsewhere
```
repeats only the delivery-independent
   instructions: reply text only, no artifact writes, the finding shape, and the mode.
```
The list copies the contract's return shape and the mode line. If either changes, this list falls out of date. It also omits the label vocabulary and the confidence scale, which the reader would otherwise get from the contract.
Fix: say "repeats only what is not in the package: the return-shape and mode lines", and point to the contract as the owner.