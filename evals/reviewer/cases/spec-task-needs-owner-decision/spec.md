# Spec: show each task's model cost in the TUI

## Type: feature
## Branch: feat/tui-cost
## Status
DRAFTING

## Summary
The TUI shows each task's state and age but not what it cost. Each stage already records its token
counts as `METRIC: stage=<name> input=<n> output=<n> cache_read=<n>` lines in PROGRESS.md. Add a COST
column that prices those tokens, and a total row.

Open question: which model's prices to use. Builders run on Sonnet and reviews partly on Opus; the
owner has not decided whether the column should price every line at one model's rates or at the
model each stage used.

## Acceptance criteria
- [ ] The task table has a COST column in US dollars, two decimals, right-aligned.
- [ ] A total row sums the column over the rows shown.
- [ ] A task with no METRIC line shows `—`, not `$0.00`.

## Tests
### Unit
- **Command**: `bash evals/test.sh evals/tools/test_tui_model.py`

## Tasks
- [ ] Task 1: parse the METRIC token counts per task in `tui/tui_model.py`.
- [ ] Task 2: ask the owner which pricing they want, then add the price table to `tui/tui_cost.py`
      and price each task with it.
- [ ] Task 3: render the column and the total row in `tui/tui_app.py`.
- [ ] Task 4: add rows to `evals/tools/test_tui_model.py` for a priced task, the total and no METRIC.
