#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "Installing el-capitan — personal agentic engineering orchestrator"
echo "  Source: $SCRIPT_DIR"

mkdir -p ~/.claude ~/.cursor/rules ~/.cursor/skills ~/.cursor/agents ~/.claude/skills ~/.claude/agents ~/.agent/tasks ~/.agent/journal ~/.agent/tools

# Remove symlinks for deleted source files (idempotent)
rm -f ~/.cursor/skills/crew-eval-pr-comments/SKILL.md ~/.claude/skills/crew-eval-pr-comments/SKILL.md
rmdir ~/.cursor/skills/crew-eval-pr-comments ~/.claude/skills/crew-eval-pr-comments 2>/dev/null || true
rm -f ~/.cursor/skills/crew-automations/SKILL.md ~/.claude/skills/crew-automations/SKILL.md
rmdir ~/.cursor/skills/crew-automations ~/.claude/skills/crew-automations 2>/dev/null || true

for f in "$SCRIPT_DIR"/.cursor/rules/*.mdc; do
  ln -sf "$f" ~/.cursor/rules/$(basename "$f")
done

for f in "$SCRIPT_DIR"/.cursor/agents/*.md; do
  ln -sf "$f" ~/.cursor/agents/$(basename "$f")
  ln -sf "$f" ~/.claude/agents/$(basename "$f")
done

for d in "$SCRIPT_DIR"/.cursor/skills/*/; do
  name=$(basename "$d")
  mkdir -p ~/.cursor/skills/$name ~/.claude/skills/$name
  ln -sf "$SCRIPT_DIR/.cursor/skills/$name/SKILL.md" ~/.cursor/skills/$name/SKILL.md
  ln -sf "$SCRIPT_DIR/.cursor/skills/$name/SKILL.md" ~/.claude/skills/$name/SKILL.md
  # Symlink reference files if the skill has a references/ directory
  if [ -d "$SCRIPT_DIR/.cursor/skills/$name/references" ]; then
    mkdir -p ~/.cursor/skills/$name/references ~/.claude/skills/$name/references
    for ref in "$SCRIPT_DIR/.cursor/skills/$name/references/"*; do
      ln -sf "$ref" ~/.cursor/skills/$name/references/$(basename "$ref")
      ln -sf "$ref" ~/.claude/skills/$name/references/$(basename "$ref")
    done
  fi
done

# NOTE: When adding new crew commands, update BOTH .cursor/rules/crew-router.mdc
# AND .claude/CLAUDE.md — they must stay in sync.
ln -sf "$SCRIPT_DIR/.claude/CLAUDE.md" ~/.claude/CLAUDE.md

# Claude Code hooks (settings + hook scripts)
if [ -f "$SCRIPT_DIR/.claude/settings.json" ]; then
  # settings.json: merge el-capitan hooks into existing config rather than symlinking.
  # This is a managed copy — re-run install.sh to pick up upstream changes.
  SETTINGS_SRC="$SCRIPT_DIR/.claude/settings.json"
  SETTINGS_DEST="$HOME/.claude/settings.json"
  if [ ! -f "$SETTINGS_DEST" ]; then
    cp "$SETTINGS_SRC" "$SETTINGS_DEST"
    echo "  Created ~/.claude/settings.json"
  else
    python3 - "$SETTINGS_SRC" "$SETTINGS_DEST" <<'PYEOF'
import sys, json, os
src_path, dest_path = sys.argv[1], sys.argv[2]
with open(src_path) as f: src = json.load(f)
with open(dest_path) as f: dest = json.load(f)
# hooks is a dict keyed by event type (PreToolUse, PostToolUse, etc.)
# Each value is an array of {matcher, hooks} entries. Merge per event type,
# deduping by matcher so re-running install.sh is idempotent.
src_hooks = src.get("hooks", {})
dest_hooks = dest.get("hooks", {})
for event_type, entries in src_hooks.items():
  if event_type not in dest_hooks:
    dest_hooks[event_type] = entries
  else:
    existing_matchers = {e.get("matcher", "") for e in dest_hooks[event_type]}
    for entry in entries:
      if entry.get("matcher", "") not in existing_matchers:
        dest_hooks[event_type].append(entry)
