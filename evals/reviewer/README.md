# Reviewer Eval Harness

Precision/recall eval for individual reviewer personas in the el-capitan pipeline. Detects regressions when persona instruction files change.

## Purpose

The spec eval harness (`evals/run.py`) measures spec template quality. This harness measures whether **reviewer personas** produce correct, well-scoped findings when given known-bad diffs. Each persona is evaluated independently — the crew-reviewer orchestrator is out of scope.

Two metrics:
- **Recall** — of the expected findings for a persona, what fraction did it actually produce?
- **Precision** — of all labeled findings produced, what fraction matched an expected finding?

A third signal:
- **Scope violations** — findings from `reviewer-code-quality` that contain Architecture-lane terms (`architecture`, `boundary`, `coupling`, `dependency direction`). Any violations cause a non-zero exit code.

---

## Usage

```bash
# Run all fixtures against all applicable personas
ANTHROPIC_API_KEY=sk-... uv run python evals/reviewer/run.py

# Run only fixtures expected to produce Adversarial findings
ANTHROPIC_API_KEY=sk-... uv run python evals/reviewer/run.py --persona reviewer-adversarial

# Run a single fixture against all applicable personas
ANTHROPIC_API_KEY=sk-... uv run python evals/reviewer/run.py --fixture r1

# Summarize most recent run (no API calls)
uv run python evals/reviewer/run.py --summarize
```

Results accumulate in `evals/reviewer/results/<timestamp>/`. Each run writes per-persona JSON files and a `manifest.json`.

---

## Fixture format

Fixtures live in `evals/reviewer/fixtures.json`:

```json
{
  "fixtures": [
    {
      "id": "r1",
      "description": "Human-readable explanation of what this fixture tests",
      "diff": "--- a/src/file.py\n+++ b/src/file.py\n@@ -1,3 +1,5 @@\n ...",
      "expected_findings": [
        {
          "persona": "reviewer-adversarial",
          "severity": "blocking",
          "match_hint": "null dereference"
        }
      ]
    }
  ]
}
```

### Field descriptions

| Field | Type | Description |
|---|---|---|
| `id` | string | Unique fixture identifier (e.g. `r1`, `r2`) |
| `description` | string | What this fixture is testing — explains the expected failure mode |
| `diff` | string | Unified diff text with `--- a/` / `+++ b/` headers and `@@ ... @@` hunks |
| `expected_findings` | array | List of findings this fixture should produce |
| `expected_findings[].persona` | string | Exact persona name (e.g. `reviewer-adversarial`) |
| `expected_findings[].severity` | string | Expected label: `blocking`, `attention`, `needs more info`, or `nit` |
| `expected_findings[].match_hint` | string | Short phrase (3–8 words) that must appear in any correct finding |

---

## Scoring methodology

### Matching

A finding is **matched** when both of the following are true in the raw output (case-insensitive):
1. The label `[<severity>]` appears (e.g. `[blocking]`)
2. The `match_hint` substring appears anywhere in the text

`match_hint` is a plain substring — not a regex, not semantic similarity.

### Recall

```
recall = matched_expected / total_expected_for_persona
```

If a persona has no `expected_findings` for a fixture, that pair is **excluded from aggregation** — it is not counted as 0 recall.

### Precision

```
precision = matched_expected / total_labeled_findings_produced
```

Where `total_labeled_findings_produced` is the count of `[blocking]`, `[attention]`, `[needs more info]`, and `[nit]` labels in the raw output.

### Scope violations

Applied only to `reviewer-code-quality`. The raw output is scanned for these denylist terms:
- `architecture`
- `boundary`
- `coupling`
- `dependency direction`

Any match counts as a scope violation. The summary table shows the count per persona, and any non-zero count causes a non-zero exit code.

### Truncation guard

If a persona returns fewer than 50 characters, the result is marked `truncated` and excluded from precision/recall. Truncated responses do not count as recall=0.

---

## Adding fixtures

Minimum required fields:

```json
{
  "id": "rN",
  "description": "What bug or quality issue does this diff contain?",
  "diff": "<unified diff — use --- a/ and +++ b/ headers with @@ hunks>",
  "expected_findings": [
    {
      "persona": "<reviewer-name>",
      "severity": "<blocking|attention|needs more info|nit>",
      "match_hint": "<short phrase that must appear in a correct finding>"
    }
  ]
}
```

Rules for good fixtures:
1. **Diffs must be self-contained** — no references to real repo files; the diff should stand alone
2. **`match_hint` must be unambiguous** — it should appear naturally in any correct finding but not in unrelated text
3. **One defect per fixture** — multiple independent bugs in the same diff produce noisy recall scores
4. **Test one persona per expected finding** — cross-persona findings are valid but make regression attribution harder

Current fixtures:

| ID | What it tests | Expected persona | Severity |
|---|---|---|---|
| r1 | Null dereference — `user` accessed without null check | `reviewer-adversarial` | `blocking` |
| r2 | Swallowed async error — exception caught, success returned | `reviewer-adversarial` | `attention` |
| r3 | New exported function with no test coverage | `reviewer-code-quality` | `attention` |
| r4 | Scope discipline — Architecture boundary change (Code Quality must NOT produce arch findings) | `reviewer-code-quality` | `attention` |
| r5 | Prompt file verbosity regression — redundant restatements burying critical instruction | `reviewer-prompt-quality` | `attention` |
