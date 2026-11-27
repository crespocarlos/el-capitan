#!/bin/bash
set -e

# Usage: install.sh [--dry-run] [--claude-config-dir DIR ...]   install or upgrade from this checkout
#        install.sh --uninstall [--dry-run]                     remove what install created; ~/.agent data stays
# --dry-run prints every action and changes nothing. Every Claude config dir gets the settings merge,
# the agents link and the skills: ~/.claude, $CLAUDE_CONFIG_DIR when set, and each --claude-config-dir
# (repeatable). They are recorded in ~/.agent/install-manifest.json, and a later install covers them too.
DRY_RUN=0
UNINSTALL=0
ARGS=("$@")
EXTRA_CONFIG_DIRS=()
while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run) DRY_RUN=1 ;;
    --uninstall) UNINSTALL=1 ;;
    --claude-config-dir)
      if [ $# -lt 2 ] || [ -z "$2" ]; then echo "error: --claude-config-dir needs a directory" >&2; exit 1; fi
      EXTRA_CONFIG_DIRS+=("$2")
      shift ;;
    *) echo "Unknown argument: $1" >&2; exit 1 ;;
  esac
  shift
done
if [ "$UNINSTALL" -eq 1 ] && [ "${#EXTRA_CONFIG_DIRS[@]}" -gt 0 ]; then
  echo "error: --claude-config-dir is an install option; --uninstall reverses every config dir the manifest records" >&2
  exit 1
fi
if [ -n "${CLAUDE_CONFIG_DIR:-}" ]; then EXTRA_CONFIG_DIRS+=("$CLAUDE_CONFIG_DIR"); fi

# Every dependency is checked before anything is written: the guard hooks fail closed, so a missing
# interpreter would turn a finished install into a blocked shell.
preflight() {
  local dep missing=""
  # Uninstalling needs only the interpreter that reverses the settings merges.
  [ "$UNINSTALL" -eq 1 ] && command -v python3 >/dev/null 2>&1 && return 0
  for dep in python3 git gh jq; do
    command -v "$dep" >/dev/null 2>&1 || missing="$missing $dep"
  done
  if [ -n "$missing" ]; then
    echo "error: el-capitan needs python3 (3.9 or newer), git, gh and jq; missing:$missing. Nothing was installed." >&2
    exit 1
  fi
  if ! python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)'; then
    echo "error: el-capitan needs python3 3.9 or newer; found $(python3 -V 2>&1). Nothing was installed." >&2
    exit 1
  fi
}
preflight

# Run as `bash -c "$(curl ...)"`, there is no file and no checkout next to it: clone one and re-run
# the installer from there, because every link it writes points into the checkout.
source_file="${BASH_SOURCE[0]:-}"
if [ -z "$source_file" ] || [ ! -f "$source_file" ] \
  || [ ! -d "$(dirname "$source_file")/.agent/tools" ]; then
  checkout="${EL_CAPITAN_HOME:-$HOME/el-capitan}"
  if [ -f "$checkout/install.sh" ] && [ -f "$checkout/.agent/tools/tools.json" ]; then
    echo "Using the existing checkout at $checkout (not updated; run git -C $checkout pull to upgrade)"
  elif [ "$UNINSTALL" -eq 1 ]; then
    echo "error: no el-capitan checkout at $checkout to uninstall from; run its install.sh --uninstall. Nothing was changed." >&2
    exit 1
  elif [ -e "$checkout" ]; then
    echo "error: $checkout exists and is not an el-capitan checkout; set EL_CAPITAN_HOME to another path. Nothing was installed." >&2
    exit 1
  elif [ "$DRY_RUN" -eq 1 ]; then
    echo "  [dry-run] clone ${EL_CAPITAN_REPO_URL:-https://github.com/crespocarlos/el-capitan.git} to $checkout, then install from there"
    exit 0
  elif ! git clone --quiet "${EL_CAPITAN_REPO_URL:-https://github.com/crespocarlos/el-capitan.git}" "$checkout"; then
    echo "error: could not clone el-capitan to $checkout. Nothing was installed." >&2
    exit 1
  fi
  exec bash "$checkout/install.sh" "${ARGS[@]}"
fi

SCRIPT_DIR="$(cd "$(dirname "$source_file")" && pwd)"
FAILED=0
COMPLETED=0
# `set -e` stops at the first failing step; say so, so a stopped run never reads as a finished one.
trap 'status=$?; if [ "$COMPLETED" -eq 0 ] && [ "$status" -ne 0 ]; then echo "Install INCOMPLETE (exit $status) — fix the error above and re-run install.sh." >&2; fi' EXIT

