**Critical**

**Task 2** — The task has the builder ask the owner a question mid-run, and the spec itself says the pricing question is open.
The builder runs autonomously and cannot wait for an answer. The price table and the way tasks are priced depend on that answer, so Tasks 2, 3 and 4 and the acceptance criteria all stall or get guessed. Resolve the decision (one model's rates, or per-stage rates) before the spec is presented, and write the answer into Task 2 and the criteria. If it can't be resolved, mark the spec as blocked on the owner and don't hand it to the builder.

**Task 1** — The spec doesn't say which stage's model a per-stage price would need, and the METRIC format has no model field.
`METRIC: stage=<name> input= output= cache_read=` carries no model name. Per-stage pricing would need a stage-to-model mapping that no task defines or locates. Name the mapping source, or state that one model's rates apply to every line.

**Spec / `## Tests`** — The files the spec names are not in the working directory, and the single test command is unverified.
Glob found no `tui*` files and no `test.sh` anywhere in the working directory. So `tui/tui_model.py`, `tui/tui_cost.py` (a new file, which the spec doesn't say), `tui/tui_app.py`, `evals/tools/test_tui_model.py` and `bash evals/test.sh` could not be confirmed. A `grep` for `METRIC:` found it only in SPEC.md, so the PROGRESS.md format is also unconfirmed. Confirm the paths against the repo root and mark `tui_cost.py` as a new file.

**Important**

**Task 4** — The tests are the only automated check, but they cover only the model, not the render.
Task 3's COST column (right-aligned, two decimals, `—` for no METRIC) lives in `tui_app.py`, and no test or `verify:` command touches it. The acceptance criteria also have no `verify:` or inspection paths. Add a `verify:` command or an inspection target to each criterion, and add a render check.

**Task 2** — The task combines a decision, a new file and the pricing logic, and it depends on Task 1's output.
Task 1's token parsing is implicit input to the pricing, which is reasonable ordering. But the "total over rows shown" semantics (filtered rows, and how `—` rows are excluded) are not defined for Task 3. Split the pricing logic from the decision, and define the total's handling of `—` rows.

Verdict: 5 finding(s), 4 unverified: `tui/tui_model.py`, `tui/tui_app.py`, `evals/test.sh`, `evals/tools/test_tui_model.py` (plus the PROGRESS.md METRIC format).