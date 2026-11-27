Assessment: request-changes — the prune of dangling links is scoped to this checkout, but the empty-folder cleanup deletes any empty directory under the skill folder, including the user's own. That breaks the stated promise to leave user folders alone.

1. [blocking · 4] **`install.sh:27`** — empty-dir cleanup deletes user-owned empty folders, not just the ones pruning emptied
```
if [ "$pruned" -eq 1 ] && [ "$DRY_RUN" -eq 0 ]; then
  find "$d" -depth -type d -empty -delete
fi
```
The link pruning is carefully limited to links that point into `$SCRIPT_DIR`. The folder cleanup has no such limit: `find -type d -empty -delete` removes every empty directory under `$d`. A user may keep a placeholder or scratch folder in `~/.cursor/skills/<skill>/`, for example `notes/` or `my-refs/`. It is deleted as soon as one dangling link is pruned anywhere in that skill. The change description says install removes "the folders that pruning left empty", so this goes beyond that. It is also destructive and silent: dry-run prints nothing about these deletions, so the user can't preview them. The skill folder itself is also deleted if it is empty, which is probably intended. The only consumer is the install flow on the user's home directory, but the data loss lands on user-owned paths.

Fix: Record the parent directory of each pruned link. After pruning, walk up from each parent and `rmdir` it, which fails on non-empty directories, stopping at `$d`. Then `rmdir "$d"`. Add a matching `[dry-run]` line for these removals. For example, inside the loop after `rm -f "$link"`, run `p=$(dirname "$link"); while [[ "$p" != "${d%/}" ]] && rmdir "$p" 2>/dev/null; do p=$(dirname "$p"); done`. After the loop, run `rmdir "$d" 2>/dev/null || true`. This only removes directories that pruning actually emptied.