#!/bin/bash
# mode-anchor.sh — UserPromptSubmit hook
# Emits a compact pipeline anchor each turn to prevent context drift on long conversations.
# Output is injected as system context before the model responds.
set +e
exec 2>/dev/null

# Resolve active task for this repo+branch. A UserPromptSubmit hook must never block a
# turn, so resolution failures are swallowed by design (crew-lint: allow-swallow).
TASK_DIR=$(~/.agent/bin/resolve-task-dir.py 2>/dev/null) || exit 0   # crew-lint: allow-swallow
[ -z "$TASK_DIR" ] && exit 0
[ ! -f "$TASK_DIR/SPEC.md" ] && exit 0

TITLE=$(head -1 "$TASK_DIR/SPEC.md" | sed 's/^#* *//' | tr -d '"\]\n[:cntrl:]')
# Single reader for `## Status` (crew-ls owns the contract). An empty value means the
# spec has no status set — the anchor says so rather than silently emitting nothing.
STATUS=$(~/.agent/bin/crew-ls.py --status-file "$TASK_DIR/SPEC.md" 2>/dev/null | tr -d '[:space:]"\][:cntrl:]')   # crew-lint: allow-swallow
[ -n "$STATUS" ] || STATUS=unset
BRANCH=$(git -C "${CLAUDE_PROJECT_DIR:-.}" branch --show-current 2>/dev/null || echo "")
BRANCH=${BRANCH//\"/}
TASK_DIR_SAFE=${TASK_DIR//\"/}

echo "[CREW: task=\"$TITLE\" status=$STATUS branch=\"$BRANCH\" task_dir=\"$TASK_DIR_SAFE\"]"
exit 0
