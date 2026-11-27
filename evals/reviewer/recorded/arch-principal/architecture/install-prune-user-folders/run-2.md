Assessment: request-changes — the approach (prune only symlinks into this checkout) is right, but the cleanup step deletes every empty folder under the skill dir, including the user's own.
Read beyond the package: install.sh (grep only)

Approach: redirect — keep the symlink-only prune, but remove only the parent directories of the links it actually removed, instead of sweeping the whole tree.
Alternatives considered:
- Don't build it (leave dangling links, or have the user run a manual cleanup) — loses: dangling links in Cursor's skill folder are a real defect, and the existing code already prunes at the skill level.
- Record a manifest of installed links and remove exactly those links on re-install — stronger ownership model, but it adds state on disk. The `readlink` prefix check already gives the same ownership test, so it's more than this change needs.
- Prune and then `rmdir` only the parent directories of removed links, walking up and stopping at the skill dir — wins: it touches only folders the install could have emptied.

1. [blocking · 5] **`install.sh:27`** — `find -empty -delete` removes the user's own empty folders
```
if [ "$pruned" -eq 1 ] && [ "$DRY_RUN" -eq 0 ]; then
  find "$d" -depth -type d -empty -delete
fi
```
The change statement says the user keeps their own files and folders in this directory. If a skill folder holds a user-made empty folder (for example `~/.cursor/skills/foo/notes/`) and any one link in it gets pruned, that folder is deleted too. It was never empty because of pruning. The sweep also covers the whole skill tree, not just the paths the pruning touched. Folders that are not install's can't be recovered.
Fix: collect `dirname "$link"` for each removed link and, after the loop, run `rmdir` on each one, then on its parents up to but not including `$d`. Then `rmdir "$d"` only if it is empty and no user content remains.

2. [attention · 4] **`install.sh:21`** — the dry-run output does not show the folder removals
```
echo "  [dry-run] remove broken symlink: $link -> $target"
...
if [ "$pruned" -eq 1 ] && [ "$DRY_RUN" -eq 0 ]; then
```
A dry run prints the links it would remove but says nothing about the folders. The user cannot see the destructive part, which is the part that causes finding 1. Real runs also remove folders silently. Fix: print each folder as it is removed, and print the same line in dry-run mode.

3. [nit · 3] **`install.sh:15`** — the symlinked-skill-dir guard has no comment
Skipping `~/.cursor/skills/<x>` when it is itself a symlink is a good protection, but it is easy to drop in a later cleanup. Fix: add a one-line comment saying a symlinked skill folder is the user's.