# Wrapper: print action in dry-run, execute otherwise.
run() {
  if [ "$DRY_RUN" -eq 1 ]; then
    echo "  [dry-run] $*"
  else
    "$@"
  fi
}

# `--uninstall` (`.claude/uninstall.py`): the settings entries install recorded as added and the managed
# blocks first, then the links into the recorded checkout and the directories install created.
# ~/.agent data and backups stay.
if [ "$UNINSTALL" -eq 1 ]; then
  if [ "$DRY_RUN" -eq 1 ]; then echo "Dry-run: el-capitan uninstall (no changes will be made)"; else echo "Uninstalling el-capitan"; fi
  echo "  Source: $SCRIPT_DIR"
  dry=()
  [ "$DRY_RUN" -eq 1 ] && dry=(--dry-run)
  status=0
  python3 "$SCRIPT_DIR/.claude/uninstall.py" "$HOME" "$SCRIPT_DIR" "${dry[@]}" || status=$?
  for backup in "$HOME"/.claude/*.bak.* "$HOME"/.cursor/hooks.json.bak.*; do
    if [ -e "$backup" ]; then echo "  Kept a backup install made: $backup"; fi
  done
  COMPLETED=1
  if [ "$status" -ne 0 ]; then
    echo "Uninstall INCOMPLETE (exit $status) — see the lines above." >&2
    exit "$status"
  fi
  if [ "$DRY_RUN" -eq 1 ]; then echo "Dry-run finished; nothing was changed."; exit 0; fi
  echo "Uninstalled. ~/.agent (tasks, journal, memory) stays; delete it yourself if you want it gone."
  exit 0
fi

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

run mkdir -p ~/.agent/tasks ~/.agent/journal ~/.agent/bin
# The directories install links into (`install_blocks.LINKS`), and the record of which it created and
# from which checkout, in ~/.agent/install-manifest.json: `--uninstall` removes only those.
if [ "$DRY_RUN" -eq 1 ]; then
  echo "  [dry-run] create the install directories and record them in ~/.agent/install-manifest.json"
else
  python3 "$SCRIPT_DIR/.claude/install_blocks.py" prepare "$HOME" "$SCRIPT_DIR" "${EXTRA_CONFIG_DIRS[@]}"
fi
# The Claude config dirs, ~/.claude first: the recorded ones and those this run names.
CONFIG_DIRS=()
while IFS= read -r config_dir; do
  [ -n "$config_dir" ] && CONFIG_DIRS+=("$config_dir")
done < <(python3 "$SCRIPT_DIR/.claude/install_blocks.py" config-dirs "$HOME" "${EXTRA_CONFIG_DIRS[@]}")
if [ "${#CONFIG_DIRS[@]}" -eq 0 ]; then
  echo "error: could not list the Claude config dirs (install_blocks.py config-dirs)" >&2
  exit 1
fi

# ~/.claude/agents and ~/.claude/skills are directory symlinks to their ~/.cursor equivalents.
# Both Cursor and Claude Code consumers are satisfied from a single set of files in ~/.cursor/.
# Migrate: if they're real directories (old file-per-file layout), replace with a dir symlink.
link_managed_dir() {
  local target="$1" dir="$2" count backup restored file name skill
  if [ -d "$target" ] && [ ! -L "$target" ]; then
    count=$(find "$target" -maxdepth 1 -name '*.md' 2>/dev/null | wc -l | tr -d ' ')
    # Never delete: hand-placed and third-party agents live here. Move aside so the
    # install can proceed and the files stay recoverable.
    backup="${target}.bak.$(date +%s)"
    while [ -e "$backup" ]; do backup="${backup}x"; done
    echo "  $target is a real directory ($count .md files) — moving to $backup and linking the managed dir."
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
}
link_managed_dir "$HOME/.claude/agents" agents
link_managed_dir "$HOME/.claude/skills" skills

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
# Agents are linked one by one, except a templated agent (`tools:` ends in `# {{mcp_servers}}`) that already has
# a rendered copy: a re-install never swaps that copy for a link. Without a copy the link is the fallback, and
# its source line is a valid list of the class's native tools.
TEMPLATED=$(python3 "$SCRIPT_DIR/.claude/install_blocks.py" templated-agents "$HOME" "$SCRIPT_DIR" 2>/dev/null) || TEMPLATED=""
run mkdir -p ~/.cursor/agents
for agent in "$SCRIPT_DIR"/.cursor/agents/*.md; do
  name=$(basename "$agent")
  if grep -qxF "$name" <<<"$TEMPLATED" && [ -f ~/.cursor/agents/"$name" ] && [ ! -L ~/.cursor/agents/"$name" ]; then
    continue
  fi
  run ln -sf "$agent" ~/.cursor/agents/"$name"
done
for agent_dir in crew-reviewer references; do
  if [ -d "$SCRIPT_DIR/.cursor/agents/$agent_dir" ]; then
    run ln -sfn "$SCRIPT_DIR/.cursor/agents/$agent_dir" ~/.cursor/agents/$agent_dir
  fi
done
prune_broken_symlinks ~/.cursor/agents
# The templated agents are written as regular files rendered from `mcp` in ~/.agent/config.json (one
# `mcp__<server>__*` per named server). Every config dir's `agents` points into ~/.cursor/agents, so each sees the
# rendered copy; a re-install re-renders, and the SessionStart hook `agents-refresh.sh` repairs a stale copy. A
# failure is one line and the install goes on: an agent without a copy keeps its valid source link.
if [ "$DRY_RUN" -eq 1 ]; then
  echo "  [dry-run] render the read-only agents into ~/.cursor/agents from the mcp section of ~/.agent/config.json"
elif ! rendered=$(python3 "$SCRIPT_DIR/.claude/install_blocks.py" render-agents "$HOME" "$SCRIPT_DIR" 2>&1); then
  echo "  WARNING: render-agents failed ($(printf '%s' "$rendered" | tail -n 1)); read-only agents keep their source tools: line"
else
  printf '%s\n' "$rendered"
fi

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
        # Its reference links went with it: drop the dangling ones (repo-owned only), then any folder left empty.
        for sub in "${d%/}" "$d"*/; do
          prune_broken_symlinks "${sub%/}"
        done
        shopt -s nullglob
        for sub in "$d"*/; do rmdir "$sub" 2>/dev/null || true; done
        rmdir "$d" 2>/dev/null || true
      fi
    fi
  done
  shopt -u nullglob
