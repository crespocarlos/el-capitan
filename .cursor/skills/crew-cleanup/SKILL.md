---
disable-model-invocation: true
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
DEFAULT_BRANCH=$(~/.agent/bin/default-branch.sh)
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
git worktree remove <path> && git branch -d <branch>   # merged
git worktree remove <path> && git branch -D <branch>   # gone, confirmed in Step 5
```

Chain with `&&`: if removal is refused, the branch must survive. Report the refused worktree and leave its task directories in place; do not offer them in the task-directory step below. If `-d` refuses after the worktree is removed, keep the branch and report it. Use `-D` only for gone branches the user confirmed; for those rows, show the unique-commit count in Step 4 (`git rev-list --count origin/$(~/.agent/bin/default-branch.sh)..<branch>`). Squash-merged branches show a nonzero count, so treat it as information, not proof of unmerged work.

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
else
  for i in "${!MATCHING_DIRS[@]}"; do
    slug=$(python3 -c "import json; d=json.load(open('${MATCHING_DIRS[$i]}/.task-id')); print(d.get('slug','unknown'))" 2>/dev/null || echo "unknown")
    echo "  $((i+1)). ${MATCHING_DIRS[$i]} (slug: $slug)"
  done
fi
```

Ask for every listed task directory, even when only one matches: "Remove which task directories? (all / none / comma-separated numbers)". Store the confirmed paths in `CONFIRMED_DIRS`, then remove them:

```bash
root=$(cd "$HOME/.agent/tasks" && pwd -P)
for dir in "${CONFIRMED_DIRS[@]}"; do
  real=$(cd "$dir" 2>/dev/null && pwd -P) || { echo "skipped (missing): $dir" >&2; continue; }
  case "$real" in "$root"/?*) ;; *) echo "skipped (not a task directory): $dir" >&2; continue ;; esac
  [ -f "$real/.task-id" ] || { echo "skipped (no .task-id): $dir" >&2; continue; }
  rm -rf "$real" && echo "Removed task directory: $real"
done
```

### Step 7: Summary

Show what was removed:

```
Removed N worktrees, N branches, N task directories.
```

List any that failed removal (e.g. uncommitted changes in the worktree — `git worktree remove` will refuse). Also list worktrees removed with the branch kept (`-d` refused) and any skipped task directories.

## Rules

- Never remove the main worktree
- `git branch -D` only for gone branches the user confirmed; merged branches use `-d`
- Always confirm before removing — never silent
- If a worktree has uncommitted changes, `git worktree remove` refuses. Report it and skip it; this skill never forces removal. The user removes it manually.

## Plain-language gates

Use plain language, without compressed summaries, before:

- Running `git worktree remove` on any worktree — list all worktrees to be removed plainly (path + branch) before executing; this cannot be undone without re-checking out the branch
- Any worktree with uncommitted changes — state the files at risk explicitly

Continue after confirmation.
