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

# Symlink regular files from $1 into $2 (creates dest). $3 is the walk depth, for the flat
# directories (rules, agents, hooks, skill references). A duplicate basename aborts before any link
# is written: otherwise the second `ln -sf` silently replaces the first and a cataloged command
# resolves to the wrong file. Cleanup of retired links is the caller's job via
# `prune_broken_symlinks`, which only removes links this installer created: doing it here would need
# that helper defined first, and any sweep that did not check the link target would delete a user's
# own dangling link in the same directory.
link_dir_files() {
  local src="$1" dest="$2" depth="${3:-1}"
  [[ -d "$src" ]] || return 0
  local listing duplicates f name first second
  listing=$(find "$src" -maxdepth "$depth" -type f ! -path '*/__pycache__/*' | sort)
  [[ -n "$listing" ]] || return 0
  duplicates=$(printf '%s\n' "$listing" | awk -F/ '
    { name = $NF; if (name in seen) print name "\t" seen[name] "\t" $0; else seen[name] = $0 }')
  if [[ -n "$duplicates" ]]; then
    while IFS=$'\t' read -r name first second; do
      echo "error: duplicate command $name in $first and $second" >&2
    done <<< "$duplicates"
    return 1
  fi
  run mkdir -p "$dest"
  while IFS= read -r f; do
    run ln -sf "$f" "$dest/$(basename "$f")"
  done <<< "$listing"
}

# A duplicate basename anywhere in the tool tree aborts before a link is written, for the same
# reason: the installed surface is flat. Scanned from the tree rather than the catalog so the check
# still fires when a copy of this installer runs against a tree whose catalog is absent or stale.
duplicate_tool_basenames() {
  local listing duplicates name first second
  listing=$(find "$SCRIPT_DIR/.agent/tools" -type f \( -name '*.py' -o -name '*.sh' \) \
    ! -path '*/__pycache__/*' | sort)
  [[ -n "$listing" ]] || return 0
  duplicates=$(printf '%s\n' "$listing" | awk -F/ '
    { name = $NF; if (name in seen) print name "\t" seen[name] "\t" $0; else seen[name] = $0 }')
  [[ -z "$duplicates" ]] && return 0
  while IFS=$'\t' read -r name first second; do
    echo "error: duplicate command $name in $first and $second" >&2
  done <<< "$duplicates"
  return 1
}

# The catalog's `kind: command` entries as `dir<TAB>name` lines: the whole of what ~/.agent/bin
# receives. Read from the manifest through Python so the JSON is parsed once, by one parser.
catalog_commands() {
  python3 - "$SCRIPT_DIR/.agent/tools/tools.json" <<'PY'
import json
import sys

with open(sys.argv[1]) as handle:
    data = json.load(handle)
for section in ("tools", "scripts"):
    for entry in data.get(section, []):
        if entry.get("kind") == "command":
            print(f"{entry['dir']}\t{entry['name']}")
PY
}

# Link only what the catalog declares as a command. A module is imported and an asset is read, so
# neither belongs on the command surface. The old directory walk linked every file at depth two,
# which shipped `cli.py`, `files.py`, `git.py`, and the `memory_*`/`review_*` modules to
# ~/.agent/bin as commands that cannot run.
link_catalog_commands() {
  local dest="$1" listing directory name
  if [[ ! -f "$SCRIPT_DIR/.agent/tools/tools.json" ]]; then
    echo "error: missing tool catalog $SCRIPT_DIR/.agent/tools/tools.json" >&2
    return 1
  fi
  listing=$(catalog_commands) || return 1
  if [[ -z "$listing" ]]; then
    echo "error: the tool catalog declares no commands" >&2
    return 1
  fi
  run mkdir -p "$dest"
  while IFS=$'\t' read -r directory name; do
    run ln -sf "$SCRIPT_DIR/.agent/tools/$directory/$name" "$dest/$name"
  done <<< "$listing"
}

# Remove links this installer created into the tool tree whose basename is no longer a cataloged
# command. Those links are not broken — their targets still exist — so `prune_broken_symlinks`
# leaves them behind, and the modules and catalog files the old walk linked would stay on the
# command surface forever. Only links whose target is inside this repo's tool tree are touched, so a
# user's own file in the same directory is safe.
prune_retired_tool_links() {
  local dir="$1" commands link target name
  [[ -d "$dir" ]] || return 0
  [[ -f "$SCRIPT_DIR/.agent/tools/tools.json" ]] || return 0
  commands=$(catalog_commands | cut -f2) || return 1
  shopt -s nullglob
  for link in "$dir"/*; do
    [[ -L "$link" ]] || continue
    target=$(readlink "$link")
    [[ "$target" == "$SCRIPT_DIR/.agent/tools/"* ]] || continue
    name=$(basename "$link")
    if grep -qxF "$name" <<< "$commands"; then
      continue
    fi
    if [ "$DRY_RUN" -eq 1 ]; then
      echo "  [dry-run] remove retired tool link: $link → $target"
    else
      echo "  Removing retired link: $name"
      rm -f "$link"
    fi
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
  echo "  [dry-run] upsert memory adapters and global rule imports"
else
  mkdir -p "$HOME/.claude" "$HOME/.codex" "$HOME/.agent"
  python3 - "$HOME" "$SCRIPT_DIR" <<'PY'
from pathlib import Path
import os
import re
import sys
import tempfile

home = Path(sys.argv[1])
source = Path(sys.argv[2])
block = """<!-- el-capitan:memory -->
Claude Code and Cursor inject session memory at session start; other harnesses run `~/.agent/bin/crew-mem.py context --mode session` at task start. Follow `~/.cursor/skills/crew-memory/references/contract.md`.
<!-- /el-capitan:memory -->"""


def global_rule_imports() -> str:
    """The `@` imports this repo needs in the global CLAUDE.md, in a managed fenced block.

    `.claude/CLAUDE.md` is project-scoped, so in any other checkout — every Kibana worktree —
    Claude Code loads only `~/.claude/CLAUDE.md`. A rule marked `alwaysApply: true` is therefore
    invisible there unless the global file imports it, and nothing was propagating those imports:
    the global file had a one-time copy of the body, so it drifted the moment the project file
    changed (it still showed a pipeline diagram two revisions stale). Managing a fenced block
    derived from the project file keeps one source of truth and leaves the user's own prose alone.
    """
    project = source / ".claude" / "CLAUDE.md"
    if not project.is_file():
        return ""
    targets = []
    for target in re.findall(r"@(\S+\.mdc)", project.read_text(errors="replace")):
        if target not in targets:
            targets.append(target)
    if not targets:
        return ""
    lines = ["<!-- el-capitan:imports -->",
             "<!-- Generated by install.sh from .claude/CLAUDE.md; edits here are overwritten. -->"]
    lines += [f"@{target}" for target in targets]
    lines.append("<!-- /el-capitan:imports -->")
    return "\n".join(lines)


def upsert(text: str, name: str, body: str) -> str:
    """Replace the fenced block in place, or append it; idempotent on every run.

    `body` carries no trailing newline, so both paths normalize to exactly one newline after the
    closing marker and collapse any run of blank lines that follows it. Preserving a blank
    separator is not worth the extra path: the two branches then disagree and repeated installs
    grow or eat blank lines.
    """
    start_marker, end_marker = f"<!-- el-capitan:{name} -->", f"<!-- /el-capitan:{name} -->"
    start, end = text.find(start_marker), text.find(end_marker)
    if start >= 0 and end >= start:
        rest = text[end + len(end_marker):].lstrip("\n")
        return text[:start] + body + ("\n" + rest if rest else "\n")
    return text.rstrip() + "\n\n" + body + "\n"


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


imports = global_rule_imports()

for target in (home / ".claude" / "CLAUDE.md", home / ".codex" / "AGENTS.md"):
    text = target.read_text() if target.exists() else ""
    text = upsert(text, "memory", block)
    # Only the Claude Code file consumes `@` imports; Codex reads AGENTS.md directly.
    if imports and target.name == "CLAUDE.md":
        text = upsert(text, "imports", imports)
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
# Runs after the merge above, so a retired script's registration is already gone; this removes the
# link that pointed at it, and only links whose target is inside this repo.
prune_broken_symlinks ~/.claude/hooks
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
# Retired names (modules the old directory walk linked, and basenames renamed with wrappers) are
# removed by `prune_retired_tool_links` and `prune_broken_symlinks` below: both are driven by the
# catalog, so no retired name needs to be listed here.
if ! duplicate_tool_basenames; then
  echo "  ERROR: tool tree has a duplicate basename; ~/.agent/bin was not updated." >&2
  exit 1
fi
link_catalog_commands ~/.agent/bin
prune_retired_tool_links ~/.agent/bin
prune_broken_symlinks ~/.agent/bin
if [ "$DRY_RUN" -eq 0 ] && [ ! -d "$HOME/.agent/memory/.git" ]; then
  CREW_MEMORY_DIR="$HOME/.agent/memory" python3 "$SCRIPT_DIR/.agent/tools/memory/crew-mem.py" init
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
