**Critical**

**Task 2** — "ask the owner which pricing they want, then add the price table to `tui/tui_cost.py`" can't be done by the builder.

Nobody answers prompts. The builder reaches Task 2, can't get an answer, and either guesses a model's rates or fails after three tries. The spec also has no `## Open questions` section. The pricing choice (one model's rates versus per-stage model) decides Task 2's data shape and Task 3's output.

Fix: move the pricing decision to `## Open questions` and settle it before the build. Then rewrite Task 2 with one concrete pricing rule, or add a prerequisite stating the decision.

**Tasks 1–4 (no verify lines)** — no task has a verify line, so the builder has nothing to run after each one.

The builder runs a verify line after each task. With none, Task 1 or Task 2 can be marked done while broken, and the failure only appears at the end in `## Tests`.

Fix: add a runnable verify to each task, for example a pytest `-k` selector for the parsing and pricing tasks.

**Important**

**Task 4 / `## Tests` "`bash evals/test.sh evals/tools/test_tui_model.py`"** — the test file is only extended in Task 4, the last task. The command covers the model and pricing but not the rendering in `tui/tui_app.py`.

Rendering is where the criteria sit: the dollar format, right alignment, the total row and the `—` for a task with no METRIC line. A bug in Task 3's rendering, such as `$0.00` instead of `—`, passes the unit command. The tests also come after the code they check, so Tasks 1–3 have nothing to run against.

Fix: add the rendering check as a layer in `## Tests`, or put the test rows in the same task as each behavior, and name the test function or `-k` selector.

**Task 2** — it does two jobs: it creates a new file (`tui/tui_cost.py`, a price table) and it wires pricing into each task. The pricing step depends on Task 1's parsed output.

If the table is wrong or the wiring fails, the builder can't tell which edit broke the verify. It is also unclear which file holds the "price each task" function, `tui_cost.py` or `tui_model.py`.

Fix: split it into "add the price table and a `cost(tokens)` function in `tui/tui_cost.py`" and "call it from `tui/tui_model.py`", naming the file for each.

**Consider**

**`## Acceptance criteria` (all three bullets)** — none names how it is proved, for example "right-aligned" or "sums the column over the rows shown". The builder has only the unit test to go on, and that test doesn't touch rendering.

Fix: add an inspection or command for each, such as a test asserting the rendered row string.

Verdict: 4 finding(s), 3 unverified: `tui/tui_model.py`, `tui/tui_app.py`, and `evals/test.sh` and `evals/tools/test_tui_model.py` were not found. The case directory contains only SPEC.md, so none of the spec's paths could be checked.