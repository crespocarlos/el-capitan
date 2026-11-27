**Critical**

**Task 4** — The task has nothing to do with package size, and it edits a contract every persona reads.
The Summary and acceptance criteria are all about `package.diff` and spec trimming. Task 4 rewrites `.cursor/agents/references/reviewer-contract.md` (headings to bullets, "tighten the wording"), which changes reviewer behaviour in every persona, and no acceptance criterion or test covers it. "Tighten the wording" cannot be checked by reading the diff. It is a separate PR that the size change does not depend on.

Fix: drop Task 4 into its own spec. If it stays, state the exact text changes and add an acceptance criterion that names an inspection path.

**Important**

**Task 3** — The task cannot be verified, and the criteria that depend on it cannot be checked either.
`crew-reviewer.md` is an agent prompt, so the spec has no way to confirm it builds packages from `package.diff`. The `## Tests` command only runs the two Python test files. Criteria 1 and 2 (what `<persona>.in.md` embeds) have no `verify:` command or inspection path.

Fix: add a `verify:` for each criterion, such as `rg 'package.diff' <path>` on the agent file and the written packages, and say what a pass looks like.

**Task 2** — The task bundles two new subcommands in one file, and the spec doesn't define the rules they implement.
`spec-context` and `check-packages` both go into `review-findings.py`. Criterion 3 says check-packages "names the package that breaks either rule", but the spec doesn't say how to detect "a generated file appears as one summary line". It also doesn't say how to recognise a spec stripped of `## Tasks` and `## Hints`, or how product-flow is identified. The builder would have to guess the summary-line format that Task 1 produces.

Fix: split it into two tasks, and state the summary-line format and the product-flow exemption rule inline in the spec.

**Task 1** — The spec doesn't define what counts as a generated file.
Collapsing "generated files" needs a rule, such as lockfile names or a header marker, and none is given. Tasks 1 and 2 are also coupled through the summary-line format, but the spec doesn't declare that.

Fix: list the generated-file patterns and the exact summary-line format, and mark the dependency between Tasks 1 and 2.

**Task 5** — The tests come last, after the code they test.
Tasks 1 and 2 change the behaviour of tools that are covered by tests, and the new rows come only in Task 5, so Tasks 1–4 have no per-task check. The tests and the doc references are not tied to the tasks they cover.

Fix: fold the test rows into Tasks 1 and 2 so each task is verified when it lands.

Verdict: 5 finding(s), 6 unverified: `.agent/tools/review-hunks.py`, `.agent/tools/review-findings.py`, `crew-reviewer.md`, `.cursor/agents/references/reviewer-contract.md`, `evals/tools/test_review_hunks.py`, `evals/reviewer/test_review_findings.py`. A Glob for those names in the case directory found none; only `SPEC.md` matched my search.