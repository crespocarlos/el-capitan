---
disable-model-invocation: true
name: crew-cleanup
description: "Remove stale worktrees interactively. Trigger: 'crew cleanup'."
---

# Worktree Cleanup

## When Invoked

### Step 1: Refresh remote state

```bash
~/.agent/bin/crew-worktree.py fetch
```

### Step 2: List all worktrees

```bash
~/.agent/bin/crew-worktree.py --list
```

That prints JSON: `worktrees` carries each one's `path`, `branch`, `main`, `merged`, and `gone`,
and `stale` names the paths a cleanup may offer. The main worktree is the one with `main: true`, and
it is never removed; `~/.agent/bin/crew-repo-info.py --root <path> --field branch` reads another
worktree's branch without changing directory.

### Step 3: Classify each worktree

For each non-main worktree, the `--list` fields already carry the verdict:

- **Gone**: `gone: true` — the branch's remote tracking ref is deleted
- **Merged**: `merged: true` — the branch is merged into the default branch
- **Active**: neither — still in use

```bash
DEFAULT_BRANCH=$(~/.agent/bin/crew-default-branch.sh)
```
### Step 4: Present the table

Show all worktrees with their status:

| #   | Path                | Branch         | Status |
| --- | ------------------- | -------------- | ------ |
| 1   | /path/to/worktree-a | feature/xyz    | gone   |
| 2   | /path/to/worktree-b | chore/cleanup  | merged |
| 3   | /path/to/worktree-c | feature/active | active |

If no stale worktrees (gone or merged), say "All worktrees are active. Nothing to clean up." and
stop.

### Step 5: Confirm removal

Ask: "Remove all stale worktrees? (or specify numbers to keep)"

### Step 6: Remove confirmed worktrees

For each confirmed removal:

```bash
~/.agent/bin/crew-worktree.py --remove <path> --branch <branch>               # merged
~/.agent/bin/crew-worktree.py --remove <path> --branch <branch> --force       # gone, confirmed in Step 5
```

One command per removal, because the worktree and its branch are one decision: it removes the
worktree first and deletes the branch only after that succeeded, so a refused worktree leaves its
branch alive. Report the refused worktree and leave its task directories in place; do not offer them
in the task-directory step below. If the branch delete refuses after the worktree is removed, the
command says so and keeps the branch — report it. `--force` is `-D`, so use it only for gone branches
the user confirmed; for those rows, show the unique-commit count in Step 4
(`git rev-list --count origin/$(~/.agent/bin/crew-default-branch.sh)..<branch>`). Squash-merged
branches show a nonzero count, so treat it as information, not proof of unmerged work.

Also remove associated task directories. Multiple tasks can share the same branch (the spec says
"Multiple specs can coexist per branch"), so collect all matches and confirm each individually
before removing:

```bash
WORKTREE_REMOTE=$(~/.agent/bin/crew-repo-info.py --root <worktree-path> --field remote_url 2>/dev/null || echo "")
WORKTREE_BRANCH=<branch>

# Collect all task dirs for this worktree's remote+branch using the resolve script
MATCHING_DIRS=()
while IFS= read -r dir; do
  [ -n "$dir" ] && MATCHING_DIRS+=("$dir")
done < <(~/.agent/bin/crew-resolve-task-dir.py   --remote "$WORKTREE_REMOTE" --branch "$WORKTREE_BRANCH" --all) || \
  echo "warning: could not enumerate task directories for '$WORKTREE_BRANCH'" >&2

if [ "${#MATCHING_DIRS[@]}" -eq 0 ]; then
  echo "No task directories found for branch '$WORKTREE_BRANCH'."
else
  for i in "${!MATCHING_DIRS[@]}"; do
    slug=$(python3 -c "import json; d=json.load(open('${MATCHING_DIRS[$i]}/.task-id')); print(d.get('slug','unknown'))" 2>/dev/null || echo "unknown")
    echo "  $((i+1)). ${MATCHING_DIRS[$i]} (slug: $slug)"
  done
fi
```

