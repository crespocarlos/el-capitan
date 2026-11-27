**Critical**

**Task 4** — Scope creep, and the target file's contents are unverified: "rewrite `.cursor/agents/references/reviewer-contract.md` … turn the 'One issue per finding' and 'Say whether the defect pre-exists' headings into bullets and tighten the wording of the severity section."

No acceptance criterion and no summary goal covers this task. The wording change is subjective, so the builder cannot tell when "tighten" is done. Every persona reads this file first, so an unmeasured rewrite can change review behavior and has nothing to do with package size. The case directory holds only SPEC.md, so I could not confirm that the file or those headings exist.

Drop Task 4 into its own spec. If it stays, add a criterion and a concrete check, such as `rg` for the exact headings that should be gone.

**Important**

**Task 3** — The verify step cannot run: "have `crew-reviewer.md` build each package from `package.diff` and `spec-context`, and run `check-packages` before dispatch."

`crew-reviewer.md` is an agent prompt, so no command checks it. The task has no verify line and no root-relative path, since `.cursor/agents/` or `.agent/` is not stated. The builder may edit the prompt and mark it done with nothing proving that `<persona>.in.md` embeds `package.diff`. Criteria 1 and 2 describe generated packages that only a model run produces, and the spec gives no way to check that.

Give the full path to `crew-reviewer.md` and add an `rg` check for `package.diff`, `spec-context` and `check-packages` in it. Add a fixture-based check of `check-packages` on a sample package.

**Task 1 / Task 2 / Task 5** — The tests come last, and the tasks have no verify lines. Task 5 adds the rows that exercise Tasks 1 and 2, so those two tasks have nothing to run when they finish. The `## Tests` command also runs only at the end.

Fold each test row into the task that adds the code, or give each task its own `bash evals/test.sh <file>` verify line.

**Task 2** — Two new subcommands, `spec-context` and `check-packages`, go into one file with no defined interface. The spec doesn't say how `check-packages` finds the packages or what makes a package fail. It doesn't say how it recognizes the product-flow package, how it detects a collapsed generated file, or what counts as a generated file. A builder will guess these, and a guess can disagree with Task 1's "collapsed" format.

Split the two subcommands. State the package location, the product-flow rule, and the summary-line format that Task 1 writes and Task 2 checks.

**Task 1** — "Generated files collapsed to one line" gives no rule for what counts as generated (lockfile name patterns, markers). Criterion 1 ("appears as one summary line") has no exact line format to match. The builder cannot run a check against a format nobody defined.

Define the detection rule and the summary-line format in the task.

Verdict: 5 finding(s), 3 unverified: `.cursor/agents/references/reviewer-contract.md`, `.agent/tools/review-hunks.py` and `.agent/tools/review-findings.py`, `evals/tools/test_review_hunks.py` and `evals/reviewer/test_review_findings.py`, `crew-reviewer.md` (the case directory holds only SPEC.md)