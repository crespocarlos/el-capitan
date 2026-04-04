#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# Symlink regular files from $1 into $2 (creates dest). nullglob; skips subdirs; no-op if $1 missing.
link_dir_files() {
  local src="$1" dest="$2"
  [[ -d "$src" ]] || return 0
  mkdir -p "$dest"
  shopt -s nullglob
  local f
  for f in "$src"/*; do
    [[ -f "$f" ]] || continue
    ln -sf "$f" "$dest/$(basename "$f")"
  done
  shopt -u nullglob
}

# Same as link_dir_files but mirrors each file into two dest dirs (e.g. ~/.cursor/... + ~/.claude/...).
link_dir_files_mirror() {
  local src="$1" dest_a="$2" dest_b="$3"
  [[ -d "$src" ]] || return 0
  mkdir -p "$dest_a" "$dest_b"
  shopt -s nullglob
  local f base
  for f in "$src"/*; do
    [[ -f "$f" ]] || continue
    base=$(basename "$f")
    ln -sf "$f" "$dest_a/$base"
    ln -sf "$f" "$dest_b/$base"
  done
  shopt -u nullglob
}

echo "Installing el-capitan — personal agentic engineering orchestrator"
echo "  Source: $SCRIPT_DIR"

mkdir -p ~/.claude ~/.cursor/rules ~/.cursor/skills ~/.cursor/agents ~/.claude/skills ~/.claude/agents ~/.agent/tasks ~/.agent/journal ~/.agent/tools

# Remove symlinks for deleted source files (idempotent)
rm -f ~/.cursor/skills/crew-eval-pr-comments/SKILL.md ~/.claude/skills/crew-eval-pr-comments/SKILL.md
rmdir ~/.cursor/skills/crew-eval-pr-comments ~/.claude/skills/crew-eval-pr-comments 2>/dev/null || true
rm -f ~/.cursor/skills/crew-automations/SKILL.md ~/.claude/skills/crew-automations/SKILL.md
rmdir ~/.cursor/skills/crew-automations ~/.claude/skills/crew-automations 2>/dev/null || true

link_dir_files "$SCRIPT_DIR/.cursor/rules" ~/.cursor/rules
link_dir_files_mirror "$SCRIPT_DIR/.cursor/agents" ~/.cursor/agents ~/.claude/agents

if [ -d "$SCRIPT_DIR/.cursor/skills" ]; then
  shopt -s nullglob
  for d in "$SCRIPT_DIR"/.cursor/skills/*/; do
    name=$(basename "$d")
    mkdir -p ~/.cursor/skills/$name ~/.claude/skills/$name
    ln -sf "$SCRIPT_DIR/.cursor/skills/$name/SKILL.md" ~/.cursor/skills/$name/SKILL.md
    ln -sf "$SCRIPT_DIR/.cursor/skills/$name/SKILL.md" ~/.claude/skills/$name/SKILL.md
    link_dir_files_mirror "$SCRIPT_DIR/.cursor/skills/$name/references" \
      ~/.cursor/skills/$name/references ~/.claude/skills/$name/references
  done
  shopt -u nullglob
fi

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
    python3 "$SCRIPT_DIR/.claude/merge_claude_settings.py" "$SETTINGS_SRC" "$SETTINGS_DEST"
  fi
fi
link_dir_files "$SCRIPT_DIR/.claude/hooks" ~/.claude/hooks

# ~/.agent templates (dotfile keeps stderr hush if optional upstream omits it)
for f in _SPEC_TEMPLATE.md _BUG_SPEC_TEMPLATE.md _JOURNAL_TEMPLATE.md _PROFILE_TEMPLATE.md; do
  ln -sf "$SCRIPT_DIR/.agent/$f" ~/.agent/"$f"
done
ln -sf "$SCRIPT_DIR/.agent/.ralph-instructions-template" ~/.agent/.ralph-instructions-template 2>/dev/null

# ~/.agent/{tools,scripts,queries}
link_dir_files "$SCRIPT_DIR/.agent/tools" ~/.agent/tools
link_dir_files "$SCRIPT_DIR/.agent/scripts" ~/.agent/scripts
link_dir_files "$SCRIPT_DIR/.agent/queries" ~/.agent/queries

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