Ask for every listed task directory, even when only one matches: "Remove which task directories?
(all / none / comma-separated numbers)". Store the confirmed paths in `CONFIRMED_DIRS`, then remove
them:

```bash
root=$(cd "$HOME/.agent/tasks" && pwd -P)
for dir in "${CONFIRMED_DIRS[@]}"; do
  real=$(cd "$dir" 2>/dev/null && pwd -P) || { echo "skipped (missing): $dir" >&2; continue; }
  case "$real" in "$root"/?*) ;; *) echo "skipped (not a task directory): $dir" >&2; continue ;; esac
  [ -f "$real/.task-id" ] || { echo "skipped (no .task-id): $dir" >&2; continue; }
  rm -rf "$real" && echo "Removed task directory: $real"
done
```

### Step 6b: Prune a DONE task's scratch directories

A task directory keeps two things nothing else ever removes: `probes/`, where throwaway probe
scripts accumulate, and `review/<timestamp>/`, which holds persona packages and diffs. Both are
scratch. A `DONE` task's spec, `REPORT.md`, `REVIEW.md`, `DEFERRED.md`, and `DROPPED.md` are the
record and stay.

List the candidates first — only directories whose spec reads `DONE`:

```bash
for dir in "$HOME"/.agent/tasks/*/; do
  [ -f "$dir/SPEC.md" ] || continue
  if ! status=$(~/.agent/bin/crew-ls.py --status-file "$dir/SPEC.md"); then
    echo "error: cannot read status for $dir" >&2
    exit 1
  fi
  [ "$status" = "DONE" ] || continue
  for scratch in "$dir/probes" "$dir"/review/*/; do
    [ -d "$scratch" ] && echo "$(du -sh "$scratch" | cut -f1)  $scratch"
  done
done
```

Show that list and ask: "Delete which scratch directories? (all / none / comma-separated numbers)".
Never infer `all`. Remove each confirmed path with the same containment check Step 6 uses — resolve
it, require it to sit under a task directory that has a `.task-id`, and re-read the status:

```bash
root=$(cd "$HOME/.agent/tasks" && pwd -P)
for dir in "${CONFIRMED_SCRATCH[@]}"; do
  real=$(cd "$dir" 2>/dev/null && pwd -P) || { echo "skipped (missing): $dir" >&2; continue; }
  case "$real" in "$root"/*/probes|"$root"/*/review/*) ;; *)
    echo "skipped (not task scratch): $dir" >&2; continue ;; esac
  task=${real%/probes}; task=${task%/review/*}
  [ -f "$task/.task-id" ] || { echo "skipped (no .task-id): $dir" >&2; continue; }
  if ! status=$(~/.agent/bin/crew-ls.py --status-file "$task/SPEC.md"); then
    echo "error: cannot read status for $task; stopping before any removal" >&2
    exit 1
  fi
  [ "$status" = "DONE" ] || { echo "skipped (task is $status): $dir" >&2; continue; }
  rm -rf "$real" && echo "Removed scratch: $real"
done
```

Re-check the status inside the loop, not only when listing: the list may be minutes old, and a task
that went back to `IMPLEMENTING` is one whose probes are live again.

### Step 7: Summary

Show what was removed:

```
Removed N worktrees, N branches, N task directories.
```

List any that failed removal (e.g. uncommitted changes in the worktree — `crew-worktree.py
--remove` refuses). Also list worktrees removed with the branch kept (the branch delete refused) and
any skipped task directories.

## Rules

- Never remove the main worktree
- `--force` only for gone branches the user confirmed; merged branches use the plain `--remove`
- Always confirm before removing — never silent
- If a worktree has uncommitted changes, `crew-worktree.py --remove` refuses. Report it and skip it;
  this skill never forces removal. The user removes it manually.

## Plain-language gates

Use plain language, without compressed summaries, before:

- Running `crew-worktree.py --remove` on any worktree — list all worktrees to be removed plainly
  (path + branch) before executing; this cannot be undone without re-checking out the branch
- Any worktree with uncommitted changes — state the files at risk explicitly

Continue after confirmation.
