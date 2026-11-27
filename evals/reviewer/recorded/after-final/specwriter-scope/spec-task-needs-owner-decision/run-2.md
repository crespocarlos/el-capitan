**Task 2** — "ask the owner which pricing they want": the builder can't carry out this task.

The builder runs unattended and nobody answers its prompts. Task 2 tells it to ask the owner, so it either stalls or picks a pricing scheme at random. Task 2's price table and Task 3's totals then depend on that choice. The Summary says the owner has not decided: "one model's rates or the model each stage used". The METRIC line format, `stage=<name> input=<n> output=<n> cache_read=<n>`, has no model field. Per-stage pricing would need a stage-to-model mapping that no task defines.

Fix: move the decision to `## Open questions` and block the spec until it is answered. Then rewrite Task 2 as a concrete instruction, either one rate table or a stage-to-model map, with the rates given.

**Task 2** — the price figures are missing from the spec, and `tui/tui_cost.py` may not exist.

Even after the decision, the builder has no per-million-token rates for input, output and cache_read, so it would invent them. `cost = f(tokens)` also has no stated formula or rounding rule. Task 2 is also two concerns, a price table and the pricing of each task, so it should be split.

Fix: state the rates and the formula in the spec, and say whether `tui/tui_cost.py` is created or already exists.

**Task 1** — the spec's paths could not be found, so the layout is unverified.

A Glob for `*tui*` and `test.sh` found nothing in the working directory. `tui/tui_model.py`, `tui/tui_app.py`, `evals/tools/test_tui_model.py` and `evals/test.sh` are therefore unconfirmed. The only METRIC match was SPEC.md itself, so the line format is also unconfirmed. No task has its own verify line, and the Tests command points at a file that Task 4 creates or extends last.

Fix: confirm these paths exist or mark them as new files, and give Tasks 1–3 a verify line each. Move each test row next to the task it covers, or state that the `## Tests` command only runs after Task 4.

**Task 3** — the rendering has no checkable test, and the tests miss several criteria.

The only test file is `test_tui_model.py`, which tests the model, not the right-aligned `$` rendering in `tui_app.py`. Criterion 2, "over the rows shown", has no test for filtered rows. Task 4 lists a priced task, the total and no METRIC, but the `—` criterion isn't tied to a rendering check.

Fix: add a rendering test, or a criterion that names an inspection path in `tui/tui_app.py` for the alignment, the `—` and the filtered-rows total.

Verdict: 4 finding(s), 4 unverified: `tui/tui_model.py`, `tui/tui_app.py`, `evals/tools/test_tui_model.py`, `evals/test.sh`. Also unverified: the METRIC line format in the real PROGRESS.md, and whether `tui/tui_cost.py` exists.