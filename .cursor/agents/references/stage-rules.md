# Review stage rules: cost line and e2e

`crew-reviewer` links here for the two things it does after the personas are dispatched and before it
hands off.

## The cost line

When the review finishes, record the stage and print one cost line from what the harness reported:

```bash
~/.agent/bin/crew-metric.py "$TASK_DIR" stage_start stage=review          # before the first persona
~/.agent/bin/crew-metric.py "$TASK_DIR" stage_end stage=review personas=<n> tokens_reported=<n|unknown>
```

`stage_end` prints the line (`review: 4 personas, 380k tokens`) and appends it to PROGRESS.md; show it
as the last line of the review output. Use `tokens_reported=unknown` when the harness gives nothing: a
token count is never estimated. `crew ls --cost` reads the same lines. With no task directory (a PR
review outside a task) print the line from the same numbers and write nothing.

## e2e for a frontend diff

When the diff touches frontend files and the repository's `AGENTS.md` has an `e2e:` line naming the
script (`e2e: npm run e2e`), invoke the existing `crew-e2e` skill with that script after `select`
and before Step 5 (build context) and pass its artifacts path to the product-flow persona's package
as evidence. The persona cites the artifacts; it does not run the browser. With
no product-flow persona in the run, put the artifacts path in the report's `### Reviewers` section
instead. Opt-in is the declared line: never guess a
script from CI job names. With no `e2e:` line, or no frontend file in the diff, skip this
and say so in the report's `### Reviewers` section. A spec's "one golden-path e2e from the first group"
line (spec template) is what makes the script exist.

## Skipped personas in the report

`crew-assemble-packages.py` skips a persona that cannot apply and records it in the review
directory's `manifest.json` under `personas.skipped` (with the reason), and prints a per-persona size
report. Name every skipped persona and its reason under `### Reviewers` in the report: a review that
ran three lenses says why it did not run four. With `"slice": true` in `assemble.json` only
product-flow and code-quality are sliced (callers and callees travel with a changed symbol); the
manifest's `personas.sliced` lists what each received.
