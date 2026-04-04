# crew abandon

Gracefully abandons the current task — records the reason, stashes changes, and writes a SESSION.md stub for later reference.

## Protocol

### Step 1: Get reason

Prompt the user for a one-sentence reason for abandoning the task:

> "What is the reason for abandoning this task? (one sentence)"

Store the response as `<reason>`.

### Step 2: Resolve task directory

```bash
TASK_DIR=$(~/.agent/tools/resolve-task-dir.sh 2>/dev/null || echo "")
```

If `$TASK_DIR` is empty, no active task was found for this repo+branch — proceed without task directory operations.

### Step 3: Append ABANDONED to PROGRESS.md

```bash
echo "[$(date '+%Y-%m-%d %H:%M:%S')] ABANDONED: <reason>" >> "$TASK_DIR/PROGRESS.md"
```

### Step 4: Stash changes (if any)

Check if there are uncommitted changes:

```bash
git status --porcelain
```

- If output is **non-empty**: run `git stash push -m "abandoned: <reason>"`
- If output is **empty** (clean working tree): append to PROGRESS.md:
  ```
  [$(date '+%Y-%m-%d %H:%M:%S')] Nothing to stash
  ```

### Step 5: Write SESSION.md stub

Write `$TASK_DIR/SESSION.md` with the following content:

```markdown
# Session Summary

**Date:** <YYYY-MM-DD>
**Branch:** <branch>
**Reason abandoned:** <reason>

## Notes

```

Use the current date (`date '+%Y-%m-%d'`) and `git branch --show-current` for the values.

### Step 6: Confirm

Output:
```
Task abandoned.
- Reason logged to PROGRESS.md
- Stash: <stashed / nothing to stash>
- SESSION.md stub written to <path>
```
