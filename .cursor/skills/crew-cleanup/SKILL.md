---
name: crew-cleanup
description: "Remove stale worktrees interactively. Trigger: 'crew cleanup'."
---

# Worktree Cleanup

## When Invoked

### Step 1: Refresh remote state

```bash
git fetch --prune --quiet
```

### Step 2: List all worktrees

```bash
git worktree list
```

Parse each worktree path and its checked-out branch. Identify the main worktree (from `git rev-parse --show-toplevel`) — it is never removed.

### Step 3: Classify each worktree

For each non-main worktree, determine its status:

- **Gone**: branch's remote tracking ref is deleted (`git branch -vv` shows `: gone]`)
- **Merged**: branch is merged into the default branch (`git branch --merged origin/<default>`)
- **Active**: neither gone nor merged — still in use

```bash
DEFAULT_BRANCH=$(git remote show origin | grep 'HEAD branch' | awk '{print $NF}')
REPO=$(basename $(git rev-parse --show-toplevel))
```

### Step 4: Present the table

Show all worktrees with their status:

| # | Path | Branch | Status |
|---|------|--------|--------|
| 1 | /path/to/worktree-a | feature/xyz | gone |
| 2 | /path/to/worktree-b | chore/cleanup | merged |
| 3 | /path/to/worktree-c | feature/active | active |

If no stale worktrees (gone or merged), say "All worktrees are active. Nothing to clean up." and stop.

### Step 5: Confirm removal

Ask: "Remove all stale worktrees? (or specify numbers to keep)"

### Step 6: Remove confirmed worktrees

For each confirmed removal:

```bash
git worktree remove <path>
git branch -D <branch>
```

Also remove the task directory if it exists:

```bash
rm -rf ~/.agent/tasks/$REPO/<branch>/
```

### Step 7: Summary

Show what was removed:

```
Removed N worktrees, N branches, N task directories.
```

List any that failed removal (e.g. uncommitted changes in the worktree — `git worktree remove` will refuse).

## Rules

- Never remove the main worktree
- Always confirm before removing — never silent
- If a worktree has uncommitted changes, warn the user and skip unless they confirm with `--force`