dest["hooks"] = dest_hooks
for k, v in src.items():
  if k != "hooks" and k not in dest:
    dest[k] = v
tmp = dest_path + ".tmp"
with open(tmp, "w") as f: json.dump(dest, f, indent=2)
os.rename(tmp, dest_path)
print("  Merged ~/.claude/settings.json")
PYEOF
  fi
fi
if [ -d "$SCRIPT_DIR/.claude/hooks" ]; then
  mkdir -p ~/.claude/hooks
  for h in "$SCRIPT_DIR/.claude/hooks/"*; do
    ln -sf "$h" ~/.claude/hooks/$(basename "$h")
  done
fi

ln -sf "$SCRIPT_DIR/.agent/_SPEC_TEMPLATE.md" ~/.agent/_SPEC_TEMPLATE.md
ln -sf "$SCRIPT_DIR/.agent/_JOURNAL_TEMPLATE.md" ~/.agent/_JOURNAL_TEMPLATE.md
ln -sf "$SCRIPT_DIR/.agent/_PROFILE_TEMPLATE.md" ~/.agent/_PROFILE_TEMPLATE.md
ln -sf "$SCRIPT_DIR/.agent/tools/journal-search.py" ~/.agent/tools/journal-search.py
ln -sf "$SCRIPT_DIR/.agent/tools/manage-worktree.sh" ~/.agent/tools/manage-worktree.sh
ln -sf "$SCRIPT_DIR/.agent/tools/log-progress.sh" ~/.agent/tools/log-progress.sh
ln -sf "$SCRIPT_DIR/.agent/tools/resolve-task-dir.sh" ~/.agent/tools/resolve-task-dir.sh
ln -sf "$SCRIPT_DIR/.agent/tools/requirements.txt" ~/.agent/tools/requirements.txt

# Create PROFILE.md from template if it doesn't exist (preserves existing profile on reinstall)
if [ ! -f ~/.agent/PROFILE.md ]; then
  cp "$SCRIPT_DIR/.agent/_PROFILE_TEMPLATE.md" ~/.agent/PROFILE.md
  echo "  Created ~/.agent/PROFILE.md from template"
fi

echo ""
echo "Done. Installed:"
echo "  Rules:    $(ls ~/.cursor/rules/*.mdc 2>/dev/null | wc -l | tr -d ' ') (symlinked → ~/.cursor/rules)"
echo "  Agents:   $(find ~/.cursor/agents -maxdepth 1 -name '*.md' -type l | wc -l | tr -d ' ') (symlinked → ~/.cursor/agents + ~/.claude/agents)"
echo "  Add-ons:  $(find ~/.cursor/agents -maxdepth 1 -name '*.md' ! -type l 2>/dev/null | wc -l | tr -d ' ') (local)"
echo "  Skills:   $(ls -d ~/.cursor/skills/*/ 2>/dev/null | wc -l | tr -d ' ') (symlinked → ~/.cursor/skills + ~/.claude/skills)"
echo ""
# Check optional dependencies
if command -v ollama &>/dev/null && python3 -c "import chromadb" 2>/dev/null; then
  echo "  Semantic search: ready (ollama + chromadb found)"
else
  echo "  Semantic search: optional — install ollama + 'pip install chromadb' for journal-search.py"
fi

echo ""
echo "  Journal:  ~/.agent/journal/ (monthly files, not tracked by git)"
echo "  Profile:  ~/.agent/PROFILE.md (edit to personalize agent context)"
echo ""
echo "Add-ons go directly in ~/.cursor/agents/ or ~/.cursor/skills/ as regular files."
echo "~/.agent/tasks/ is ready for per-repo/branch task state."
