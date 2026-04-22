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
```

### Step 4: Present the table

Show all worktrees with their status:

| #   | Path                | Branch         | Status |
| --- | ------------------- | -------------- | ------ |
| 1   | /path/to/worktree-a | feature/xyz    | gone   |
| 2   | /path/to/worktree-b | chore/cleanup  | merged |
| 3   | /path/to/worktree-c | feature/active | active |

If no stale worktrees (gone or merged), say "All worktrees are active. Nothing to clean up." and stop.

### Step 5: Confirm removal

Ask: "Remove all stale worktrees? (or specify numbers to keep)"

### Step 6: Remove confirmed worktrees

For each confirmed removal:

```bash
git worktree remove <path>
git branch -D <branch>
```

Also remove associated task directories. Multiple tasks can share the same branch (the spec says "Multiple specs can coexist per branch"), so collect all matches and confirm each individually before removing:

```bash
WORKTREE_REMOTE=$(git -C <worktree-path> remote get-url origin 2>/dev/null || echo "")
WORKTREE_BRANCH=<branch>

# Collect all task dirs for this worktree's remote+branch using the resolve script
MATCHING_DIRS=()
while IFS= read -r dir; do
  [ -n "$dir" ] && MATCHING_DIRS+=("$dir")
done < <(~/.agent/bin/resolve-task-dir.py   --remote "$WORKTREE_REMOTE" --branch "$WORKTREE_BRANCH" --all 2>/dev/null || true)

if [ "${#MATCHING_DIRS[@]}" -eq 0 ]; then
  echo "No task directories found for branch '$WORKTREE_BRANCH'."
elif [ "${#MATCHING_DIRS[@]}" -eq 1 ]; then
  rm -rf "${MATCHING_DIRS[0]}"
  echo "Removed task directory: ${MATCHING_DIRS[0]}"
else
  # Multiple tasks for the same branch — present each and ask which to remove
  echo "Found ${#MATCHING_DIRS[@]} task directories for branch '$WORKTREE_BRANCH':"
  for i in "${!MATCHING_DIRS[@]}"; do
    slug=$(python3 -c "import json; d=json.load(open('${MATCHING_DIRS[$i]}/.task-id')); print(d.get('slug','unknown'))" 2>/dev/null || echo "unknown")
    echo "  $((i+1)). ${MATCHING_DIRS[$i]} (slug: $slug)"
  done
  # Ask: "Remove which task directories? (all / none / comma-separated numbers)"
  # Remove only those the user confirms
fi
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

## Auto-clarity override

Drop to plain language before:

- Running `git worktree remove` on any worktree — list all worktrees to be removed plainly (path + branch) before executing; this cannot be undone without re-checking out the branch
- Any worktree with uncommitted changes — state the files at risk explicitly

Resume compressed mode after confirmation.
