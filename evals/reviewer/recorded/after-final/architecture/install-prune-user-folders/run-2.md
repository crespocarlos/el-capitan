Assessment: request-changes — the symlink prune is scoped to links into this checkout, but the folder cleanup is not, and it deletes folders the user owns.
Read beyond the package: none (only grepped install.sh for the line number)

1. [blocking · 5] **`install.sh:27`** — empty-folder cleanup deletes the user's own empty folders, not only the ones pruning emptied
```
if [ "$pruned" -eq 1 ] && [ "$DRY_RUN" -eq 0 ]; then
  find "$d" -depth -type d -empty -delete
```
The skill folder is shared with the user, and the change itself says link-pruning must leave the user's files alone. This `find` matches every empty directory under the skill folder, whatever its origin. Say a user keeps an empty `~/.cursor/skills/foo/notes/` or `scratch/`, and one stale link is pruned elsewhere in `foo`. The next install then deletes `notes/` and `scratch/`. If pruning leaves the skill folder itself empty, `-depth` deletes it too, including one the user created as a placeholder. The dry-run branch prints nothing about these removals, so the user is not warned either.
Fix: Remove only the parent directories of the links just pruned, deepest first. Record each `$(dirname "$link")` while pruning. Then `rmdir` each one, and its parents up to `$d`, stopping at the first non-empty folder. `rmdir` fails on a non-empty folder, so it is safe. Also print each folder removal in dry-run mode.

2. [attention · 3] **`install.sh:19`** — the prune matches only absolute link targets that start with `$SCRIPT_DIR/`
```
[[ "$target" == "$SCRIPT_DIR"/* && ! -e "$link" ]] || continue
```
This is only safe if `link_dir_files` and the `ln -sf` calls always write absolute targets. I did not verify that, so I'm assuming it. If `SCRIPT_DIR` is reached through a different path (a symlinked checkout, or a moved checkout), stale links stay. The old code had the same prefix assumption, so this is partly pre-existing.
Fix: Confirm that the links are always absolute and that `SCRIPT_DIR` is resolved the same way (`cd … && pwd -P`) in both the creating and pruning code.

### Findings: 2