---
name: crew-migrate
description: "Migrate task state from old ~/.agent/tasks/<repo>/<branch>/<slug>/ layout to UUID layout. Trigger: 'crew migrate'."
---

## `crew migrate`

Migrates task state from the old `~/.agent/tasks/<repo>/<branch>/<slug>/` layout to the new `~/.agent/tasks/<uuid>/` layout. Run inline — no skill file.

### Step 1: Scan for old-layout directories

```bash
OLD_LAYOUT_DIRS=()
for dir in ~/.agent/tasks/*/; do
  [ -d "$dir" ] || continue
  [ -f "${dir}.task-id" ] && continue  # skip UUID dirs
  # Check if any subdirectory contains SPEC.md (old-layout heuristic)
  if find "$dir" -mindepth 2 -maxdepth 2 -name "SPEC.md" 2>/dev/null | grep -q .; then
    OLD_LAYOUT_DIRS+=("$dir")
  fi
done
```

If `${#OLD_LAYOUT_DIRS[@]}` is 0: print "Nothing to migrate." and stop.

### Step 2: Build migration table

For each old-layout dir, find all `SPEC.md` files under `<repo>/<branch>/<slug>/`. For each one, extract:
- `OLD_PATH` — the full `~/.agent/tasks/<repo>/<branch>/<slug>/` path
- `REPO_REMOTE` — run `git -C <slug-dir>/../.. remote get-url origin 2>/dev/null` (best effort; may be empty)
- `BRANCH` — the second path segment after `~/.agent/tasks/`
- `SLUG` — the third path segment
- `PROPOSED_UUID` — generate via `uuidgen 2>/dev/null || python3 -c "import uuid; print(uuid.uuid4())"`

**Idempotency guard:** Before generating `PROPOSED_UUID`, check if a UUID dir already exists with matching `repo_remote_url` + `branch`:

```bash
for task_id_file in ~/.agent/tasks/*/.task-id; do
  [ -f "$task_id_file" ] || continue
  file_remote=$(python3 -c "import json; d=json.load(open('$task_id_file')); print(d.get('repo_remote_url',''))" 2>/dev/null || echo "")
  file_branch=$(python3 -c "import json; d=json.load(open('$task_id_file')); print(d.get('branch',''))" 2>/dev/null || echo "")
  if [ "$file_remote" = "$REPO_REMOTE" ] && [ "$file_branch" = "$BRANCH" ]; then
    echo "Already migrated: $OLD_PATH → $(dirname $task_id_file) (skipping)"
    continue 2  # skip this entry
  fi
done
```

Present the migration table:

```
Migration plan:
  Old path                                          → Proposed UUID dir
  ~/.agent/tasks/myrepo/main/add-feature/           → ~/.agent/tasks/550e8400-e29b-41d4-a716-446655440000/
  ~/.agent/tasks/myrepo/chore/fix-bug/              → ~/.agent/tasks/6ba7b810-9dad-11d1-80b4-00c04fd430c8/
  (already migrated: ~/.agent/tasks/myrepo/feature/xyz/ → skipped)
```

### Step 3: Confirm before mutation

Ask: "Migrate N task(s)? (yes/no)"

If no → stop. Do not modify anything.

### Step 4: Execute migration

For each confirmed entry:

```bash
UUID=$(uuidgen 2>/dev/null || python3 -c "import uuid; print(uuid.uuid4())")
NEW_DIR=~/.agent/tasks/$UUID
mkdir -p "$NEW_DIR"

# Write .task-id JSON
python3 -c "
import json, sys
data = {
  'uuid': '$UUID',
  'repo_remote_url': '$REPO_REMOTE',
  'branch': '$BRANCH',
  'slug': '$SLUG',
  'created_at': '$(date -u +"%Y-%m-%dT%H:%M:%SZ")'
}
json.dump(data, sys.stdout, indent=2)
" > "$NEW_DIR/.task-id"

# Copy all content from old dir
cp -r "$OLD_PATH"/* "$NEW_DIR/" 2>/dev/null || true

# Remove old dir
rm -rf "$OLD_PATH"
echo "Migrated: $OLD_PATH → $NEW_DIR"
```

### Step 5: Report

Print: "Migrated N tasks."

If N = 0 (all were already migrated or skipped): "Nothing to migrate."