fi

# `agents` and `skills` of every other config dir: a directory link into ~/.cursor when the dir has none.
# When it is a real directory (another tool syncs into it), one link per crew entry inside it, leaving its
# other entries alone. Anything of the user's (a link elsewhere, a file or link of a crew entry's name) is
# kept with a line, never replaced, and uninstall removes only the links named after their ~/.cursor entry.
link_config_entries() {
  local target="$1/$2" source="$HOME/.cursor/$2" entry name link
  if [ -L "$target" ]; then
    [ "$(readlink "$target")" = "$source" ] || echo "  kept $target: your link to $(readlink "$target"); crew $2 are not linked there"
    return 0
  fi
  if [ ! -e "$target" ]; then
    run ln -s "$source" "$target"
    return 0
  fi
  if [ ! -d "$target" ]; then
    echo "  kept $target: not a directory; crew $2 are not linked there"
    return 0
  fi
  shopt -s nullglob
  for entry in "$SCRIPT_DIR/.cursor/$2"/*; do
    name=$(basename "$entry")
    link="$target/$name"
    if [ -L "$link" ] && [ "$(readlink "$link")" = "$source/$name" ]; then continue; fi
    if [ -e "$link" ] || [ -L "$link" ]; then
      echo "  kept $link: yours; the crew entry $name is not linked there"
      continue
    fi
    run ln -s "$source/$name" "$link"
  done
  for link in "$target"/*; do
    name=$(basename "$link")
    if [ -L "$link" ] && [ ! -e "$link" ] && [ "$(readlink "$link")" = "$source/$name" ]; then run rm -f "$link"; fi
  done
  shopt -u nullglob
}
for config_dir in "${CONFIG_DIRS[@]:1}"; do
  link_config_entries "$config_dir" agents
  link_config_entries "$config_dir" skills
done

if [ "$DRY_RUN" -eq 1 ]; then
  echo "  [dry-run] upsert memory adapters and global rule imports"
else
  mkdir -p "$HOME/.claude" "$HOME/.codex" "$HOME/.agent"
  python3 "$SCRIPT_DIR/.claude/install_blocks.py" upsert "$HOME" "$SCRIPT_DIR"
fi

# Claude Code hooks (settings + hook scripts)
if [ -f "$SCRIPT_DIR/.claude/settings.json" ]; then
  # settings.json: merge el-capitan hooks into existing config rather than symlinking.
  # This is a managed copy — re-run install.sh to pick up upstream changes.
  SETTINGS_SRC="$SCRIPT_DIR/.claude/settings.json"
  # What the merge adds (absent before) is recorded in the install manifest, per config dir; uninstall
  # removes only that. Every config dir's hooks run the scripts in ~/.claude/hooks.
  # Crew memory is the one memory store: Claude Code's auto-memory goes off in a dir (`autoMemoryEnabled:
  # false`) only once none of its entries is left to import, so nothing it remembered is lost.
  for config_dir in "${CONFIG_DIRS[@]}"; do
    SETTINGS_DEST="$config_dir/settings.json"
    if [ "$DRY_RUN" -eq 1 ]; then
      echo "  [dry-run] merge settings.json → $SETTINGS_DEST"
      continue
    fi
    memory_flag=()
    check_status=0
    left=$(python3 "$SCRIPT_DIR/.agent/tools/memory/crew-mem.py" import-claude --check --config-dir "$config_dir" 2>&1) || check_status=$?
    pending=$(grep -c '^not imported:' <<< "$left" || true)
    review=$(grep -c '^review ' <<< "$left" || true)
    if [ "$check_status" -eq 0 ]; then
      memory_flag=(--auto-memory-off)
    elif [ "$check_status" -eq 1 ]; then
      if [ "$pending" -gt 0 ]; then
        echo "  auto-memory left on in $config_dir: Claude memory entries to import: $pending."
        echo "    Run ~/.agent/bin/crew-mem.py import-claude --config-dir $config_dir, import the drafts, then re-run install.sh."
      fi
      if [ "$review" -gt 0 ]; then
        echo "  auto-memory left on in $config_dir: Claude memory entries for your review: $review."
        echo "    ~/.agent/bin/crew-mem.py import-claude --check --config-dir $config_dir lists them: decide, then delete or move each file."
      fi
    else
      echo "  auto-memory left on in $config_dir: could not check its Claude memory entries: ${left%%$'\n'*}" >&2
    fi
    if ! python3 "$SCRIPT_DIR/.claude/merge_claude_settings.py" "$SETTINGS_SRC" "$SETTINGS_DEST" --manifest "$HOME" "${memory_flag[@]}"; then
      echo "  ERROR: settings.json merge failed — hooks may not be registered" >&2
      echo "  Run manually: python3 $SCRIPT_DIR/.claude/merge_claude_settings.py $SETTINGS_SRC $SETTINGS_DEST --manifest $HOME" >&2
      FAILED=1
    fi
  done
fi
link_dir_files "$SCRIPT_DIR/.claude/hooks" ~/.claude/hooks
# The guard rules and the shared preamble live in subdirectories, and each is linked as a whole
# directory: a hook sources `lib/hook.sh` relative to its own file, so a flat copy of the `.sh` files
# would break that line. `prune_broken_symlinks` does not recurse, so these two are managed here. A
# real directory at the destination is an earlier partial install of the same names, replaced so the
# link exists; only these two names are ever removed, and only when this repo ships them.
for sub in lib guard; do
  if [ -d "$SCRIPT_DIR/.claude/hooks/$sub" ]; then
    if [ -d "$HOME/.claude/hooks/$sub" ] && [ ! -L "$HOME/.claude/hooks/$sub" ]; then
      run rm -rf "$HOME/.claude/hooks/$sub"
    fi
    run ln -sfn "$SCRIPT_DIR/.claude/hooks/$sub" "$HOME/.claude/hooks/$sub"
  fi
done
# Runs after the merge above, so a retired script's registration is already gone; this removes the
# link that pointed at it, and only links whose target is inside this repo.
prune_broken_symlinks ~/.claude/hooks
if [ "$DRY_RUN" -eq 0 ]; then
  mkdir -p "$HOME/.cursor"
  if ! python3 "$SCRIPT_DIR/.claude/merge_cursor_hooks.py" "$SCRIPT_DIR/.cursor/hooks.template.json" "$HOME/.cursor/hooks.json" --manifest "$HOME"; then
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
  COMPLETED=1
  echo "Install INCOMPLETE — see errors above. Hooks or settings may not be registered." >&2
  exit 1
fi
if [ "$DRY_RUN" -eq 1 ]; then
  COMPLETED=1
  echo "Dry-run finished; nothing was changed."
  exit 0
fi
echo "Done. Installed:"
echo "  Rules:   $(ls ~/.cursor/rules/*.mdc 2>/dev/null | wc -l | tr -d ' ') (symlinked → ~/.cursor/rules)"
echo "  Agents:   $(find ~/.cursor/agents -maxdepth 1 -name '*.md' -type l | wc -l | tr -d ' ') symlinked, the read-only ones rendered (→ ~/.cursor/agents ← ~/.claude/agents)"
echo "  Skills:   $(ls -d ~/.cursor/skills/*/ 2>/dev/null | wc -l | tr -d ' ') (symlinked → ~/.cursor/skills ← ~/.claude/skills)"
echo "  Claude config dirs: ${CONFIG_DIRS[*]}"
echo ""
echo "  Journal:  ~/.agent/journal/ (monthly files, not tracked by git)"

echo ""
echo "Add-ons go directly in ~/.cursor/agents/ or ~/.cursor/skills/ as regular files."
echo "~/.agent/tasks/ is ready for per-repo/branch task state."
COMPLETED=1
