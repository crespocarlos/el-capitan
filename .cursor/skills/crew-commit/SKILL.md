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
git diff --staged --name-only     # file list for scope check

if [ -n "${CREW_TASK_DIR+x}" ]; then
  TASK_DIR="$CREW_TASK_DIR"
else
  TASK_DIR=$(~/.agent/bin/resolve-task-dir.py 2>/dev/null || echo "")
  export CREW_TASK_DIR="$TASK_DIR"
fi
```

If nothing staged, run `git status --short` and show the user what's unstaged. Ask which files to stage — never `git add -A` without explicit approval (it can pick up .env files, debug logs, scratch files).

### Step 2: Read the diff (fast path first)

**Fast path — use when `$TASK_DIR/REVIEW.md` exists AND staged files haven't changed since the review:**

First verify the staged file set still matches the review. Run:
```bash
git diff --name-only --cached | sort
```
Compare against the file list in `REVIEW.md`. Any mismatch (new file, removed file, or different path) → fall back to slow path.

If the file set matches: read `$TASK_DIR/REVIEW.md` and `$TASK_DIR/SPEC.md` (if present) for intent context. Skip reading the full diff unless the REVIEW.md summary is insufficient to determine type and scope.

**Slow path — use when REVIEW.md is absent:**

Read the full staged diff: `git diff --staged`. If `$TASK_DIR` is non-empty, also read `$TASK_DIR/SPEC.md` for intent context.

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

Before proposing the commit message, check for out-of-scope modifications. `TASK_DIR` was already resolved in Step 2 above.

If `$TASK_DIR/BASELINE.diff` exists:

1. List currently modified files: `git diff --name-only HEAD`
2. For each modified file, check if its name (basename or relative path) appears as a literal string in `$TASK_DIR/SPEC.md`:
   ```bash
   grep -q "<filename>" "$TASK_DIR/SPEC.md"
   ```
3. For each modified file whose name does **not** appear as a literal string in SPEC.md, emit:
   > "Out-of-scope warning: [file] was modified but is not referenced in SPEC.md."

Surface all warnings before proposing the commit message. The user decides whether to proceed, remove the files from staging, or update the spec.

### Step 3: Commit

Generate the message. Then:

**Auto-commit (default)** — if all of the following are true, commit immediately without asking:
- Message follows `type(scope): description` format
- Message is ≤72 characters
- No out-of-scope warnings from Step 2b
- Type and scope were unambiguously derivable from the diff/SPEC/REVIEW

```bash
git commit -m "<the message>"
```

Show the committed message after: `Committed: <hash> — <message>`

**Pause for approval** — only when one or more of these is true:
- Type or scope is ambiguous (multiple plausible options)
- Out-of-scope files detected (Step 2b warnings)
- Message would exceed 72 characters
- The diff touches an unusual combination of areas with no clear single scope

In pause mode, show the proposed message and ask: "Look good?" before committing.

After a successful commit, log the transition using the already-resolved `$TASK_DIR`:

```bash
if [ -n "$TASK_DIR" ]; then
  ~/.agent/bin/log-progress.py "$TASK_DIR" "COMMITTING: committed $(git rev-parse --short HEAD)"
fi
```

> Next: run `crew open pr` to push and open a PR, or push directly if a PR is already open.

## Auto-clarity override

Drop to plain language before:

- Presenting the commit message for confirmation — show the full message verbatim, not compressed; the user is approving the exact text that will be permanent in git history
- Any `git commit --amend` operation — state clearly it rewrites the last commit

Resume compressed mode after the user approves the message.
