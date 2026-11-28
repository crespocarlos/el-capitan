#!/bin/bash
set -e

# Usage: install.sh [--dry-run] [--sandbox] [--claude-config-dir DIR ...]   install or upgrade from this checkout
#        install.sh --uninstall [--dry-run]                     remove what install created; ~/.agent data stays
# --dry-run prints every action and changes nothing. Every Claude config dir gets the settings merge,
# the agents link and the skills: ~/.claude, $CLAUDE_CONFIG_DIR when set, and each --claude-config-dir
# (repeatable). They are recorded in ~/.agent/install-manifest.json, and a later install covers them too.
# --sandbox turns Claude Code's sandbox on in each settings.json (filesystem and network limits for Bash and its children).
DRY_RUN=0
SANDBOX=()
UNINSTALL=0
ARGS=("$@")
EXTRA_CONFIG_DIRS=()
while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run) DRY_RUN=1 ;;
    --uninstall) UNINSTALL=1 ;;
    --sandbox) SANDBOX=(--sandbox) ;;
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
# tool would turn a finished install into a blocked shell. uv provides the interpreter (CPython 3.12+).
preflight() {
  local dep missing=""
  for dep in git gh jq uv; do
    command -v "$dep" >/dev/null 2>&1 || missing="$missing $dep"
  done
  if [ -n "$missing" ]; then
    echo "error: el-capitan needs git, gh, jq and uv; missing:$missing. Nothing was installed." >&2
    exit 1
  fi
}
preflight

# Run as `bash -c "$(curl ...)"`, there is no file and no checkout next to it: clone one and re-run
# the installer from there, because every link it writes points into the checkout.
source_file="${BASH_SOURCE[0]:-}"
if [ -z "$source_file" ] || [ ! -f "$source_file" ] \
  || [ ! -d "$(dirname "$source_file")/src/crew" ]; then
  checkout="${EL_CAPITAN_HOME:-$HOME/el-capitan}"
  if [ -f "$checkout/install.sh" ] && [ -f "$checkout/src/crew/tools.json" ]; then
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

# el-capitan's environment: ~/.agent/venv, built from pyproject.toml and uv.lock on a uv-managed CPython 3.12+.
# Every Python step below runs on it; ~/.agent/bin links the catalog's commands to its launchers. The package is
# installed as a copy (not editable), so switching or deleting this checkout never breaks the tools.
VENV="$HOME/.agent/venv"
if [ "$UNINSTALL" -eq 0 ] && [ "$DRY_RUN" -eq 0 ]; then
  if ! UV_PROJECT_ENVIRONMENT="$VENV" uv sync --project "$SCRIPT_DIR" --frozen --no-dev --managed-python --no-editable \
    --reinstall-package el-capitan --quiet; then
    echo "error: could not build $VENV (uv sync --frozen); see the lines above." >&2
    exit 1
  fi
fi
PY="$VENV/bin/python"

# gitleaks: the shell guard's credentials rule scans commits and pushes with it, and denies them without it. A pinned
# release binary checked against its SHA-256 (scripts/install-bin.sh), unless one is already on PATH.
if [ "$UNINSTALL" -eq 0 ] && ! command -v gitleaks >/dev/null 2>&1 && [ ! -x "$HOME/.agent/bin/gitleaks" ]; then
  if [ "$DRY_RUN" -eq 1 ]; then
    echo "  [dry-run] install the pinned gitleaks into ~/.agent/bin"
  elif ! bash "$SCRIPT_DIR/scripts/install-bin.sh" gitleaks "$HOME/.agent/bin" >/dev/null; then
    echo "  WARN: gitleaks is not installed, so the shell guard denies commits and pushes; re-run install.sh" >&2
  fi
fi
[ -x "$PY" ] || PY=$(uv python find '>=3.12') || { echo "error: no Python 3.12+ (uv python install 3.12)" >&2; exit 1; }

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
  "$PY" "$SCRIPT_DIR/.claude/uninstall.py" "$HOME" "$SCRIPT_DIR" "${dry[@]}" || status=$?
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


