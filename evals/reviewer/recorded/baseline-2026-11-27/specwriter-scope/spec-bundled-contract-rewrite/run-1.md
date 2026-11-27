**Task 4** — Out-of-scope rewrite of the shared reviewer contract.

Task 4 rewrites `.cursor/agents/references/reviewer-contract.md`, which every persona reads first. It is unrelated to the package-size goal in the Summary and has no acceptance criterion. Restructuring headings into bullets and tightening the severity wording changes the behaviour of every lens, and the spec gives no way to verify that the changes are safe. It also shares nothing with Tasks 1–3 and 5, so it is a separate PR.

Fix: Remove Task 4 and ship the contract rewrite as its own spec with its own criteria, or justify it as required for package size and add a `verify:` check.

**Spec (Tests/Tasks)** — The `## Tests` command runs test files that Task 5 writes last.

The Unit command runs `evals/tools/test_review_hunks.py` and `evals/reviewer/test_review_findings.py`. Task 5 adds the rows to them after Tasks 1–3, so none of the earlier tasks has a runnable check. A failure in Task 1 or 2 only shows up at the end. Per-task acceptance checks are absent altogether.

Fix: Give each of Tasks 1–3 an inline `verify:` command, or move the test rows into Tasks 1 and 2 so each task is checked as it lands.

**Acceptance criteria** — Criteria 1 and 2 have no verification path.

"Every `<persona>.in.md` embeds `package.diff`" and "carries the spec without Tasks and Hints" name no `rg` command, test, or file to inspect. Criterion 3 depends on `check-packages` being run against real written packages, which are not available in the builder's environment. The criterion also does not say whether the check should return 1 when the package carries the spec's Tasks and Hints.

Fix: Add a `verify:` for each criterion, such as a pytest case or an `rg` for the collapsed-summary line, and state the fixtures that `check-packages` uses.

**Task 3** — `crew-reviewer.md` is a prompt file, and the task is under-specified.

The task does not say where in `crew-reviewer.md` the package-build step lives. It does not give the `check-packages` invocation or arguments, or the exact output format of the "one line" generated-file summary (Task 1). It also does not say how to detect a generated file, so Tasks 1 and 3 can't be implemented without guessing. A prompt-file change cannot be tested with the unit command.

Fix: Name the section of `crew-reviewer.md` to edit, spell out the command line, and define the generated-file detection rule and summary format in Task 1.

**Task 2** — The `spec-context` and `check-packages` interfaces are undefined.

Task 2 adds two subcommands with no arguments, input paths, or output format. It does not say how `check-packages` identifies product-flow or finds the spec heading boundaries (for example, `## Tasks` through the next `##`). The builder must explore the code to fill these gaps. Tasks 2 and 3 also have an unstated interface dependency.

Fix: Specify the CLI signatures, the section-stripping rule, and the exit semantics in the task.

Verdict: 5 finding(s), 6 unverified

Unverified: `.agent/tools/review-hunks.py`, `.agent/tools/review-findings.py`, `.cursor/agents/references/reviewer-contract.md`, `crew-reviewer.md`, `evals/tools/test_review_hunks.py`, `evals/reviewer/test_review_findings.py`. My Glob found no matching files in the working directory. The only Grep hits were in SPEC.md, so I could not check any of these paths.