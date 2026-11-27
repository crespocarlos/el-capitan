**Important**

**Task 4** — `rewrite .cursor/agents/references/reviewer-contract.md ... tighten the wording of the severity section`: scope creep, and no criterion covers it.
The summary and the three criteria are only about package size. Task 4 rewrites a contract that every persona reads first, which changes review behaviour and has nothing to do with `package.diff` or the spec trimming. "Tighten the wording" has no pass/fail check. The builder would guess, and a later review could shift with no test to catch it.
Fix: drop Task 4 and ship it as its own spec. If it stays, add a criterion for it and give a checkable edit, such as the exact headings to convert and the severity text to leave unchanged.

**Task 5** — `add rows to evals/tools/test_review_hunks.py and evals/reviewer/test_review_findings.py`: the tests come after the code they check, and the task covers two files.
Tasks 1–3 have no verify line that can run until Task 5 adds the tests. A builder that stops after Task 3 has an untested tree, and a failure shows up only in the final `## Tests` run. Task 5 also edits two test files for two separate tools.
Fix: fold the `review-hunks.py` rows into Task 1 and the `review-findings.py` rows into Task 2, and give each task its own verify command, such as `bash evals/test.sh evals/tools/test_review_hunks.py`.

**Task 3** — `have crew-reviewer.md build each package from package.diff and spec-context, and run check-packages before dispatch`: it depends on Tasks 1 and 2, and nothing says what the CLIs look like.
`spec-context` and `check-packages` are not defined anywhere. There is no argument list, no output format, and no description of how a package is recognised as product-flow's. The builder has to guess at what Task 3 should call, and a wrong guess breaks the persona flow. `crew-reviewer.md` is a prompt file, so no test covers it.
Fix: state the CLI signatures in Tasks 1 and 2, for example `spec-context <SPEC.md>` printing to stdout and `check-packages <dir>` with its exit codes. Add a check for Task 3, such as `rg 'check-packages' <path>`, and give the full path to `crew-reviewer.md`.

**Spec (Tests / criteria)** — the `## Tests` section has only `### Unit`, and no layer covers the dispatch path.
Criterion 3 says `check-packages` exits 1 on a bad package, and a CLI that the reviewer flow invokes crosses a process boundary. A unit test that calls a function would not catch a wrong exit code or a wrong argv. Criteria 1 and 2 also give no command for checking them.
Fix: add `### Integration`, which runs `review-findings.py check-packages` on a fixture directory and asserts exit 1 and the package name, and give each criterion a command or an "inspect `path` for …" check.

**Spec (paths)** — none of the paths could be verified. A glob found no `review-hunks`, `review-findings`, `reviewer-contract`, `crew-reviewer` or `evals/test.sh` files in the working directory.
If the case files are missing, every task's path and the `## Tests` command are unverified. Relative to a repository root, the `.agent/tools/` and `.cursor/agents/` paths are explicit, but `crew-reviewer.md` has no directory.

Fix: confirm the paths and give `crew-reviewer.md` its full path.

Verdict: 5 finding(s), 5 unverified: `.agent/tools/review-hunks.py`, `.agent/tools/review-findings.py`, `.cursor/agents/references/reviewer-contract.md`, `crew-reviewer.md`, `evals/test.sh`.