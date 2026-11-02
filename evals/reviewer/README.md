# Reviewer Eval Harness

Precision/recall eval for individual reviewer personas in the el-capitan pipeline. Detects regressions when persona instruction files change.

## Purpose

The spec eval harness (`evals/run.py`) measures spec template quality. This harness measures whether **reviewer personas** produce correct, well-scoped findings when given known-bad diffs. Each persona is evaluated independently — the crew-reviewer orchestrator is out of scope.

Two metrics:
- **Recall** — of the expected findings for a persona, what fraction did it actually produce?
- **Precision** — of all labeled findings produced, what fraction matched an expected finding?

Additional signals:
- **Scope violations** — findings from `reviewer-code-quality` that contain Architecture-lane terms (`architecture`, `boundary`, `coupling`, `dependency direction`). Any violations cause a non-zero exit code.
- **False positives** — `[blocking]` or `[attention]` findings a persona produces on a fixture listed as clean for it (`clean_for`). An increase over the baseline is flagged as a regression.

---

## Usage

```bash
# Run all fixtures against all applicable personas
OPENROUTER_API_KEY=... uv run python evals/reviewer/run.py

# Run only fixtures expected to produce Adversarial findings
OPENROUTER_API_KEY=... uv run python evals/reviewer/run.py --persona reviewer-adversarial

# Run a single fixture against all applicable personas
OPENROUTER_API_KEY=... uv run python evals/reviewer/run.py --fixture r1

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
| `clean_for` | array | Optional. Personas that must produce no `[blocking]`/`[attention]` finding on this diff; they run on the fixture and count toward false positives |

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

### False positives

For each persona in a fixture's `clean_for`, the count of `[blocking]` and `[attention]` labels in its output is added to that persona's `false_positives`. The summary shows a "false pos" column; the baseline stores the count, and any increase is reported as a regression. Clean fixtures test that verification and the "not a finding" rules suppress noise, not just that bugs are caught.

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
| r1 | Behavioral regression — email fallback removed for active users | `reviewer-adversarial` | `blocking` |
| r2 | Silent failure — exception logged, function returns success | `reviewer-adversarial` | `blocking` |
| r3 | Timezone corruption — `replace(tzinfo=…)` overwrites the offset | `reviewer-code-quality` | `blocking`, `attention` |
| r4 | Scope discipline — new module boundary (Code Quality must NOT produce arch findings) | `reviewer-code-quality` | `blocking` |
| r5 | Prompt file verbosity regression — redundant restatements burying critical instruction | `reviewer-prompt-quality` | `blocking` |
| r6 | API backward-compat break — exported parameter removed | `reviewer-architecture` | `blocking` |
| r7 | Magic numbers — hardcoded TTL and refresh threshold (naming lane, formerly Fresh Eyes) | `reviewer-code-quality` | any |
| r8 | Incomplete error state — payment failure has no user message | `reviewer-product-flow` | `attention` |
| r9 | Spec with an untestable acceptance criterion | `specwriter-adversarial` | any |
| r10 | Spec task granularity violation — one task touches 5 files | `specwriter-scope` | any |
| r11 | Clean — guard visible in hunk context; an absence claim is a false positive | `clean_for`: adversarial, code-quality | — |
| r12 | Clean — small, tested, conventional refactor | `clean_for`: code-quality | — |

`baseline.json` predates the Fresh Eyes merge and the clean fixtures; re-run and re-baseline before comparing.
