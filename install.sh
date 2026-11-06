#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
FAILED=0

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

# Legacy: an old installer linked this directory at $SCRIPT_DIR/rules; a later one used
# $SCRIPT_DIR/.cursor/rules. Remove either, or `mkdir -p` traverses the link and the
# repo is linked into itself.
legacy_rules="$HOME/.cursor/rules"
if [ -L "$legacy_rules" ]; then
  case "$(readlink "$legacy_rules")" in
    "$SCRIPT_DIR/rules"|"$SCRIPT_DIR/.cursor/rules") run rm -f "$legacy_rules" ;;
  esac
fi
if [ -d "$legacy_rules" ] && [[ "$(cd "$legacy_rules" && pwd -P)" == "$SCRIPT_DIR"* ]]; then
  echo "  ERROR: ~/.cursor/rules resolves inside the source repo; remove it and re-run." >&2
  exit 1
fi

run mkdir -p ~/.claude ~/.cursor/rules ~/.cursor/skills ~/.cursor/agents ~/.agent/tasks ~/.agent/journal ~/.agent/bin

# ~/.claude/agents and ~/.claude/skills are directory symlinks to their ~/.cursor equivalents.
# Both Cursor and Claude Code consumers are satisfied from a single set of files in ~/.cursor/.
# Migrate: if they're real directories (old file-per-file layout), replace with a dir symlink.
for dir in agents skills; do
  target="$HOME/.claude/$dir"
  if [ -d "$target" ] && [ ! -L "$target" ]; then
    count=$(find "$target" -maxdepth 1 -name '*.md' 2>/dev/null | wc -l | tr -d ' ')
    # Never delete: hand-placed and third-party agents live here. Move aside so the
    # install can proceed and the files stay recoverable.
    backup="${target}.bak.$(date +%s)"
    while [ -e "$backup" ]; do backup="${backup}x"; done
    echo "  ~/.claude/$dir is a real directory ($count .md files) — moving to $backup and linking the managed dir."
    run mv "$target" "$backup"
    # Restore user files into the add-on location, or the migration silently disables
    # every third-party agent the user had. Names the managed set already owns are skipped.
    restored=0
    if [ "$DRY_RUN" -eq 0 ]; then
      mkdir -p "$HOME/.cursor/$dir"
      if [ "$dir" = agents ]; then
        # Agents are flat files.
        shopt -s nullglob
        for file in "$backup"/*.md; do
          name=$(basename "$file")
          [ -e "$SCRIPT_DIR/.cursor/$dir/$name" ] && continue
          [ -e "$HOME/.cursor/$dir/$name" ] && continue
          cp "$file" "$HOME/.cursor/$dir/$name" || FAILED=1
          restored=$((restored + 1))
        done
        shopt -u nullglob
      else
        # Skills are directories holding SKILL.md.
        shopt -s nullglob
        for skill in "$backup"/*/; do
          name=$(basename "$skill")
          [ -f "$skill/SKILL.md" ] || continue
          [ -e "$SCRIPT_DIR/.cursor/$dir/$name" ] && continue
          [ -e "$HOME/.cursor/$dir/$name" ] && continue
          cp -R "$skill" "$HOME/.cursor/$dir/$name" || FAILED=1
          restored=$((restored + 1))
        done
        shopt -u nullglob
      fi
      echo "  Restored $restored user item(s) into ~/.cursor/$dir; originals kept in $backup"
    fi
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

link_dir_files "$SCRIPT_DIR/rules" ~/.cursor/rules
prune_broken_symlinks ~/.cursor/rules
link_dir_files "$SCRIPT_DIR/.cursor/agents" ~/.cursor/agents
for agent_dir in crew-reviewer references; do
  if [ -d "$SCRIPT_DIR/.cursor/agents/$agent_dir" ]; then
    run ln -sfn "$SCRIPT_DIR/.cursor/agents/$agent_dir" ~/.cursor/agents/$agent_dir
  fi
done
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

if [ "$DRY_RUN" -eq 1 ]; then
  echo "  [dry-run] upsert memory adapters"
else
  mkdir -p "$HOME/.claude" "$HOME/.codex" "$HOME/.agent"
  python3 - "$HOME" <<'PY'
from pathlib import Path
import os
import sys
import tempfile

