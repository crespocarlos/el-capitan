Assessment: request-changes — the empty-folder cleanup is broader than the stated "folders that pruning left empty" and will delete user-created empty folders, which the change says it must leave alone.

Read beyond the package: none

1. [attention · 4] **`install.sh:27`** — empty-dir sweep deletes the user's own empty folders, not just those pruning emptied
```
if [ "$pruned" -eq 1 ] && [ "$DRY_RUN" -eq 0 ]; then
  find "$d" -depth -type d -empty -delete
fi
```
The user may keep their own folders under `~/.cursor/skills/<skill>/`. Suppose they made an empty `notes/` or `scratch/` folder there, and one dangling link elsewhere in that skill gets pruned. The sweep then removes every empty directory under the skill, including `notes/`. It can also remove the skill folder itself. The comment and PR intent say only folders the pruning emptied should go. The dry-run branch also never reports these deletions, so a preview hides them.

Fix: Track the parent directories of the removed links (`dirname "$link"`). After removal, run `rmdir` on each parent and walk up toward `$d`, stopping at the first non-empty directory. Leave other empty directories alone. In dry-run, print the folders that would be removed.