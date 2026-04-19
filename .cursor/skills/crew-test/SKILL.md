---
name: crew-test
description: "Discover and run tests scoped to the current git diff. Trigger: 'crew test'."
---
**Workflow**: build | **Stage**: test

# Test Runner

## Execution model

**Single-shot output, 1 turn.** Resolve context, discover, run, report — without intermediate narration. Never say "now running tests".

## When Invoked

### Step 1: Resolve TASK_DIR

```bash
if [ -n "${CREW_TASK_DIR+x}" ]; then
  TASK_DIR="$CREW_TASK_DIR"
else
  TASK_DIR=$(~/.agent/tools/resolve-task-dir.py) || exit 1
  export CREW_TASK_DIR="$TASK_DIR"
fi
```

### Step 2: Get changed files

```bash
source ~/.agent/scripts/get-diff.sh --full
```

If that exits 1 (no committed changes on branch), fall back:

```bash
CHANGED_FILES=$(git diff --cached --name-only)
```

If that returns empty, fall back:

```bash
CHANGED_FILES=$(git diff --name-only)
```

### Step 3: Extract exported symbols

```bash
grep -h "^export " $CHANGED_FILES 2>/dev/null | grep -oP "(?<=export (function|class|const|type|interface) )\w+"
```

If no symbols are found, use the basenames of changed files (without extension) as symbol identifiers.

### Step 4: Dispatch tester-explorer

**Pre-check before dispatch** — skip tester-explorer when discovery would be redundant:

1. If `$TASK_DIR/SPEC.md` exists and all typed blocks (`### Unit`, `### Integration`, `### E2E`, `### Validation`) that are **present** have a `**Command**` value that is not `"none"` or empty → the spec already has commands; skip to Step 5 using those commands.
2. If all `CHANGED_FILES` have non-source extensions (`.md`, `.mdc`, `.json`, `.yaml`, `.toml`, `.sh`, `.py` config-only) → no importable symbols exist; skip to Step 7 with WARN verdict.

Otherwise, launch `tester-explorer` as a subagent with a structured prompt:

```
## Changed files
<one changed file path per line>

## Exported symbols
<one symbol per line>
```

Wait for tester-explorer to return its discovery summary.

### Step 5: Run typed automated blocks

Extract test commands from the spec and from tester-explorer results using the following logic:

**If `$TASK_DIR/SPEC.md` contains typed blocks** (`### Unit`, `### Integration`, `### E2E`, `### Validation`):
- For each typed block present (in order: Unit → Integration → E2E → Validation), extract its `Command` field.
- Skip blocks whose `Command` is `"none"` or empty.
- Run each command in sequence:
  ```bash
  cd $(git rev-parse --show-toplevel) && <command>
  ```
- Capture exit code and up to 30 lines of output per block.
- A block PASSES if exit code is 0; FAILS otherwise.

**Backward-compat fallback (no typed blocks in SPEC.md):**
- If tester-explorer returned `## Frameworks`, extract the `unit` layer command and run it.
- If tester-explorer returned the old `## Test command` format, use that command directly.
- If no command is found from any format, skip to Step 7 with WARN verdict.

### Step 6: Runbook (scriptable only) + legacy SPEC guard

**Deprecated `### Manual` under `## Tests`:** If `$TASK_DIR/SPEC.md` still contains `### Manual` under `## Tests`, print one line only:
```
[crew-test] WARN: SPEC still uses ### Manual under ## Tests — migrate checks to Acceptance Criteria, typed ## Tests, and scriptable runbook.md. Skipping that block.
```
Do not execute legacy Manual items.

**`$TASK_DIR/runbook.md`:** If the file exists, process each top-level `## ` section in order, **except** `## Prerequisites` and `## Common Failures and Fixes`:

- **Skip with WARN** (one line per section): section title or body indicates `type: visual`, `type: judgment`, or human-only QA; or the section has **no** fenced shell (bash/sh) code block with a following `**Pass:**` / `Pass:` line suitable for deterministic checks.
- **Auto-execute** (same spirit as former manual `type: script`): section contains a fenced shell block and an inline `**Pass:**` or `Pass:` criterion → run the extracted command from repo root (`cd $(git rev-parse --show-toplevel) && …`); compare exit code/output to the criterion; report PASS/FAIL.

If no `runbook.md`, skip silently (unless WARN above).

### Step 7: Runbook outline

If `$TASK_DIR/runbook.md` exists:

```bash
test -f "$TASK_DIR/runbook.md" && grep "^## " "$TASK_DIR/runbook.md"
```

Prefix output with `Runbook: $TASK_DIR/runbook.md` and `Sections:` for operator visibility.

### Step 8: Verdict

Determine verdict:
- **PASS**: all typed blocks (or fallback) ran and exited 0; all auto-executed runbook scripted steps passed
- **WARN**: no typed blocks, no extractable command from any format, and no `runbook.md` found; or no test files found
- **FAIL**: any typed block or auto-executed runbook step exited non-zero

Output each test file discovered as:

```
[TEST] path/to/file.test.ts — covers: <symbols>
```

For each typed block run:
```
[Unit] PASS/FAIL — <command>
[Integration] PASS/FAIL — <command>
[E2E] PASS/FAIL — <command>
[Validation] PASS/FAIL — <command>
```

If verdict is FAIL, print up to 30 lines of failing output.

If verdict is WARN with no command: print `No test command found — skipping automated tests.`

Output: `Verdict: PASS` / `Verdict: WARN` / `Verdict: FAIL`

**Conclusion:**
- If PASS: "Tests passed. Run `crew review` to continue."
- If WARN: "No tests found or no test command configured. Verify manually using the checklist above."
- If FAIL: "Tests failed. Fix the failures before proceeding."
