Assessment: request-changes — the empty-folder cleanup is broader than what the change says it does, so it deletes folders the user owns.

Read beyond the package: none (install.sh was the only file in the working directory).

Approach: endorse — Extending the existing prune loop to walk the whole skill folder is the smallest design. It beat both a per-file manifest of installed links and an `rm -rf` of each skill folder before relinking. Both of those would damage the user's own files or add state that has to be kept in sync.

Alternatives considered:
- Don't change anything and only prune a skill's SKILL.md — this leaves dangling reference links, which is the need this change exists to meet.
- Keep a manifest of the links install created and remove exactly those — it is precise, but it adds a state file that must be migrated and kept in sync. The existing `readlink` check against `$SCRIPT_DIR` already identifies our links without any state.
- Wipe and relink each skill folder — it is simple, but it destroys the user's own files in the same folder.

1. [blocking · 4] **`install.sh:27`** — empty-folder cleanup removes the user's own empty folders, not only the ones pruning emptied
```
if [ "$pruned" -eq 1 ] && [ "$DRY_RUN" -eq 0 ]; then
  find "$d" -depth -type d -empty -delete
fi
```
The user may keep their own folders in `~/.cursor/skills/<skill>/`, for example an empty `notes/` or `scratch/` they made for later. If one stale link is pruned anywhere in that skill, this `find` runs over the whole skill folder. It deletes every empty directory in it, including the user's. If the skill folder itself ends up empty, it is deleted too. Nothing is printed for these removals. The dry-run branch also never reports which folders would be removed, so the user cannot preview the deletion. The change describes this as removing "the folders that pruning left empty", and the code does more than that.
Fix: Remove only the parent directories of links that were actually pruned. Record `dirname "$link"` for each one, then walk up from there with `rmdir` (which only removes empty directories) until you reach `$d`. Do the same walk in dry-run and print the "would remove" lines. Whether to delete a skill folder that ends up empty is a separate choice: `mkdir -p` recreates it on the next run anyway.