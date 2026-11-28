# Reading the report

Step 4 detail for `crew e2e`. Render the report from the JSON only; never retell it from memory.
`TASK_DIR` is the task `task-context` resolved, empty for none.

Once `state` is `done`, `report` returns the verdict, summary, `prIntent`, `approach`, `setup`,
`checks` (each with `status`, `via`, `category`, `details`, `evidence`, `screenshots`, and a computed
`end_to_end`), `findings`, `environmentChanges`, `notCovered`, and `not_end_to_end` — passing checks
observed only through a health probe, a unit command, or a script. A check is end-to-end only when it
was not skipped and was observed through `ui`, `api`, `es`, or `log`. Quote `not_end_to_end` explicitly:
a green run whose checks were mostly `unit` or `health` is not end-to-end evidence, and reporting it
as if it were is the one misleading outcome this skill can produce.

```markdown
## E2E: <title> (#<number>) — <verdict>
<summary>
Tested head `<testedHead7>`; PR at `<headRefOid7>`. Approach: <approach>. Run: <run field>

### Checks (<end-to-end count> of <total> end-to-end)
| Check | Status | Observed via | Category |
|---|---|---|---|
| <title> | pass/fail/warn/skipped | ui, api | feature |

### Findings
- **bug** — <title>: <detail, one line>        (group by kind: bug, concern, note, positive)

### Not end-to-end
<not_end_to_end titles, or "none">

### Left in the environment
<environmentChanges, one bullet each; include injected faults and debug lines and whether reverted>

### Not covered
<notCovered>

### Coverage of the PR surface
<each changed file from Step 1's diff, mapped to the check(s) that touched it (by title match or
evidence path); files with no matching check listed under "no check touched this file">
```

Build the coverage section from the PR's changed-file list against each check's `title`, `category`,
and `evidence`. It answers "what in the diff did nothing observe", which `not_end_to_end` does not: that
one is about *how* a check that ran observed things, not which files no check touched.

Show at most a 300-character excerpt of any `evidence`, point to the run page for screenshots, and
never paste credentials or tokens that appear in evidence (Step 0's secret hygiene).

## A blocked verdict

`blocked` is not a result for the PR. State the blocking cause from the summary or findings in one
line (an environment limit such as a missing connector, for example), say the PR's behavior is
unverified, and list passed checks only as "environment checks that passed" — never as evidence for
the PR. Then give the next step: which prerequisite to fix, or `crew e2e setup` when `doctor` notes
point at it. Do not offer a rerun until the cause is addressed, and name the `doctor` notes as suspects.

## Persist the report

Write it to `$TASK_DIR/E2E.md` when `task-context` resolves a task, otherwise to
`/tmp/crew-e2e-<key>/E2E.md`, prefixed with the date.

**Keep a history.** Nightshift replaces a PR key's run directory on its next run, so a report cited
today can be gone when someone rereads the conversation. As soon as a run finishes, copy the rendered
report, the raw `report` JSON, and `testedHead` into `$TASK_DIR/e2e/<testedHead7>/` (or
`/tmp/crew-e2e-<key>/e2e/<testedHead7>/` without a task) before reporting the summary — this is the
durable copy, not nightshift's run directory.
