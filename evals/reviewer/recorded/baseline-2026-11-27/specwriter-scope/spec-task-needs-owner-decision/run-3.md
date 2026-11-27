**Critical**

**Task 2** — The task makes the builder ask the owner a question the spec leaves open.

The Summary says the owner hasn't decided between one model's rates and per-stage rates. Task 2 tells the builder to ask, but the builder runs autonomously and has no one to ask, so it will stall or guess. The two options also give different results. Per-stage pricing needs a model field, and the METRIC line has none (`stage=<name> input= output= cache_read=`). Task 1's parser and Task 4's expected values both depend on the answer.

Fix: Have the owner decide before implementation, then record the decision and the price table in the spec. Alternatively, make the single-model choice an explicit design constraint with a stated price table and move per-stage pricing out of scope.

**Important**

**Task 2** — The task combines two jobs: asking the owner a question and building the price table and pricing logic.

The task also has no acceptance check, and it can't have one while the pricing basis is open. It creates a new file, `tui/tui_cost.py`, that nothing else in the spec mentions. The spec gives no price values and no cache_read rate, and doesn't say whether cache-write tokens are priced.

Fix: Make Task 2 a pure implementation task that lists the price table inline and gives a check such as `verify: rg` for the table and a unit test for one priced task.

**Spec (file paths)** — None of the paths could be verified. `tui/tui_model.py`, `tui/tui_app.py`, `tui/tui_cost.py`, `evals/tools/test_tui_model.py`, `evals/test.sh` and PROGRESS.md do not exist in the case directory. The directory contains only SPEC.md. If they exist in the real repo, the spec doesn't say so. Task 4 names a test file as if it already exists, and the Tests command depends on `evals/test.sh`, which I couldn't find.

Fix: State which files already exist and which are new, with paths from the repo root. Confirm that `evals/test.sh` accepts a file argument.

**Task 3 / Acceptance criteria** — The criteria and tasks don't have a runnable check for the rendering.

The Tests section only runs `test_tui_model.py`, which cannot exercise the right-alignment, two-decimal formatting or the total row that Task 3 renders in `tui_app.py`. The bullet "A total row sums the column over the rows shown" is also ambiguous about how `—` rows are treated in the sum.

Fix: Add a `verify:` command or inspection target for each criterion. Either test the formatting from a model-level function, or state that the rendering is checked by inspecting `tui_app.py`. Say how `—` rows are handled in the total.

**Consider**

**Task 4** — The tests come last, after Tasks 1–3. Each task also has no check of its own before then. Interleaving each test with its implementation task would let the builder verify as it goes.

Verdict: 4 finding(s), 1 unverified: the existence of `tui/tui_model.py`, `tui/tui_app.py`, `tui/tui_cost.py`, `evals/tools/test_tui_model.py`, `evals/test.sh` and PROGRESS.md. The case directory has only SPEC.md.