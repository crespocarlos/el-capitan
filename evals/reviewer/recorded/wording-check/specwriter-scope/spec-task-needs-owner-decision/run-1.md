**Critical**

**Task 2** — "ask the owner which pricing they want": the builder can't do this task, and the Summary's open question blocks it.
Nobody answers prompts during the build. Task 2 stalls or guesses between one flat model rate and a per-stage model rate. Those give different dollar figures, and Task 3 and Task 4 build on them.
Fix: resolve the choice before the spec ships, or move it to `## Open questions` and rewrite Task 2 as "add the price table to `tui/tui_cost.py`" with the chosen rule and the rates stated.

**Acceptance criteria** — "two decimals", "US dollars": no criterion checks the pricing rule, so the column's numbers can't be shown correct.
The builder can mark the criteria `[x]` with any price table. A priced task could show $1.20 or $4.00 for the same tokens and both would pass. The METRIC format has no model field, so per-stage pricing may not even be derivable.
Fix: add a criterion with a worked example, such as "input=1000 output=500 cache_read=0 shows `$X.XX`" under the chosen rule, and say how the model is determined.

**Important**

**Tasks 1–4 / `## Tests`** — the verify lines and test layer are missing or can't run.
- No task has a verify line, and the only automated check is `bash evals/test.sh evals/tools/test_tui_model.py`.
- That test file is created or extended in Task 4, which runs last. Until then the test either doesn't exist or covers nothing.
- Pricing lives in `tui/tui_cost.py`, but the tests only target `test_tui_model.py`, and nothing covers the `tui_app.py` rendering (right-alignment, total row, `—`).
- Fix: give each task its own verify command, move the tests next to the code they cover, and add a render-level check for the column and total row.

**Task 1 / Task 2** — they touch different files, but Task 2 prices tasks with the parsed counts. Task 2 should name the function and data shape that Task 1 exposes.
Without a named interface (for example `tokens_by_task() -> dict`), the builder has to guess it.
Fix: name the function signature in Task 1 and use it in Task 2.

**Acceptance criteria** — "A total row sums the column over the rows shown": it doesn't say how `—` rows count or how rounding is done.
Summing rounded cells and rounding the exact sum can differ by a cent, and a failing check can't tell which was intended.
Fix: state "sum exact costs, round once; `—` rows are excluded".

Verdict: 4 finding(s), 3 unverified: `tui/tui_model.py`, `tui/tui_app.py` and `evals/test.sh` could not be checked, because the workspace holds only SPEC.md. `tui/tui_cost.py` is new, so there was nothing to check.