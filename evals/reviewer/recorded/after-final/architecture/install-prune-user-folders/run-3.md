Assessment: request-changes — the pruning is correctly scoped to links into this checkout, but the empty-folder cleanup is not. It deletes the user's own empty folders, which the change says it must leave alone.

Read beyond the package: none (`install.sh` was the only changed file, and it holds the whole hunk).

1. [blocking · 5] **`install.sh:27`** — empty-dir cleanup deletes user-owned empty folders, not just ones pruning emptied
```
if [ "$pruned" -eq 1 ] && [ "$DRY_RUN" -eq 0 ]; then
  find "$d" -depth -type d -empty -delete
fi
```
A user keeps an empty `~/.cursor/skills/foo/notes/` folder, or a scratch skill folder they just created. Any run that prunes at least one dangling link in that same skill folder deletes the empty folder as well. The cleanup also removes the skill folder itself if it ends up empty. Pruning removed nothing from `notes/`, so its removal breaks the stated contract that the user's own files and folders stay. The `pruned` flag is per skill folder, so it doesn't narrow the deletion to the folders pruning emptied. `-delete` also has no dry-run output, so the user can't see this beforehand.
Fix: remove only the ancestors of each link you removed, and stop at the skill folder. After `rm -f "$link"`, run `p=$(dirname "$link"); while [[ "$p" != "${d%/}" ]] && rmdir "$p" 2>/dev/null; do p=$(dirname "$p"); done`. `rmdir` fails on any non-empty folder, so a folder that was already empty and unrelated to the pruned link is never touched. Then try `rmdir "$d"` for the skill folder, as the old code did. This path was only reached when SKILL.md was dangling.

2. [attention · 3] **`install.sh:25`** — dry-run reports incompletely and the empty-folder cleanup never previews
```
done < <(find "$d" -type l)
...
[ "$DRY_RUN" -eq 0 ]; then
```
In dry-run, links are listed but the folders that would be removed are not. The old code printed `[dry-run] remove stale skill dir`. A user previewing an install therefore can't see that folder deletion is coming, and that deletion is the riskiest step.
Fix: once the cleanup in finding 1 is per-link, print `[dry-run] remove empty dir: …` for each ancestor that would become empty. Alternatively, drop the folder removal and leave empty folders in place.