# The catalog's `kind: command` entries as `target<TAB>name` lines: the whole of what ~/.agent/bin
# receives. A Python command's target is its launcher in the venv (pyproject.toml `[project.scripts]`),
# a shell command's its file in the checkout.
catalog_commands() {
  jq -r --arg venv "$VENV/bin" --arg tree "$SCRIPT_DIR/src/crew" '(.tools + .scripts)[] | select(.kind == "command")
    | (if (.name | endswith(".py")) then "\($venv)/\(.name)" else "\($tree)/\(.dir)/\(.name)" end) + "\t" + .name' \
    "$SCRIPT_DIR/src/crew/tools.json"
}

# Link only what the catalog declares as a command. A module is imported and an asset is read, so
# neither belongs on the command surface.
link_catalog_commands() {
  local dest="$1" listing target name
  if [[ ! -f "$SCRIPT_DIR/src/crew/tools.json" ]]; then
    echo "error: missing tool catalog $SCRIPT_DIR/src/crew/tools.json" >&2
    return 1
  fi
  listing=$(catalog_commands) || return 1
  if [[ -z "$listing" ]]; then
    echo "error: the tool catalog declares no commands" >&2
    return 1
  fi
  run mkdir -p "$dest"
  while IFS=$'\t' read -r target name; do
    run ln -sf "$target" "$dest/$name"
  done <<< "$listing"
}

