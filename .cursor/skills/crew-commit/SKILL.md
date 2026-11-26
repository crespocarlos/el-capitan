---
disable-model-invocation: true
name: crew-commit
description: "Generate a semantic commit message and commit. Trigger: 'crew commit'."
---

**Workflow**: build | **Stage**: commit

# Semantic Commit

## When Invoked

### Step 1: Gather context (parallel)

Run these simultaneously:

```bash
git diff --staged --stat          # size check + file list
~/.agent/bin/crew-repo-info.py --field staged     # file list for scope check

source ~/.agent/bin/task-env.sh
~/.agent/bin/crew-task-context.py --artifacts spec,review --max-chars 4000
```

If nothing staged, run `git status --short` and show the user what's unstaged. Ask which files to
stage — never `git add -A` without explicit approval (it can pick up .env files, debug logs, scratch
files).

### Step 2: Read the diff (fast path first)

**Fast path — use when `$TASK_DIR/REVIEW.md` exists AND the reviewed tree is unchanged since the
review:**

The review records the identity it approved. Verify all three:

```bash
~/.agent/bin/crew-repo-info.py --field head          # compare to "Reviewed at:" in REVIEW.md
~/.agent/bin/crew-repo-info.py --field staged | sort # compare to "### Files reviewed"
~/.agent/bin/crew-repo-info.py --field staged_dirty  # must be empty: no unstaged edits
```

Compare `HEAD` against the `Reviewed at:` line, the staged list against `### Files reviewed`, and
require `staged_dirty` to print nothing — an edited-but-restaged file keeps the same staged name set,
so the file list alone cannot prove the review still applies. Any mismatch (new file, removed file,
different path, new commits, or unstaged edits) → fall back to slow path.

If the file set matches: use the returned REVIEW.md and SPEC.md contents when present for intent
context. Skip reading the full diff unless the review summary is insufficient to determine type and
scope. If either artifact is marked `TRUNCATED`, read `$TASK_DIR/REVIEW.md` or `$TASK_DIR/SPEC.md`
directly before judging the fast path — the identity fields live at the end of the review.

**Slow path — use when REVIEW.md is absent:**

Read the full staged diff: `git diff --staged`. Use the returned SPEC.md when present for intent
context.

## Commit Message Format

Single line. [Conventional Commits](https://www.conventionalcommits.org/):

```
<type>(<scope>): <imperative description>
```

Examples:

```
feat(evals): convert feature duplication evaluators to createPrompt pattern
fix(streams): handle empty feature array in duplication check
refactor(synthtrace): extract template generation into separate module
test(evals): add semantic uniqueness evaluator coverage
chore(deps): bump @kbn/inference-common to 1.4.0
```

### Types

- `feat` — new feature or capability
- `fix` — bug fix
- `refactor` — code change that neither fixes a bug nor adds a feature
- `test` — adding or updating tests
- `chore` — maintenance, dependency updates, config changes
- `docs` — documentation only
- `perf` — performance improvement

### Rules

- Imperative mood ("add", not "added" or "adds")
- No period at the end
- Max 72 characters total
- Scope from the primary directory or module changed, lowercase
- If SPEC.md exists, the message should reflect its goal
- Never multi-line for branch commits — the PR description carries the context

### Step 2b: Out-of-scope check

Before proposing the commit message, check for out-of-scope modifications. `TASK_DIR` was already
resolved in Step 1.

If `$TASK_DIR/BASELINE.diff` exists:

1. List currently modified files: `git diff --name-only HEAD`
2. For each modified file, check if its name (basename or relative path) appears as a literal string
   in `$TASK_DIR/SPEC.md`:
   ```bash
   grep -q "<filename>" "$TASK_DIR/SPEC.md"
   ```
3. For each modified file whose name does **not** appear as a literal string in SPEC.md, emit: >
   "Out-of-scope warning: [file] was modified but is not referenced in SPEC.md."

Surface all warnings before proposing the commit message. The user decides whether to proceed,
remove the files from staging, or update the spec.

### Step 2c: Gates

Run the repository's gates as its CI does: `~/.agent/bin/crew-progress.py verify --task-dir
"$TASK_DIR"` (passes on an unchanged tree are cached; no task: `--out /tmp/gates.json`). It reads the
commands from the base branch, never the PR head, and prints `<name> exit=<N>`. Act on the outcome
per `~/.cursor/skills/crew-implement/references/verify-outcomes.md`.

### Step 3: Commit

Generate the message. Then:

**Auto-commit (default)** — the explicit `crew commit` invocation approves committing. If all of the
following are true, commit immediately:
- Message follows `type(scope): description` format
- Message is ≤72 characters
- No out-of-scope warnings from Step 2b
- Type and scope were unambiguously derivable from the diff/SPEC/REVIEW
- verify exited 0 (Step 2c)

```bash
git commit -m "<the message>"
```

Show the committed message after: `Committed: <hash> — <message>`

**Pause for approval** — only when one or more of these is true:
- Type or scope is ambiguous (multiple plausible options)
- Out-of-scope files detected (Step 2b warnings)
- Message would exceed 72 characters
- The diff touches an unusual combination of areas with no clear single scope
- verify exited nonzero (Step 2c): act on it per the verify outcomes before any commit

In pause mode, show the proposed message and ask: "Look good?" before committing.

After a successful commit, log the event using the already-resolved `$TASK_DIR`. A commit does not
change pipeline state, so this is a `METRIC` audit line, not a `TRANSITION`:

```bash
if [ "${CREW_TASK_STATE:-ok}" = "error" ]; then
  echo "warning: task state unreadable — commit not logged to PROGRESS.md" >&2
elif [ -n "$TASK_DIR" ]; then
  ~/.agent/bin/crew-metric.py "$TASK_DIR" commit sha="$(~/.agent/bin/crew-repo-info.py --field head_short)"
fi
```

## Plain-language gates

Use plain language before:

- Presenting the commit message for confirmation (pause mode only; auto-commit shows the message
  after committing) — show the full message verbatim, not compressed; the user is approving the
  exact text that will be permanent in git history
- Any `git commit --amend` operation — state clearly it rewrites the last commit

Continue after the user approves the message.

If a PR is already open for this branch, push the commit directly instead of opening a new one.

> Next: run `crew open pr` to push and open a PR.
