#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

DRY_RUN=0
for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=1 ;;
    *) echo "Unknown argument: $arg" >&2; exit 1 ;;
  esac
done

# Wrapper: print action in dry-run, execute otherwise.
run() {
  if [ "$DRY_RUN" -eq 1 ]; then
    echo "  [dry-run] $*"
  else
    "$@"
  fi
}

# Symlink regular files from $1 into $2 (creates dest). nullglob; skips subdirs; no-op if $1 missing.
link_dir_files() {
  local src="$1" dest="$2"
  [[ -d "$src" ]] || return 0
  run mkdir -p "$dest"
  shopt -s nullglob
  local f
  for f in "$src"/*; do
    [[ -f "$f" ]] || continue
    run ln -sf "$f" "$dest/$(basename "$f")"
  done
  shopt -u nullglob
}

if [ "$DRY_RUN" -eq 1 ]; then
  echo "Dry-run: el-capitan install (no changes will be made)"
else
  echo "Installing el-capitan — personal agentic engineering orchestrator"
fi
echo "  Source: $SCRIPT_DIR"

run mkdir -p ~/.claude ~/.cursor/rules ~/.cursor/skills ~/.cursor/agents ~/.agent/tasks ~/.agent/journal ~/.agent/bin

# ~/.claude/agents and ~/.claude/skills are directory symlinks to their ~/.cursor equivalents.
# Both Cursor and Claude Code consumers are satisfied from a single set of files in ~/.cursor/.
# Migrate: if they're real directories (old file-per-file layout), replace with a dir symlink.
for dir in agents skills; do
  target="$HOME/.claude/$dir"
  if [ -d "$target" ] && [ ! -L "$target" ]; then
    count=$(find "$target" -maxdepth 1 -name '*.md' 2>/dev/null | wc -l | tr -d ' ')
    echo "  WARNING: ~/.claude/$dir is a real directory ($count .md files) — replacing with dir symlink."
    echo "           Backup any local-only files before proceeding."
    run rm -rf "$target"
  fi
  run ln -sfn "$HOME/.cursor/$dir" "$target"
done

# Prune broken symlinks in a directory (symlinks whose target no longer exists).
# Only removes symlinks that point into SCRIPT_DIR, so hand-placed files are safe.
prune_broken_symlinks() {
  local dir="$1"
  [[ -d "$dir" ]] || return 0
  local link target
  shopt -s nullglob
  for link in "$dir"/*; do
    [[ -L "$link" ]] || continue
    target=$(readlink "$link")
    # Only manage symlinks that point into this repo
    [[ "$target" == "$SCRIPT_DIR"* ]] || continue
    if [ ! -e "$link" ]; then
      if [ "$DRY_RUN" -eq 1 ]; then
        echo "  [dry-run] remove broken symlink: $link → $target"
      else
        echo "  Removing stale symlink: $(basename "$link")"
        rm -f "$link"
      fi
    fi
  done
  shopt -u nullglob
}

link_dir_files "$SCRIPT_DIR/.cursor/rules" ~/.cursor/rules
link_dir_files "$SCRIPT_DIR/.cursor/agents" ~/.cursor/agents
prune_broken_symlinks ~/.cursor/agents

if [ -d "$SCRIPT_DIR/.cursor/skills" ]; then
  shopt -s nullglob
  for d in "$SCRIPT_DIR"/.cursor/skills/*/; do
    name=$(basename "$d")
    run mkdir -p ~/.cursor/skills/$name
    run ln -sf "$SCRIPT_DIR/.cursor/skills/$name/SKILL.md" ~/.cursor/skills/$name/SKILL.md
    link_dir_files "$SCRIPT_DIR/.cursor/skills/$name/references" ~/.cursor/skills/$name/references
  done
  shopt -u nullglob
  # Prune skill subdirs whose SKILL.md symlink is broken (skill was deleted from source)
  shopt -s nullglob
  for d in ~/.cursor/skills/*/; do
    skill_md="$d/SKILL.md"
    [[ -L "$skill_md" ]] || continue
    target=$(readlink "$skill_md")
    [[ "$target" == "$SCRIPT_DIR"* ]] || continue
    if [ ! -e "$skill_md" ]; then
      if [ "$DRY_RUN" -eq 1 ]; then
        echo "  [dry-run] remove stale skill dir: $d"
      else
        echo "  Removing stale skill: $(basename "$d")"
        rm -f "$skill_md"
        rmdir "$d" 2>/dev/null || true
      fi
    fi
  done
  shopt -u nullglob
fi

run ln -sf "$SCRIPT_DIR/.claude/CLAUDE.md" ~/.claude/CLAUDE.md

# Claude Code hooks (settings + hook scripts)
if [ -f "$SCRIPT_DIR/.claude/settings.json" ]; then
  # settings.json: merge el-capitan hooks into existing config rather than symlinking.
  # This is a managed copy — re-run install.sh to pick up upstream changes.
  SETTINGS_SRC="$SCRIPT_DIR/.claude/settings.json"
  SETTINGS_DEST="$HOME/.claude/settings.json"
  if [ "$DRY_RUN" -eq 1 ]; then
    echo "  [dry-run] merge settings.json → $SETTINGS_DEST"
  elif [ ! -f "$SETTINGS_DEST" ]; then
    cp "$SETTINGS_SRC" "$SETTINGS_DEST"
    echo "  Created ~/.claude/settings.json"
  else
    if ! python3 "$SCRIPT_DIR/.claude/merge_claude_settings.py" "$SETTINGS_SRC" "$SETTINGS_DEST"; then
      echo "  ERROR: settings.json merge failed — hooks may not be registered" >&2
      echo "  Run manually: python3 $SCRIPT_DIR/.claude/merge_claude_settings.py $SETTINGS_SRC $SETTINGS_DEST" >&2
    fi
  fi
fi
link_dir_files "$SCRIPT_DIR/.claude/hooks" ~/.claude/hooks

# ~/.agent templates (dotfile keeps stderr hush if optional upstream omits it)
# Before ln -sf overwrites: if the target is a pre-existing REGULAR file (not a symlink),
# back it up to a uniquely-suffixed .bak.<ts> so a second reinstall never destroys the
# first backup.
backup_if_regular() {
  local target="$1"
  if [ -e "$target" ] && [ ! -L "$target" ]; then
    if [ "$DRY_RUN" -eq 1 ]; then
      echo "  [dry-run] backup $(basename "$target") → $(basename "$target").bak.<ts>"
      return
    fi
    local ts backup
    ts=$(date +%s)
    backup="${target}.bak.${ts}"
    while [ -e "$backup" ]; do ts=$((ts+1)); backup="${target}.bak.${ts}"; done
    mv "$target" "$backup"
    echo "[install] backed up regular file $(basename "$target") → $(basename "$backup")"
  fi
}

for f in _SPEC_TEMPLATE.md _BUG_SPEC_TEMPLATE.md _JOURNAL_TEMPLATE.md; do
  backup_if_regular ~/.agent/"$f"
  run ln -sf "$SCRIPT_DIR/.agent/$f" ~/.agent/"$f"
done
backup_if_regular ~/.agent/.ralph-instructions-template
run ln -sf "$SCRIPT_DIR/.agent/.ralph-instructions-template" ~/.agent/.ralph-instructions-template 2>/dev/null || true

# ~/.agent/bin
run rm -f ~/.agent/bin/resolve-task-dir.sh ~/.agent/bin/log-progress.sh
link_dir_files "$SCRIPT_DIR/.agent/bin" ~/.agent/bin

echo ""
echo "Done. Installed:"
echo "  Rules:    $(ls ~/.cursor/rules/*.mdc 2>/dev/null | wc -l | tr -d ' ') (symlinked → ~/.cursor/rules)"
echo "  Agents:   $(find ~/.cursor/agents -maxdepth 1 -name '*.md' -type l | wc -l | tr -d ' ') (symlinked → ~/.cursor/agents ← ~/.claude/agents)"
echo "  Skills:   $(ls -d ~/.cursor/skills/*/ 2>/dev/null | wc -l | tr -d ' ') (symlinked → ~/.cursor/skills ← ~/.claude/skills)"
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
