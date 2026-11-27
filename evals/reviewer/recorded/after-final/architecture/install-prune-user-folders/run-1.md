Assessment: request-changes — the prune step also deletes empty folders that were never emptied by the prune, and the stated contract says the skill folder is partly the user's.
Read beyond the package: install.sh (grep only; `link_dir_files` and `DRY_RUN` are defined outside the visible file)

1. [blocking · 4] **`install.sh:27`** — `-empty -delete` removes the user's own empty folders, not just the ones pruning emptied
```
if [ "$pruned" -eq 1 ] && [ "$DRY_RUN" -eq 0 ]; then
  find "$d" -depth -type d -empty -delete
fi
```
The prune is meant to touch only dangling links into this checkout. This `find` deletes every empty directory under the skill folder, whatever its origin. Suppose a user keeps an empty `~/.cursor/skills/foo/notes/` or `drafts/` folder, and one stale link is pruned in `foo`. The install then deletes `notes/` and `drafts/`. If every link in the skill was pruned, it also deletes `foo/` itself. That breaks the stated promise that the folder may hold the user's own files and folders. Dry-run does not list these deletions, so the preview does not match what the real run does.
Fix: Record the parent directory of each pruned link. After `rm`, run `rmdir` on that parent and walk upward, stopping at `$d`. Use `rmdir` on `$d` itself only if it is empty. This removes only folders the prune emptied.

2. [attention · 3] **`install.sh:21`** — Dry-run lists the links to remove but not the folders that would go
```
echo "  [dry-run] remove broken symlink: $link -> $target"
```
The real run goes on to delete folders, and the dry-run never reports them. A user who previews the install sees no sign that directories will be removed. This also hides the problem in finding 1.
Fix: Emit a `[dry-run] remove empty dir` line for each folder that would become empty. Reuse the same upward-walk helper in both modes.

3. [nit · 2] **`install.sh:15`** — `[[ -L "${d%/}" ]] && continue` skips a symlinked skill folder, but a symlinked sub-folder inside a skill is not covered
Cost: `find "$d" -type l` lists symlinks inside a symlinked folder only if the loop reaches them, so the guard works only at the top level. This is low risk, because `find` does not follow links.