# Remove links this installer created into the tool tree or the venv whose basename is no longer a
# cataloged command: their targets still exist, so `prune_broken_symlinks` leaves them behind. Only
# those links are touched, so a user's own file in the same directory is safe.
prune_retired_tool_links() {
  local dir="$1" commands link target name
  [[ -d "$dir" ]] || return 0
  [[ -f "$SCRIPT_DIR/src/crew/tools.json" ]] || return 0
  commands=$(catalog_commands | cut -f2) || return 1
  shopt -s nullglob
  for link in "$dir"/*; do
    [[ -L "$link" ]] || continue
    target=$(readlink "$link")
    [[ "$target" == "$SCRIPT_DIR/src/crew/"* || "$target" == "$VENV/bin/"* ]] || continue
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

run mkdir -p ~/.agent/tasks ~/.agent/journal ~/.agent/bin
# The directories install links into (`install_blocks.LINKS`), and the record of which it created and
# from which checkout, in ~/.agent/install-manifest.json: `--uninstall` removes only those.
if [ "$DRY_RUN" -eq 1 ]; then
  echo "  [dry-run] create the install directories and record them in ~/.agent/install-manifest.json"
else
  "$PY" "$SCRIPT_DIR/.claude/install_blocks.py" prepare "$HOME" "$SCRIPT_DIR" "${EXTRA_CONFIG_DIRS[@]}"
fi
# The Claude config dirs, ~/.claude first: the recorded ones and those this run names.
CONFIG_DIRS=()
while IFS= read -r config_dir; do
  [ -n "$config_dir" ] && CONFIG_DIRS+=("$config_dir")
done < <("$PY" "$SCRIPT_DIR/.claude/install_blocks.py" config-dirs "$HOME" "${EXTRA_CONFIG_DIRS[@]}")
if [ "${#CONFIG_DIRS[@]}" -eq 0 ]; then
  echo "error: could not list the Claude config dirs (install_blocks.py config-dirs)" >&2
  exit 1
fi

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

if [ "$DRY_RUN" -eq 1 ]; then
  echo "  [dry-run] upsert memory adapters and global rule imports"
else
  mkdir -p "$HOME/.claude" "$HOME/.codex" "$HOME/.agent"
  "$PY" "$SCRIPT_DIR/.claude/install_blocks.py" upsert "$HOME" "$SCRIPT_DIR"
fi

# Claude Code's settings: the claude-code adapter's fragment (hooks running crew-hook.py, and permissions) merged into
# each config dir's settings.json rather than linked. What the merge adds (absent before) is recorded in the install
# manifest, per config dir; uninstall removes only that.
# Crew memory is the one memory store: Claude Code's auto-memory goes off in a dir (`autoMemoryEnabled:
# false`) only once none of its entries is left to import, so nothing it remembered is lost.
SETTINGS_SRC="$HOME/.agent/state/claude-settings.json"
if [ "$DRY_RUN" -eq 0 ]; then
  mkdir -p "$HOME/.agent/state"
  "$PY" -m crew.harness.harness_install show claude-code .claude/settings.json "$HOME" "$SCRIPT_DIR" >"$SETTINGS_SRC"
fi
for config_dir in "${CONFIG_DIRS[@]}"; do
  SETTINGS_DEST="$config_dir/settings.json"
  if [ "$DRY_RUN" -eq 1 ]; then
    echo "  [dry-run] merge settings.json → $SETTINGS_DEST"
    continue
  fi
  memory_flag=()
  check_status=0
  left=$("$VENV/bin/crew-mem.py" import-claude --check --config-dir "$config_dir" 2>&1) || check_status=$?
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
  if ! "$PY" "$SCRIPT_DIR/.claude/merge_claude_settings.py" "$SETTINGS_SRC" "$SETTINGS_DEST" --manifest "$HOME" "${memory_flag[@]}" ${SANDBOX[@]+"${SANDBOX[@]}"}; then
    echo "  ERROR: settings.json merge failed — hooks may not be registered" >&2
    echo "  Run manually: $PY $SCRIPT_DIR/.claude/merge_claude_settings.py $SETTINGS_SRC $SETTINGS_DEST --manifest $HOME" >&2
    FAILED=1
  fi
done

# What every harness reads, rendered by its adapter (crew.harness, harness_install apply): Claude Code's rules, agents
# and skills under ~/.claude, the Cursor plugin at ~/.cursor/plugins/local/el-capitan, the Cursor CLI's deny tokens,
# Codex's files, the reference store every prompt reads by path, and the hook rules copied into ~/.agent/hooks, so the
# rules, their contract and the registrations change together, only here. It runs after the settings merge, so the
# layout before the adapters loses its registrations before its scripts.
if [ "$DRY_RUN" -eq 1 ]; then
  echo "  [dry-run] install every adapter's rendered files"
elif ! "$PY" -m crew.harness.harness_install apply "$HOME" "$SCRIPT_DIR"; then
  echo "  ERROR: the harness files were not installed (python -m crew.harness.harness_install apply)" >&2
  FAILED=1
fi

# `agents` and `skills` of every other config dir: a directory link into ~/.claude when the dir has none (an earlier
# install's link into ~/.cursor is replaced). When it is a real directory (another tool syncs into it), one link per
# crew entry inside it, leaving its other entries alone. Anything of the user's (a link elsewhere, a file or link of
# a crew entry's name) is kept with a line, never replaced, and uninstall removes only the links named after their
# ~/.claude entry.
link_config_entries() {
  local target="$1/$2" source="$HOME/.claude/$2" entry name link
  if [ -L "$target" ] && [ "$(readlink "$target")" = "$HOME/.cursor/$2" ]; then run rm -f "$target"; fi
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
link_catalog_commands ~/.agent/bin
prune_retired_tool_links ~/.agent/bin
prune_broken_symlinks ~/.agent/bin
if [ "$DRY_RUN" -eq 0 ] && [ ! -d "$HOME/.agent/memory/.git" ]; then
  CREW_MEMORY_DIR="$HOME/.agent/memory" "$VENV/bin/crew-mem.py" init
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
echo "Done. Installed el-capitan for the harnesses listed above."
echo "  Claude config dirs: ${CONFIG_DIRS[*]}"
echo "  Journal:  ~/.agent/journal/ (monthly files, not tracked by git)"
echo "~/.agent/tasks/ is ready for per-repo/branch task state."
COMPLETED=1
