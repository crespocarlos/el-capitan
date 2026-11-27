**Important**

**Task 4** — This task is unrelated to the spec's goal and should ship as its own PR.
The Summary and acceptance criteria are all about package size. Task 4 rewrites the reviewer contract that every persona reads first. It converts headings to bullets and tightens the severity wording, so it changes review behavior. No acceptance criterion covers it, and it is a prose edit that can't be checked mechanically.
Fix: move Task 4 to a separate spec, or add an acceptance criterion and a verify command for it. Otherwise drop it.

**Task 2** — Both subcommands go in `review-findings.py`, and nothing says how `check-packages` identifies a package or a rule violation.
`check-packages` must know where the written packages live. It must also know which persona is product-flow, what counts as a generated-file summary line, and how "spec without Tasks and Hints" is detected. The spec leaves all of these to guesswork, so the builder will invent an interface that Task 3 then has to call.
Fix: state the CLI signature (arguments, package directory, the summary-line format) and the exit-code contract in the task.

**Task 5** — The tests come last, after the code they cover, and the whole task is untestable until it runs.
The `## Tests` command runs only after every task. Tasks 1–3 have no per-task check, so a failure in Task 1 surfaces only at the end. The acceptance bullets also have no `verify:` commands. Examples are "appears as one summary line" and "exits 1 naming the package".
Fix: add a verify command to each task, or pair each implementation task with its own test rows. Give each acceptance bullet a `verify:` or an inspection path.

**Task 3** — `crew-reviewer.md` has no path, and the "build each package from…" and "before dispatch" steps are vague.
The path has no directory prefix, unlike the other tasks. `.cursor/agents/` is the only directory implied, and the spec doesn't say so. The task also edits a prompt file, and "run `check-packages` before dispatch" has no acceptance check that the builder can run.
Fix: give the full path from the repo root, and say which lines of the prompt change and how to confirm it, for example with an `rg` on `check-packages`.

**Consider**

**Task 1/Task 3** — The tasks are ordered so that Task 1 changes the output, and Task 3 switches the embeds.
Until Task 3 lands, `package.diff` is written but unused. The order works, but Tasks 2 and 3 form a dependency pair: the `check-packages` call in Task 3 fails if Task 2 isn't merged. Say so, for example with an atomic note.

Verdict: 4 finding(s), 5 unverified: `.agent/tools/review-hunks.py`, `.agent/tools/review-findings.py`, `crew-reviewer.md`, `.cursor/agents/references/reviewer-contract.md`, `evals/test.sh` and the test file paths. The case directory contains only SPEC.md, so no file path could be checked.