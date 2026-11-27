Assessment: request-changes — the empty-folder cleanup is not limited to folders that pruning emptied, so it can delete user-created empty folders inside a skill directory.

Read beyond the package: none. `install.sh` is the only file, and I read it in full. `run` and `link_dir_files` are defined elsewhere, outside the case files.

Approach: redirect — Keep the prune-at-any-depth design, but remove only the directories that pruning emptied instead of sweeping the whole skill tree.
Alternatives considered:
- Don't build it (keep the SKILL.md-only prune) — loses, because a deleted or moved reference file leaves a dangling link forever.
- Track what the installer created, for example a manifest per skill, and remove exactly those entries — more precise and the safest for user data. It costs a new on-disk format and a migration for existing installs, which is too heavy while symlink-target matching works.
- Remove the stale link, then `rmdir` its parent chain up to the skill root (the redirect) — this touches only directories the pruning emptied, and it is a small change from the current code.
- Wipe and relink each skill folder — loses, because it destroys the user's own files.

1. [attention · 4] **`install.sh:27`** — The empty-directory sweep deletes user folders that pruning did not empty
```
if [ "$pruned" -eq 1 ] && [ "$DRY_RUN" -eq 0 ]; then
  find "$d" -depth -type d -empty -delete
fi
```
Suppose a user keeps an empty `~/.cursor/skills/foo/notes/` or `scratch/` folder, and one stale link is pruned from `foo`. The `find` then deletes every empty directory under `foo`, including `notes/`, even though pruning never touched it. The header comment promises only that "the folders that left empty" are removed. The dry-run branch also never says which directories would be removed, so a preview can't warn the user.
Fix: after `rm -f "$link"`, walk up from `$(dirname "$link")` and `rmdir` each parent (it fails harmlessly if the directory is non-empty), stopping at `$d` or at the first failure. Print the directory in the dry-run branch too.

2. [nit · 3] **`install.sh:17`** — The target prefix check depends on how `SCRIPT_DIR` is spelled
```
[[ "$target" == "$SCRIPT_DIR"/* && ! -e "$link" ]] || continue
```
The comparison is against the literal string. If `SCRIPT_DIR` is a symlinked or non-canonical path that differs from the one used when the links were created, or it ends in `/`, a stale link is never matched and stays behind. The old code had the same weakness, and it fails safe, so the cost is stale links accumulating.
Fix: canonicalise `SCRIPT_DIR` once with `cd … && pwd -P`, or strip any trailing `/` before comparing.