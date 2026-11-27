**Critical**

**Task 4** — `rewrite .cursor/agents/references/reviewer-contract.md ... turn the "One issue per finding" ... headings into bullets and tighten the wording of the severity section`: this task is scope creep, and it breaks existing checks.
No acceptance criterion needs it, because the three criteria cover `package.diff`, spec trimming and `check-packages`. Rewriting the contract every persona reads can change reviewer behaviour, and the `## Tests` command has no check on it. A builder following it can't mark any criterion done by it, and "tighten the wording" has no pass or fail.
Fix: remove Task 4 and ship it as its own spec, or add a criterion and a concrete check for it.

**Task 1 / Task 5 / `## Tests`** — the tests are split from the code that needs them, and the paths are unverified.
Tasks 1–3 have no per-task verify line, and Task 5 adds the tests last. The builder can't prove Tasks 1–3 as it goes, and `evals/tools/test_review_hunks.py` and `evals/reviewer/test_review_findings.py` get edited only at the end. A failure then points at the wrong task.
Fix: fold each test row into the task it covers (Task 1 with `test_review_hunks.py`, Task 2 with `test_review_findings.py`) and give each task its own verify command.

**Important**

**Task 3** — `have crew-reviewer.md build each package ... and run check-packages before dispatch`: the task mixes two concerns and has nothing to check it.
It's a prompt-file edit, and `## Tests` is Unit-only, with no integration or validation layer that runs the reviewer flow. A broken `crew-reviewer.md` passes every test. Nothing checks that the package embeds `package.diff` or that product-flow keeps the full spec.
Fix: add a `### Validation` step, such as an `rg` for `package.diff` and `check-packages` in `crew-reviewer.md`. Alternatively add a criterion naming that inspection.

**Task 2** — `add spec-context and check-packages`: it has no defined interface.
Task 3 depends on how `spec-context` is called and how `check-packages` finds the packages (directory or arguments). The criterion says "exits 1 naming the package", but the spec names no package location, no product-flow exception and no output format. The builder has to guess.
Fix: state the CLI signature, the package directory path and the product-flow exemption.

Verdict: 4 finding(s), 5 unverified: `.agent/tools/review-hunks.py`, `.agent/tools/review-findings.py`, `.cursor/agents/references/reviewer-contract.md`, `evals/tools/test_review_hunks.py`, `evals/reviewer/test_review_findings.py`. A glob for these files found none in the case directory, so the paths themselves are unconfirmed. `evals/test.sh` and `crew-reviewer.md` were not found either.