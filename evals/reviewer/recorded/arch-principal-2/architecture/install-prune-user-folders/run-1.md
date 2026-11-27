Assessment: request-changes — the pruning is the right mechanism, but the empty-folder cleanup deletes the user's own empty folders, which the change says it must not touch.

Read beyond the package: none (install.sh was the only file in the working directory)

Approach: redirect — keep the dangling-link pruning, but remove only the parent folders of the links it removed, not every empty folder under the skill.
Alternatives considered:
- Don't build it (keep the old SKILL.md-only prune) — loses: a deleted or moved reference file leaves a dangling link at depth, which is the stated need.
- Prune links, then `rmdir` only the parent folders of removed links, walking up to the skill root and stopping at the first non-empty folder — wins: it can only delete folders the install made.
- Make the installer record what it linked in a manifest and prune from that — more robust, but it adds state to migrate. It is not justified for a script this size.
- Chosen: a blanket `find -depth -type d -empty -delete` over the whole skill folder — loses, because it also removes folders it never created.

1. [attention · 5] **`install.sh:27`** — empty-folder cleanup deletes the user's own empty folders
```
if [ "$pruned" -eq 1 ] && [ "$DRY_RUN" -eq 0 ]; then
  find "$d" -depth -type d -empty -delete
fi
```
A user keeps an empty `~/.cursor/skills/foo/notes/` or `scratch/` folder inside a skill. A later install prunes one dangling link in the same skill, and this `find` deletes every empty folder under it, including the user's. If the skill's own folder ends up empty, it is deleted too. The header comment promises that the user's files stay. Dry-run also doesn't list these folder removals, so the user gets no warning.
Fix: collect `dirname "$link"` for each removed link. After pruning, walk each one upward with `rmdir` (which fails on a non-empty folder) until it reaches `"${d%/}"`, and don't remove `"${d%/}"` itself unless the skill is gone. In dry-run, print the folders that would be removed.

2. [nit · 3] **`install.sh:25`** — `find "$d" -type l` is run inside `nullglob` and without a depth or prune policy
```
done < <(find "$d" -type l)
```
It descends into real user folders of any size, and into the user's own non-symlinked trees. The `$SCRIPT_DIR/*` target filter keeps this safe, but each install walks everything the user keeps there.
Fix: leave as is, or bound it with `-maxdepth` if the skill layout is known to be shallow.