Assessment: request-changes — the empty-folder cleanup deletes every empty directory under a skill folder, including empty folders the user created, which breaks the stated promise that the user's own folders stay.

Read beyond the package: install.sh (grep only)

Approach: endorse — A single `find`-based prune of dangling links at any depth is the smallest design that meets the goal, and it beat a hard-coded `SKILL.md`/`references` special case. The defect below sits inside that approach.

Alternatives considered:
- Don't change anything (keep the SKILL.md-only prune) — loses because dangling reference links at depth stay behind forever.
- Track an install manifest and remove only what was recorded — more precise, but it adds state to migrate and keep in sync. That is not worth it while the prefix check on the link target already identifies the repo's own links.
- Rmdir only the parent directories of the links just removed, walking upward until one is non-empty — this keeps the single-pass shape and fixes finding 1.

1. [blocking · 4] **`install.sh:27`** — the empty-directory sweep deletes the user's own empty folders
```
if [ "$pruned" -eq 1 ] && [ "$DRY_RUN" -eq 0 ]; then
  find "$d" -depth -type d -empty -delete
fi
```
Suppose a user keeps an empty `~/.cursor/skills/foo/notes/` or `drafts/` folder as a placeholder. Install removes one stale link anywhere in that skill, and the sweep then deletes every empty directory under the skill. The user's folder is gone even though it had nothing to do with the pruned link. The header comment promises that the user's folders stay, and a dry run never shows the deletion.

Fix: rmdir only the ancestors of each pruned link, stopping at the first non-empty directory or at `$d`. For example, after `rm -f "$link"`, run `p=$(dirname "$link"); while [[ "$p" != "${d%/}" ]] && rmdir "$p" 2>/dev/null; do p=$(dirname "$p"); done`. Then handle the top-level skill folder with a final `rmdir "$d" 2>/dev/null || true`.

2. [attention · 3] **`install.sh:25`** — the dry run does not report the folders that would be removed
```
echo "  [dry-run] remove broken symlink: $link -> $target"
```
The real run also removes folders, but the dry run prints only the links. A user who previews the run cannot see which folders it will delete, which hides the problem in finding 1.

Fix: after the ancestor-walk fix, have the dry run print the folders that would become empty, or state that empty parent folders will be removed.