---
name: crew-test
description: "Discover and run tests scoped to the current git diff. Use only when the user explicitly asks to run or verify tests for the current changes. Alias: 'crew test'."
---

**Workflow**: build | **Stage**: test

# Test Runner

## Execution model

**Single-shot output, 1 turn.** Resolve context, discover, run, report — without intermediate
narration. Never say "now running tests".

## When Invoked

### Step 1: Resolve TASK_DIR

```bash
source ~/.agent/bin/task-env.sh
```

If `TASK_DIR` is empty, stop with: "No active task. Run `crew spec` first, or set `CREW_TASK_DIR`."
Do not use `exit`; it can close the agent shell.

### Step 2: Get changed files

```bash
source ~/.agent/bin/get-diff.sh --full
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
printf '%s\n' "$CHANGED_FILES" | while IFS= read -r file; do
  [ -f "$file" ] || continue
  grep -h '^export ' "$file"
done | sed -nE 's/^export (async )?(function|class|const|type|interface|enum) ([A-Za-z0-9_]+).*/\3/p'
```

`sed -nE` is POSIX and works on BSD and GNU; `grep -oP` is a GNU extension and fails on macOS, which
silently degraded discovery to file basenames.

If no symbols are found, use the basenames of changed files (without extension) as symbol
identifiers.

### Step 4: Dispatch tester-explorer

**Pre-check before dispatch** — skip tester-explorer when discovery would be redundant:

1. If `$TASK_DIR/SPEC.md` exists and all typed blocks (`### Unit`, `### Integration`, `### E2E`,
   `### Validation`) that are **present** have a `**Command**` value that is not `"none"` or empty →
   the spec already has commands; skip to Step 5 using those commands.
2. If all `CHANGED_FILES` have non-source extensions (`.md`, `.mdc`, `.json`, `.yaml`, `.toml`) → no
   importable symbols exist; skip to Step 6 with WARN verdict.

Otherwise, launch `tester-explorer` as a subagent with a structured prompt:

```
## Changed files
<one changed file path per line>

## Exported symbols
<one symbol per line>

## Project guidance
<output of `~/.agent/bin/agent-context.py <changed files>`>
```

Wait for tester-explorer to return its discovery summary.

### Step 5: Run typed automated blocks

Extract test commands from the spec and from tester-explorer results using the following logic:

**Jest path grouping:** When a requested command is `node scripts/jest` with explicit test paths,
first group those paths by their nearest ancestor `jest.config.js` (walk upward from each test file
to the repository root). Run one command per group, passing only that group's paths:

```bash
node scripts/jest --config <nearest-jest.config.js> <path-in-that-config> [...]
```

Never pass test paths belonging to different nearest Jest configs to one `node scripts/jest`
invocation. Report one `[Unit]` result per config group. If a path has no ancestor `jest.config.js`,
do not guess: report WARN for that path and run no command for it.

**If `$TASK_DIR/SPEC.md` contains typed blocks** (`### Unit`, `### Integration`, `### E2E`, `###
Validation`):

- For each typed block present (in order: Unit → Integration → E2E → Validation), extract its
  `Command` field.
- Skip blocks whose `Command` is `"none"` or empty.
- Run each command in sequence:
  ```bash
  cd $(git rev-parse --show-toplevel) && <command>
  ```
- Capture exit code and up to 30 lines of output per block.
- A block PASSES if exit code is 0; FAILS otherwise.

**Fallback (no typed blocks in SPEC.md):** if tester-explorer returned `## Frameworks`, extract the
`unit` layer command and run it. If no command is found, skip to Step 6 with WARN verdict.

### Step 6: Verdict

Determine verdict:

- **PASS**: all typed blocks (or fallback) ran and exited 0
- **WARN**: no typed blocks and no extractable command; or no test files found
- **FAIL**: any typed block exited non-zero

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

**Conclusion:**

- If PASS: print `Verdict: PASS` then `> Next: run \`crew review\` to continue.`
- If WARN: print `Verdict: WARN` then `> Next: no test command found — verify the SPEC.md acceptance
  criteria manually, then run \`crew review\`.`
- If FAIL: print `Verdict: FAIL` then `> Next: fix the test failures, then re-run \`crew test\`.`

## Plain-language gates

No gate applies, because test discovery and test commands are not irreversible. If a test command
modifies shared state (for example, writes to a production database), say so plainly and ask for
confirmation before running it.