home = Path(sys.argv[1])
block = """<!-- el-capitan:memory -->
Claude Code and Cursor inject session memory at session start; other harnesses run `~/.agent/bin/mem.py context --mode session` at task start. Follow `~/.cursor/skills/crew-memory/references/contract.md`.
<!-- /el-capitan:memory -->"""


def write_atomically(target, text):
    # Preserve the existing file's mode (mkstemp creates 0600) and follow a symlink so a
    # dotfiles-managed CLAUDE.md keeps its link instead of being replaced by a file.
    target = target.resolve() if target.is_symlink() else target
    mode = target.stat().st_mode & 0o777 if target.exists() else 0o644
    descriptor, temporary = tempfile.mkstemp(prefix=".install-", dir=target.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(text)
        os.chmod(temporary, mode)
        os.replace(temporary, target)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


for target in (home / ".claude" / "CLAUDE.md", home / ".codex" / "AGENTS.md"):
    text = target.read_text() if target.exists() else ""
    start, end = text.find("<!-- el-capitan:memory -->"), text.find("<!-- /el-capitan:memory -->")
    if start >= 0 and end >= start:
        text = text[:start] + block + text[end + len("<!-- /el-capitan:memory -->"):]
    else:
        text = text.rstrip() + "\n\n" + block
    write_atomically(target, text.rstrip() + "\n")
PY
fi

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
      FAILED=1
    fi
  fi
fi
link_dir_files "$SCRIPT_DIR/.claude/hooks" ~/.claude/hooks
if [ "$DRY_RUN" -eq 0 ]; then
  mkdir -p "$HOME/.cursor"
  if ! python3 "$SCRIPT_DIR/.claude/merge_cursor_hooks.py" "$SCRIPT_DIR/.cursor/hooks.template.json" "$HOME/.cursor/hooks.json"; then
    echo "  ERROR: ~/.cursor/hooks.json merge failed — Cursor guards are not registered" >&2
    FAILED=1
  fi
fi

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

for f in _SPEC_TEMPLATE.md _BUG_SPEC_TEMPLATE.md _JOURNAL_TEMPLATE.md _MEMORY_TEMPLATE.md; do
  backup_if_regular ~/.agent/"$f"
  run ln -sf "$SCRIPT_DIR/.agent/$f" ~/.agent/"$f"
done
# ~/.agent/bin
run rm -f ~/.agent/bin/resolve-task-dir.sh ~/.agent/bin/log-progress.sh
link_dir_files "$SCRIPT_DIR/.agent/tools" ~/.agent/bin
link_dir_files "$SCRIPT_DIR/.agent/scripts" ~/.agent/bin
prune_broken_symlinks ~/.agent/bin
if [ "$DRY_RUN" -eq 0 ] && [ ! -d "$HOME/.agent/memory/.git" ]; then
  CREW_MEMORY_DIR="$HOME/.agent/memory" python3 "$SCRIPT_DIR/.agent/tools/mem.py" init
fi

echo ""
if [ "$FAILED" -eq 1 ]; then
  echo "Install INCOMPLETE — see errors above. Hooks or settings may not be registered."
else
  echo "Done. Installed:"
fi
echo "  Rules:    $(ls ~/.cursor/rules/*.mdc 2>/dev/null | wc -l | tr -d ' ') (symlinked → ~/.cursor/rules)"
echo "  Agents:   $(find ~/.cursor/agents -maxdepth 1 -name '*.md' -type l | wc -l | tr -d ' ') (symlinked → ~/.cursor/agents ← ~/.claude/agents)"
echo "  Skills:   $(ls -d ~/.cursor/skills/*/ 2>/dev/null | wc -l | tr -d ' ') (symlinked → ~/.cursor/skills ← ~/.claude/skills)"
echo ""
echo "  Journal:  ~/.agent/journal/ (monthly files, not tracked by git)"

echo ""
echo "Add-ons go directly in ~/.cursor/agents/ or ~/.cursor/skills/ as regular files."
echo "~/.agent/tasks/ is ready for per-repo/branch task state."

# Required dependencies: the guard hooks below fail closed, so a missing interpreter
# turns into a blocked shell rather than a warning.
missing=0
for dep in jq python3 git; do
  if ! command -v "$dep" >/dev/null 2>&1; then
    echo "  ERROR: $dep is required (hooks and tools use it)" >&2
    missing=1
  fi
done
[ "$missing" -eq 0 ] || exit 1
[ "$FAILED" -eq 0 ] || exit 1
