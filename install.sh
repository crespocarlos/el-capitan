#!/bin/bash
set -e

echo "Installing el-capitan — personal agentic engineering orchestrator"

# Create real directories (not symlinks — add-ons sit alongside core files)
mkdir -p ~/.claude ~/.cursor/rules ~/.cursor/skills ~/.cursor/agents ~/.agent/tasks

# Symlink rules (individual files)
for f in ~/el-capitan/.cursor/rules/*.mdc; do
  ln -sf "$f" ~/.cursor/rules/$(basename "$f")
done

# Symlink agents (individual files)
for f in ~/el-capitan/.cursor/agents/*.md; do
  ln -sf "$f" ~/.cursor/agents/$(basename "$f")
done

# Symlink skills (individual directories with SKILL.md)
for d in ~/el-capitan/.cursor/skills/*/; do
  name=$(basename "$d")
  mkdir -p ~/.cursor/skills/$name
  ln -sf ~/el-capitan/.cursor/skills/$name/SKILL.md ~/.cursor/skills/$name/SKILL.md
done

# Symlink CLAUDE.md
ln -sf ~/el-capitan/.claude/CLAUDE.md ~/.claude/CLAUDE.md

# Symlink agent template and journal
ln -sf ~/el-capitan/.agent/_SPEC_TEMPLATE.md ~/.agent/_SPEC_TEMPLATE.md
ln -sf ~/el-capitan/.agent/JOURNAL.md ~/.agent/JOURNAL.md

echo ""
echo "Done. Installed:"
echo "  Rules:    $(ls ~/.cursor/rules/*.mdc 2>/dev/null | wc -l | tr -d ' ') (symlinked)"
echo "  Agents:   $(find ~/.cursor/agents -maxdepth 1 -name '*.md' -type l | wc -l | tr -d ' ') core (symlinked)"
echo "  Add-ons:  $(find ~/.cursor/agents -maxdepth 1 -name '*.md' ! -type l 2>/dev/null | wc -l | tr -d ' ') (local)"
echo "  Skills:   $(ls -d ~/.cursor/skills/*/ 2>/dev/null | wc -l | tr -d ' ') (symlinked)"
echo ""
echo "Add-ons go directly in ~/.cursor/agents/ or ~/.cursor/skills/ as regular files."
echo "~/.agent/tasks/ is ready for per-repo/branch task state."
