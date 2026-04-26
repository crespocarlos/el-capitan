# el-capitan evals

Three-arm eval harness for measuring whether the SPEC.md template format improves spec quality over free-form prompts.

## Arms

| Arm | System prompt | Tests |
|-----|--------------|-------|
| `baseline` | None | Raw task description only |
| `terse` | "Be specific. List acceptance criteria." | Generic brevity prompt |
| `crew-spec` | Full `_SPEC_TEMPLATE.md` | El-capitan structured spec template |

**Why three arms, not two:** Comparing `crew-spec` vs `baseline` conflates the template with generic conciseness. `crew-spec` vs `terse` is the honest delta — it isolates the value of the structure, not just the instruction to be specific.

## Metrics

- **`output_tokens_api`** — primary signal: how many tokens the model emits
- **`structure_score`** — secondary: count of `## Context`, `## Acceptance Criteria`, `- [ ]`, `**Acceptance**`, etc. present in the output
- **`input_tokens_api`** — cost signal: `crew-spec` will have higher input tokens due to the template

## Usage

```bash
# Install deps (one-time)
uv sync

# Run all tasks, all arms
ANTHROPIC_API_KEY=sk-... uv run python run.py

# Run single task
ANTHROPIC_API_KEY=sk-... uv run python run.py --task t1

# Run specific arms only
ANTHROPIC_API_KEY=sk-... uv run python run.py --arms baseline,crew-spec

# Summarize existing results (no API calls)
uv run python run.py --summarize
```

## Adding tasks

Edit `tasks.json`. Each task is a `{"id": "tN", "description": "..."}` object. Use realistic el-capitan feature requests — the same kind of descriptions users would give to `crew spec`.

## Methodology note

Results are committed to `results/` as JSON. The `manifest.json` in each run directory records total token cost. Runs accumulate over time — multiple runs on the same tasks show variance.

## Interpreting results

A good `crew-spec` result shows:
- Higher `structure_score` than `baseline` and `terse`
- Output tokens ≥ baseline (more structured = more complete, not less)
- Consistent `**Acceptance**` blocks in tasks (the key quality signal for crew-builder)

If `terse` matches `crew-spec` on structure score, the template isn't adding value beyond generic instruction — that's a signal to revise the template.

## Reviewer eval

A separate precision/recall harness for individual reviewer personas lives in `evals/reviewer/`.

It measures whether each persona (adversarial, code-quality, prompt-quality, etc.) produces the correct findings when given known-bad diffs. Regressions surface as drops in recall or new scope violations when persona instruction files change.

```bash
# Run all reviewer fixtures
ANTHROPIC_API_KEY=sk-... uv run python evals/reviewer/run.py

# Summarize most recent reviewer eval run
uv run python evals/reviewer/run.py --summarize
```

See [evals/reviewer/README.md](reviewer/README.md) for fixture format, scoring methodology, and how to add new fixtures.
