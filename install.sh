#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "Installing el-capitan — personal agentic engineering orchestrator"
echo "  Source: $SCRIPT_DIR"

mkdir -p ~/.claude ~/.cursor/rules ~/.cursor/skills ~/.cursor/agents ~/.agent/tasks ~/.agent/journal ~/.agent/tools

for f in "$SCRIPT_DIR"/.cursor/rules/*.mdc; do
  ln -sf "$f" ~/.cursor/rules/$(basename "$f")
done

for f in "$SCRIPT_DIR"/.cursor/agents/*.md; do
  ln -sf "$f" ~/.cursor/agents/$(basename "$f")
done

for d in "$SCRIPT_DIR"/.cursor/skills/*/; do
  name=$(basename "$d")
  mkdir -p ~/.cursor/skills/$name
  ln -sf "$SCRIPT_DIR/.cursor/skills/$name/SKILL.md" ~/.cursor/skills/$name/SKILL.md
  # Symlink reference files if the skill has a references/ directory
  if [ -d "$SCRIPT_DIR/.cursor/skills/$name/references" ]; then
    mkdir -p ~/.cursor/skills/$name/references
    for ref in "$SCRIPT_DIR/.cursor/skills/$name/references/"*; do
      ln -sf "$ref" ~/.cursor/skills/$name/references/$(basename "$ref")
    done
  fi
done

ln -sf "$SCRIPT_DIR/.claude/CLAUDE.md" ~/.claude/CLAUDE.md

ln -sf "$SCRIPT_DIR/.agent/_SPEC_TEMPLATE.md" ~/.agent/_SPEC_TEMPLATE.md
ln -sf "$SCRIPT_DIR/.agent/_JOURNAL_TEMPLATE.md" ~/.agent/_JOURNAL_TEMPLATE.md
ln -sf "$SCRIPT_DIR/.agent/_PROFILE_TEMPLATE.md" ~/.agent/_PROFILE_TEMPLATE.md
ln -sf "$SCRIPT_DIR/.agent/tools/journal-search.py" ~/.agent/tools/journal-search.py
ln -sf "$SCRIPT_DIR/.agent/tools/manage-worktree.sh" ~/.agent/tools/manage-worktree.sh
ln -sf "$SCRIPT_DIR/.agent/tools/requirements.txt" ~/.agent/tools/requirements.txt

# Create PROFILE.md from template if it doesn't exist (preserves existing profile on reinstall)
if [ ! -f ~/.agent/PROFILE.md ]; then
  cp "$SCRIPT_DIR/.agent/_PROFILE_TEMPLATE.md" ~/.agent/PROFILE.md
  echo "  Created ~/.agent/PROFILE.md from template"
fi

echo ""
echo "Done. Installed:"
echo "  Rules:    $(ls ~/.cursor/rules/*.mdc 2>/dev/null | wc -l | tr -d ' ') (symlinked)"
echo "  Agents:   $(find ~/.cursor/agents -maxdepth 1 -name '*.md' -type l | wc -l | tr -d ' ') core (symlinked)"
echo "  Add-ons:  $(find ~/.cursor/agents -maxdepth 1 -name '*.md' ! -type l 2>/dev/null | wc -l | tr -d ' ') (local)"
echo "  Skills:   $(ls -d ~/.cursor/skills/*/ 2>/dev/null | wc -l | tr -d ' ') (symlinked)"
echo ""
# Add tools to PATH hint
if ! echo "$PATH" | grep -q "$HOME/.agent/tools"; then
  echo ""
  echo "  Optional: add ~/.agent/tools to your PATH for journal-search.py and manage-worktree.sh:"
  echo "    export PATH=\"\$HOME/.agent/tools:\$PATH\""
fi

# Check for semantic search dependencies (optional)
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
