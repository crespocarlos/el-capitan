Assessment: request-changes — the empty-folder sweep is wider than the stated intent and deletes user-owned empty folders, which the change says must be preserved.
Read beyond the package: install.sh (grep only; it holds just the changed region, so no other consumers were found)

Approach: redirect — pruning dangling links is sound, but the folder cleanup should remove only the parent directories of the links it deleted, not every empty directory.
Alternatives considered:
- Don't prune at all, or tell the user to clean up by hand — loses. The dangling links accumulate in a folder the installer owns, and the link-only prune is cheap and safe.
- Record the installed links in a manifest and remove exactly those on reinstall — better in principle, because it never guesses ownership. It costs a new on-disk format and a migration for existing installs, which is too much for this change. The current check, "symlink into this checkout whose target is gone", already gives the same ownership test without state.
- Prune each link, then `rmdir` only that link's parent chain up to the skill dir — wins. It matches the claim "folders that pruning left empty" and never touches folders the user made.

1. [attention · 4] **`install.sh:27`** — the empty-dir sweep deletes the user's own empty folders
```
if [ "$pruned" -eq 1 ] && [ "$DRY_RUN" -eq 0 ]; then
  find "$d" -depth -type d -empty -delete
fi
```
A user keeps an empty `~/.cursor/skills/foo/notes/` placeholder next to the installed links. A reference is later removed from the repo. The next install prunes that one link, and the `find` then deletes every empty directory under the skill, including `notes/`. The comment says the user's folders stay, but the sweep is not limited to folders the pruning emptied. The sweep also runs without printing anything, and the dry-run prints nothing about it.
Fix: collect `dirname "$link"` for each pruned link. After the loop, walk up from each of those directories with `rmdir` (which only succeeds on an empty directory), stopping at `${d%/}`. Also remove `${d%/}` itself if it is empty. Print a `[dry-run] remove empty dir` line in dry-run mode.

2. [nit · 3] **`install.sh:17`** — dry-run reports the symlinks but not the folders that would go
```
echo "  [dry-run] remove broken symlink: $link -> $target"
```
In a dry run, the user sees the links listed but not the directories the real run would remove. The preview understates what the real run does, and that gap is the one that matters for finding 1.
Fix: have the dry-run path list the directories that would become empty, using the same parent-chain walk as in finding 1.