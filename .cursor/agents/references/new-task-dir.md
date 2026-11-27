# New task directory

`crew-specwriter` Step 1 runs this block once per spec, with a fresh UUID every time.

```bash
# Slug from the issue title or description: lowercase, hyphens, ~50 chars ("Add retry" -> add-retry)
SLUG=<slug-from-title>

UUID=$(uuidgen 2>/dev/null || python3 -c "import uuid; print(uuid.uuid4())")
TASK_DIR=~/.agent/tasks/$UUID
mkdir -p "$TASK_DIR"

# .task-id records the remote and branch; crew-repo-info exits 1 when either is unavailable.
INFO=$(~/.agent/bin/crew-repo-info.py --remote origin --json) || exit 1
jq --arg uuid "$UUID" --arg slug "$SLUG" \
  '{uuid: $uuid, repo_remote_url: .remote_url, branch: .branch, slug: $slug,
    created_at: (now | todate)}' <<<"$INFO" > "$TASK_DIR/.task-id"

# Refuse to write into a directory that already holds another task's spec, before any file is touched.
if [ -f "$TASK_DIR/SPEC.md" ]; then
  echo "error: $TASK_DIR already holds a SPEC.md; generate a new UUID instead of reusing a task dir" >&2
  exit 1
fi

RECALLED_PATTERNS=$(~/.agent/bin/crew-mem.py context --mode plan --query "$SLUG" --warn-unavailable)
RECALLED_PATTERNS=${RECALLED_PATTERNS:-none}
```
