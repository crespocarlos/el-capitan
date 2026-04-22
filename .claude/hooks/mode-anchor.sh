#!/bin/bash
# mode-anchor.sh — UserPromptSubmit hook
# Emits a compact pipeline anchor each turn to prevent context drift on long conversations.
# Output is injected as system context before the model responds.
set +e
exec 2>/dev/null

# Resolve active task for this repo+branch
TASK_DIR=$(~/.agent/bin/resolve-task-dir.py 2>/dev/null) || exit 0
[ -z "$TASK_DIR" ] && exit 0
[ ! -f "$TASK_DIR/SPEC.md" ] && exit 0

TITLE=$(head -1 "$TASK_DIR/SPEC.md" | sed 's/^#* *//' | tr -d '"\]\n[:cntrl:]')
STATUS=$(awk '/^## Status/{found=1; next} found && NF{print; exit}' "$TASK_DIR/SPEC.md" | tr -d '[:space:]"\][:cntrl:]')
BRANCH=$(git -C "${CLAUDE_PROJECT_DIR:-.}" branch --show-current 2>/dev/null || echo "")
BRANCH=${BRANCH//\"/}
TASK_DIR_SAFE=${TASK_DIR//\"/}

echo "[CREW: task=\"$TITLE\" status=$STATUS branch=\"$BRANCH\" task_dir=\"$TASK_DIR_SAFE\"]"
exit 0
