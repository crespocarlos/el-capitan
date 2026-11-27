Assessment: request-changes — the empty-folder cleanup is scoped to the whole skill directory, not to the folders pruning emptied, so it can delete user-owned folders the change promises to leave alone.

1. [blocking · 4] **`install.sh:27`** — `find -empty -delete` removes every empty folder under the skill dir, not just the ones pruning emptied
```
    if [ "$pruned" -eq 1 ] && [ "$DRY_RUN" -eq 0 ]; then
      find "$d" -depth -type d -empty -delete
    fi
```
The stated contract is to remove "the folders that pruning left empty". The user may keep their own folders in `~/.cursor/skills/<skill>/`. Once any link in that skill is pruned, this find deletes all empty directories beneath it. That includes a user's pre-existing empty folder, such as a placeholder they created for notes or a scratch area. The deletion is silent, because nothing is echoed and the dry-run output never mentions it. It is also unrecoverable. The `-L` guard and the target-prefix check show the script otherwise takes care to leave user content alone, so this is a boundary violation in the same function. The defect is new in this diff. The old code only ran `rmdir` on the skill dir itself.

Fix: record each pruned link's parent directory. After removal, run `rmdir` on that parent and walk upward, stopping at the first failure or at `"$d"`. This touches only directories that pruning emptied. For example, in the loop use `p=$(dirname "$link")` and `while [[ "$p" != "${d%/}" ]] && rmdir "$p" 2>/dev/null; do p=$(dirname "$p"); done`. After the loop, run `rmdir "$d" 2>/dev/null || true` if you still want to drop the emptied skill folder. Because `rmdir` fails on non-empty directories, user content stays safe. Add dry-run echoes for the directories that would be removed.