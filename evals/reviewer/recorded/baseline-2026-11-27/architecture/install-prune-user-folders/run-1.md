Assessment: request-changes — the empty-folder cleanup is not limited to folders that pruning emptied, so it can delete the user's own empty folders in a skill directory.

1. [blocking · 4] **`install.sh:27`** — empty-dir cleanup removes any empty folder, not only those the prune emptied
```
if [ "$pruned" -eq 1 ] && [ "$DRY_RUN" -eq 0 ]; then
  find "$d" -depth -type d -empty -delete
fi
```
The change says the skill folder is one "the user may also keep their own files and folders in", and that install removes "the folders that pruning left empty". `-type d -empty -delete` has no link to the pruning. Once any dangling link is pruned in a skill, every empty directory under `~/.cursor/skills/<skill>/` is deleted. That includes user-created placeholders such as `notes/`, or `references/` when the user has emptied it on purpose. The guards on the symlink removal ("a regular file is the user's, so both stay") are not applied to directories. The `pruned` flag is also per skill, so one stale link anywhere in the skill exposes every empty folder in it. The harm is unannounced deletion of user-owned paths. It is small in data terms but breaks the stated ownership contract. The line is new in this diff, so the defect is not pre-existing.

Fix: Collect the parent directories of the links you actually removed. After removal, walk up from each parent and `rmdir` it, which fails on non-empty directories. Stop at `$d` or at the first failure. Never run a blanket `find -empty -delete`.

2. [attention · 3] **`install.sh:27`** — dry-run and real runs do not report directory removals
```
if [ "$pruned" -eq 1 ] && [ "$DRY_RUN" -eq 0 ]; then
  find "$d" -depth -type d -empty -delete
```
Dry-run prints the link removals but not which folders would be deleted. Real runs delete folders silently. A user previewing with `--dry-run` therefore cannot see the destructive part from finding 1. That part is the risky one.

Fix: When pruning parent directories (per finding 1), print `[dry-run] remove empty dir: …` or `Removing empty dir: …` for each one. Use the same branch structure as the symlink removal.