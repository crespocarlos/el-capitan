Assessment: request-changes — the rule that decides when to switch to path delivery cannot be evaluated by the orchestrator, so the default stays inline and the 640 KB problem remains.

1. [attention · 4] **`.cursor/agents/references/dispatch.md:28`** — The size trigger has no threshold the orchestrator can check
```
Use it when embedding would push the orchestrator's own output past what the harness accepts —
one measured five-persona review was 640 KB, roughly 160k tokens of duplicate output.
```
The orchestrator doesn't know "what the harness accepts". The heading says "too large to embed", and the 640 KB figure is one anecdote, not a limit. Different models will pick different cutoffs. Some will keep embedding until the output fails. Others will use path delivery on small packages, which loses the inline guarantee for no benefit. The text also doesn't say whether embedding is still required when conditions 1–3 hold but the package is small.
Fix: Give a measurable rule, such as "when the package size times the number of personas exceeds N KB, deliver by path", and state N. Keep the 640 KB figure as the motivating example. Say that when the package is under N or any condition fails, the package must be embedded.

2. [attention · 3] **`.cursor/agents/references/dispatch.md:18`** — Condition 1 depends on a gate this change does not show
```
1. The package was written to `$REVIEW_ROOT` and passed the `check-packages` gate of
   `crew-reviewer`'s dispatch step, so the file read is byte-for-byte the package the protocol checked.
```
The only match for `check-packages` in the supplied files is this line. The files in the working directory don't show that the gate exists, what it verifies, or whether it ran before dispatch. If the gate doesn't compare bytes, "byte-for-byte" is an unsupported claim. If `crew-reviewer` doesn't define it, the reference dangles.
Fix: Confirm that `crew-reviewer` defines `check-packages` and that it checks file integrity. Then reference it by section name, or drop the byte-for-byte claim.

3. [nit · 3] **`.cursor/agents/references/dispatch.md:22`** — The instruction list for the path prompt can drift from the finding contract
```
repeats only the delivery-independent instructions: reply text only, no artifact writes, the finding shape, and the mode.
```
Restating "the finding shape" in the dispatch prompt duplicates the shared contract. If the contract changes, this copy can drift. The sentence also doesn't say whether "repeats" means quoting or pointing to the contract.
Fix: Say that the dispatch prompt names the contract and mode instead of copying the finding shape.