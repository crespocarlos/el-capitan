#!/bin/bash
set -e

echo "Installing el-capitan — personal agentic engineering orchestrator"

mkdir -p ~/.claude ~/.cursor/rules ~/.cursor/skills ~/.cursor/agents ~/.agent/tasks

# Symlink rules, skills, agents (directories)
for dir in rules skills agents; do
  if [ -L ~/.cursor/$dir ]; then
    rm ~/.cursor/$dir
  elif [ -d ~/.cursor/$dir ]; then
    echo "Warning: ~/.cursor/$dir exists and is not a symlink. Back it up manually, then re-run."
    exit 1
  fi
  ln -sf ~/el-capitan/.cursor/$dir ~/.cursor/$dir
done

# Symlink CLAUDE.md
ln -sf ~/el-capitan/.claude/CLAUDE.md ~/.claude/CLAUDE.md

# Symlink agent template and journal (individual files, not the tasks dir)
ln -sf ~/el-capitan/.agent/_SPEC_TEMPLATE.md ~/.agent/_SPEC_TEMPLATE.md
ln -sf ~/el-capitan/.agent/JOURNAL.md ~/.agent/JOURNAL.md

echo ""
echo "Done. Next steps:"
echo "  1. Install Claude Code: curl -fsSL https://claude.ai/install.sh | bash"
echo "  2. ~/.agent/tasks/ is ready for per-repo/branch task state"
echo ""
echo "el-capitan installed."
