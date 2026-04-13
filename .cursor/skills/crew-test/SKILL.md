---
name: crew-test
description: "Discover and run tests scoped to the current git diff. Trigger: 'crew test'."
---
**Workflow**: build | **Stage**: test

# Test Runner

## Execution model

**Single-shot output.** Load context, discover tests, run them, report results without intermediate narration. Only speak once — when all results are ready.

Target: 1 turn.
- Turn 1: resolve context + discover tests + run tests + surface manual checklist + verdict

Never narrate what you're doing. Never say "now running tests".

## When Invoked

### Step 1: Resolve TASK_DIR

```bash
TASK_DIR=$(~/.agent/tools/resolve-task-dir.sh) || exit 1
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

Launch `tester-explorer` as a subagent with a structured prompt containing two sections:

```
## Changed files
<one changed file path per line>

## Exported symbols
<one symbol per line>
```

Wait for tester-explorer to return its discovery summary.

### Step 5: Run the test command

Extract the test command from tester-explorer's `## Test command` output.

If the command is "none found", skip to Step 7 with WARN verdict.

Otherwise run:

```bash
cd $(git rev-parse --show-toplevel) && <test command>
```

Capture exit code and up to 30 lines of output.

### Step 6: Surface manual checklist

If `$TASK_DIR/SPEC.md` exists, extract and print the `### Manual` subsection under `## Tests`:

```bash
awk '/^### Manual/{found=1; next} found && /^###/{exit} found{print}' "$TASK_DIR/SPEC.md"
```

If no `## Tests` section or `### Manual` subsection exists, skip this step silently.

### Step 7: Verdict

Determine verdict:
- **PASS**: test command ran and exited 0
- **WARN**: no test files found, or no test command found
- **FAIL**: test command ran and exited non-zero

Output each test file discovered as:

```
[TEST] path/to/file.test.ts — covers: <symbols>
```

If verdict is FAIL, print up to 30 lines of test output.

If verdict is WARN with no test command: print `No test command found — skipping automated tests.`

Output: `Verdict: PASS` / `Verdict: WARN` / `Verdict: FAIL`

**Conclusion:**
- If PASS: "Tests passed. Run `crew diff` to continue."
- If WARN: "No tests found or no test command configured. Verify manually using the checklist above."
- If FAIL: "Tests failed. Fix the failures before proceeding."
