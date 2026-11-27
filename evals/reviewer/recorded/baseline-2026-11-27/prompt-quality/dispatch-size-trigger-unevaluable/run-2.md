Assessment: request-changes — the change allows delivery by path, but the "too large to embed" trigger has no number the orchestrator can check, so it can't reliably choose between inline and path delivery.

1. [attention · 4] **`.cursor/agents/references/dispatch.md:19`** — The size trigger for path delivery can't be evaluated
```
**Package delivery: inline by default, by path when a package is too large to embed.**
...
Use it when embedding would push the orchestrator's own output past what the harness accepts —
one measured five-persona review was 640 KB, roughly 160k tokens of duplicate output.
```
The three conditions say when path delivery is allowed. Nothing says when it is needed. "Too large to embed" and "past what the harness accepts" give no threshold. The orchestrator can't tell its own output limit, and it doesn't know the harness limit in advance. The 640 KB figure is one example, not a boundary. Models will therefore split on the same input. Some will embed 300 KB and hit the limit. Others will pass paths for small packages, which loses the inline default.

The rule also puts the usage guidance after the conditions, so the decision criterion comes last. The text also mixes two quantities: a package's size, and the total output across all personas. Embedding costs package size × persona count, so either quantity could trigger it.

Fix: State a measurable rule. For example: "Embed when the total of all persona packages in this dispatch is under N KB. Otherwise deliver by path, if conditions 1–3 hold." Pick N from the measured limit. Say which quantity is compared (per-package or summed). Also say what to do when path delivery is needed but condition 2 fails. For example, split the package, or embed a trimmed package that has passed the same gate. Put the trigger before the conditions.

2. [needs more info · 2] **`.cursor/agents/references/dispatch.md:18`** — The `check-packages` gate is cited but defined nowhere in the supplied files
```
passed the `check-packages` gate of
`crew-reviewer`'s dispatch step
```
A grep of the package finds this only at its point of use. I could not confirm that the `crew-reviewer` dispatch step or the `check-packages` gate exists under those names. Condition 1 rests on that gate, so the "byte-for-byte the package the protocol checked" guarantee fails if the reference is stale. Which file defines the `check-packages` gate, and does `crew-reviewer`'s dispatch step still use that name?