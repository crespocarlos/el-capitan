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

### Step 5: Run typed automated blocks

Extract test commands from the spec and from tester-explorer results using the following logic:

**If `$TASK_DIR/SPEC.md` contains typed blocks** (`### Unit`, `### Integration`, `### E2E`):
- For each typed block present (in order: Unit → Integration → E2E), extract its `Command` field.
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

### Step 6: Surface manual checklist

If `$TASK_DIR/SPEC.md` exists and has a `### Manual` subsection under `## Tests`:

```bash
awk '/^### Manual/{found=1; next} found && /^###/{exit} found{print}' "$TASK_DIR/SPEC.md"
```

**Auto-execute typed manual items** that have an inline **Pass:** criterion:
- `type: http` — item contains a `curl`/`fetch` command block and an inline `**Pass:**` criterion → run the curl command; compare output against the criterion; report PASS/FAIL.
- `type: data` — item contains a query/script (ES curl, SQL, Python) and an inline `**Pass:**` criterion → run the command; compare output against the criterion; report PASS/FAIL.
- `type: script` — item contains a shell or Python block and an inline `**Pass:**` criterion → run the command; compare exit code or output against the criterion; report PASS/FAIL.
- `type: playwright` — auto-execute when Navigate, Assert, and Pass sub-bullets are all present. Protocol:
  1. **Probe MCP availability**: attempt `mcp__playwright__navigate` with a dummy URL (e.g. `about:blank`). Any error (tool not found, connection refused, etc.) = MCP unavailable → fall through to human checklist for ALL playwright items.
  2. **Apply auth** (when MCP available): read `auth-approach` from tester-explorer's `### e2e` summary (NOT the spec item's `Auth` sub-bullet, which is human documentation only):
     - `storageState: <path>` → apply the storage state file via `mcp__playwright__context_storage_state`.
     - `process.env.*` / env-var pattern → set the referenced env var credentials before navigating.
     - `globalSetup` ref or "not detected" → log "no auth applied" and proceed.
  3. **Navigate**: call `mcp__playwright__navigate` with the item's `Navigate` URL.
  4. **Wait** (optional): if a `Wait` sub-bullet is present, call `mcp__playwright__wait_for_selector` with that selector before asserting.
  5. **Assert**: call `mcp__playwright__evaluate` to check that the `Assert` selector is visible on the page (equivalent to `state: 'visible'`). If the element is visible: report `[playwright] PASS — <Pass text>`. If not: report `[playwright] FAIL — selector not found: <Assert selector>`.
  6. **Fallback conditions**: if MCP unavailable, OR if Navigate, Assert, or Pass sub-bullet is missing → surface as human checklist entry.

**Surface as human checklist** (do not auto-execute):
- `type: visual` — print the item as a checklist entry.
- `type: judgment` — print the item as a checklist entry.
- Untagged items — treat as `type: judgment`; print as checklist entry.
- Any `type: http`, `type: data`, or `type: script` item that does NOT contain an inline `**Pass:**` criterion → print as checklist entry (never auto-execute without an explicit criterion).
- Any `type: playwright` item where MCP is unavailable OR Navigate, Assert, or Pass sub-bullet is missing → print as checklist entry.

If no `## Tests` section or `### Manual` subsection exists, skip this step silently.

### Step 7: Runbook detection

Check for a runbook alongside the spec:

```bash
test -f "$TASK_DIR/runbook.md"
```

If present, print its path and extract all `##`-level section headers:

```bash
grep "^## " "$TASK_DIR/runbook.md"
```

Output:
```
Runbook: $TASK_DIR/runbook.md
Sections:
  ## Prerequisites
  ## 1. Section Title
  ## Common Failures and Fixes
```

### Step 8: Verdict

Determine verdict:
- **PASS**: all automated blocks (typed or fallback) ran and exited 0; all auto-executed manual items passed
- **WARN**: no typed blocks, no extractable command from any format, and no `runbook.md` found; or no test files found
- **FAIL**: any automated block or auto-executed manual item exited non-zero

Output each test file discovered as:

```
[TEST] path/to/file.test.ts — covers: <symbols>
```

For each typed block run:
```
[Unit] PASS/FAIL — <command>
[Integration] PASS/FAIL — <command>
[E2E] PASS/FAIL — <command>
```

If verdict is FAIL, print up to 30 lines of failing output.

If verdict is WARN with no command: print `No test command found — skipping automated tests.`

Output: `Verdict: PASS` / `Verdict: WARN` / `Verdict: FAIL`

**Conclusion:**
- If PASS: "Tests passed. Run `crew diff` to continue."
- If WARN: "No tests found or no test command configured. Verify manually using the checklist above."
- If FAIL: "Tests failed. Fix the failures before proceeding."
