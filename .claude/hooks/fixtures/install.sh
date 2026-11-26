#!/usr/bin/env bash
# install.sh migration and idempotency, against a throwaway HOME with a legacy layout.
set -euo pipefail
root=$(cd "$(dirname "$0")/../../.." && pwd)
home=$(mktemp -d)
trap 'rm -rf "$home"' EXIT
unset CREW_MEMORY_DIR CREW_JOURNAL_DIR CREW_TASK_DIR

# Legacy layout: real ~/.claude/agents|skills directories holding a user file plus a stale
# managed copy, and the older ~/.cursor/rules symlink form pointing at $root/rules.
mkdir -p "$home/.claude/agents" "$home/.claude/skills/my-skill" "$home/.cursor"
printf -- '---\nname: my-custom-agent\n---\n' > "$home/.claude/agents/my-custom-agent.md"
printf -- '---\nname: crew-builder\n---\nSTALE\n' > "$home/.claude/agents/crew-builder.md"
printf -- '---\nname: my-skill\n---\n' > "$home/.claude/skills/my-skill/SKILL.md"
ln -s "$root/rules" "$home/.cursor/rules"
printf '# Mine\n\n@AGENTS.md\n' > "$home/.claude/CLAUDE.md"
chmod 644 "$home/.claude/CLAUDE.md"

HOME="$home" bash "$root/install.sh" >/dev/null
test -f "$home/.cursor/agents/my-custom-agent.md"          # user agent stays loadable
test -L "$home/.cursor/agents/crew-builder.md"             # stale managed copy replaced
test -f "$home/.cursor/skills/my-skill/SKILL.md"           # user skill stays loadable
test -L "$home/.claude/agents"                             # managed dir is a symlink
test -d "$root/rules" && test ! -L "$root/rules"           # repo not linked into itself
# GNU first: GNU `stat -f` is a valid filesystem query that prints a block and exits 0, so the BSD
# spelling cannot go first. BSD stat rejects `-c` and falls through to `-f '%OLp'`.
test "$(stat -c '%a' "$home/.claude/CLAUDE.md" 2>/dev/null || stat -f '%OLp' "$home/.claude/CLAUDE.md")" = 644
ls -d "$home"/.claude/agents.bak.* >/dev/null              # originals retained

# A dangling symlink the installer did not create must survive: pruning is limited to links whose
# target is inside this repo. A user's link into an unmounted volume looks exactly like a stale one.
mkdir -p "$home/.claude/hooks"
ln -s "$home/unmounted/user-hook.sh" "$home/.claude/hooks/user-owned.sh"
ln -s "$root/.claude/hooks/gone-script.sh" "$home/.claude/hooks/repo-owned.sh"
HOME="$home" bash "$root/install.sh" >/dev/null
test -L "$home/.claude/hooks/user-owned.sh"                # user link kept
test ! -e "$home/.claude/hooks/repo-owned.sh" || test ! -L "$home/.claude/hooks/repo-owned.sh"

# Second run must not duplicate hooks or lose the restored add-ons.
before=$(python3 -c "import json,sys; d=json.load(open(sys.argv[1])); print(json.dumps({k:len(v) for k,v in sorted(d['hooks'].items())}))" "$home/.claude/settings.json")
HOME="$home" bash "$root/install.sh" >/dev/null
after=$(python3 -c "import json,sys; d=json.load(open(sys.argv[1])); print(json.dumps({k:len(v) for k,v in sorted(d['hooks'].items())}))" "$home/.claude/settings.json")
test "$before" = "$after"
test -f "$home/.cursor/agents/my-custom-agent.md"

# A user hook in an event this installer also uses must survive the merge.
python3 - "$home/.claude/settings.json" <<'PY'
import json, sys
path = sys.argv[1]
data = json.load(open(path))
data.setdefault("hooks", {}).setdefault("Stop", []).append(
    {"hooks": [{"type": "command", "command": "bash \"$HOME/my-own-stop-hook.sh\""}]})
json.dump(data, open(path, "w"), indent=2)
PY
HOME="$home" bash "$root/install.sh" >/dev/null
grep -q 'my-own-stop-hook.sh' "$home/.claude/settings.json"

# Merge scripts: idempotent, preserve foreign hooks, and fail loudly on bad input.
counts() {
  python3 - "$1" <<'PY'
import json, sys
data = json.load(open(sys.argv[1]))
print(json.dumps({k: len(v) for k, v in sorted(data["hooks"].items())}))
PY
}
cp "$root/.claude/settings.json" "$home/merge.json"
python3 "$root/.claude/merge_claude_settings.py" "$root/.claude/settings.json" "$home/merge.json" >/dev/null
first=$(counts "$home/merge.json")
python3 "$root/.claude/merge_claude_settings.py" "$root/.claude/settings.json" "$home/merge.json" >/dev/null
test "$first" = "$(counts "$home/merge.json")"

# A hook this repository retired must be removed from an existing install: the guard files fail
# closed, so a leftover registration would deny every command once its script is gone. A user hook that
# merely shares a retired file name must survive — the match is the managed path, not the basename.
python3 - "$home/merge.json" <<'PY'
import json, sys
path = sys.argv[1]
data = json.load(open(path))
data["hooks"].setdefault("PreToolUse", []).append({"hooks": [
    {"type": "command", "command": "bash \"$HOME/.claude/hooks/block-destructive-git.sh\""},
    {"type": "command", "command": "bash \"$HOME/myhooks/session-start.sh\""},
    {"type": "command", "command": "bash \"$HOME/.claude/hooks/my-own-hook.sh\""}]})
json.dump(data, open(path, "w"), indent=2)
PY
python3 "$root/.claude/merge_claude_settings.py" "$root/.claude/settings.json" "$home/merge.json" >/dev/null
if grep -q 'block-destructive-git.sh' "$home/merge.json"; then exit 1; fi
grep -q 'myhooks/session-start.sh' "$home/merge.json"
grep -q 'my-own-hook.sh' "$home/merge.json"
python3 - "$home/merge.json" <<'PY'
import json, sys
data = json.load(open(sys.argv[1]))
commands = [h["command"] for entries in data["hooks"].values() for e in entries for h in e.get("hooks", [])]
assert any("guard/credentials.sh" in c for c in commands), "guard/credentials.sh is not registered"
assert any("session-event.sh" in c and " start" in c for c in commands), "session-event start is not registered"
PY

# Same retirement rule for the Cursor template.
cp "$root/.cursor/hooks.template.json" "$home/hooks.json"
python3 - "$home/hooks.json" <<'PY'
import json, sys
path = sys.argv[1]
data = json.load(open(path))
data["hooks"]["beforeShellExecution"].append({"command": "bash \"$HOME/.claude/hooks/check-publish.sh\""})
json.dump(data, open(path, "w"), indent=2)
PY
python3 "$root/.claude/merge_cursor_hooks.py" "$root/.cursor/hooks.template.json" "$home/hooks.json" >/dev/null
if grep -q 'check-publish.sh' "$home/hooks.json"; then exit 1; fi
python3 "$root/.claude/merge_cursor_hooks.py" "$root/.cursor/hooks.template.json" "$home/hooks.json" >/dev/null
# Idempotent: a second merge leaves exactly the template's own entries, with no duplicate.
count=$(python3 -c "import json,sys; print(len(json.load(open(sys.argv[1]))['hooks']['beforeShellExecution']))" "$home/hooks.json")
template_count=$(python3 -c "import json,sys; print(len(json.load(open(sys.argv[1]))['hooks']['beforeShellExecution']))" "$root/.cursor/hooks.template.json")
test "$count" = "$template_count"
printf '{bad' > "$home/broken.json"
if python3 "$root/.claude/merge_claude_settings.py" "$root/.claude/settings.json" "$home/broken.json" >/dev/null 2>&1; then exit 1; fi
test "$(cat "$home/broken.json")" = '{bad'

# Dry-run must change nothing.
before=$(find "$home" -type f | wc -l | tr -d ' ')
HOME="$home" bash "$root/install.sh" --dry-run >/dev/null
test "$before" = "$(find "$home" -type f | wc -l | tr -d ' ')"

# Preflight and the README `bash -c "$(curl ...)"` form: an empty cwd, a fake HOME, no checkout next
# to the script, and no network (the clone reads a local copy of this tree).
bare=$(mktemp -d)
trap 'rm -rf "$home" "$bare"' EXIT
bash_bin=$(command -v bash)
script=$(cat "$root/install.sh")
mkdir -p "$bare/cwd" "$bare/nogh" "$bare/oldpy"
for tool in python3 git jq dirname basename cat mkdir; do ln -s "$(command -v "$tool")" "$bare/nogh/$tool"; done
for tool in git gh jq dirname basename cat mkdir; do
  path=$(command -v "$tool" || true)
  if [ -n "$path" ]; then ln -s "$path" "$bare/oldpy/$tool"; fi
done
printf '#!/bin/sh\n[ "$1" = -V ] && echo "Python 3.8.10" && exit 0\nexit 1\n' > "$bare/oldpy/python3"
chmod +x "$bare/oldpy/python3"
# macOS's system python3 writes its bytecode cache under ~/Library/Caches on any run; that is the
# interpreter, not the installer.
snapshot() { (cd "$1" && find . ! -path './Library*' | sort); }
refuses() {  # $1 fake HOME, $2 PATH, $3 expected text, then the command after `bash`
  local fake="$1" path="$2" expected="$3" before
  shift 3
  mkdir -p "$fake"
  before=$(snapshot "$fake")
  if (cd "$bare/cwd" && HOME="$fake" PATH="$path" "$bash_bin" "$@" >/dev/null 2>"$bare/err"); then exit 1; fi
  grep -q "$expected" "$bare/err"
  test "$(wc -l < "$bare/err" | tr -d ' ')" = 1           # one line
  test "$before" = "$(snapshot "$fake")"                  # nothing written
  test -z "$(ls -A "$bare/cwd")"
}
refuses "$bare/h1" "$bare/nogh" 'missing: gh' -c "$script"
refuses "$bare/h2" "$bare/nogh" 'missing: gh' "$root/install.sh"
refuses "$bare/h3" "$bare/oldpy" '3.9 or newer' -c "$script"
mkdir -p "$bare/h4/el-capitan" && touch "$bare/h4/el-capitan/notes.txt"
refuses "$bare/h4" "$PATH" 'not an el-capitan checkout' -c "$script"
(cd "$bare/cwd" && HOME="$bare/h5" EL_CAPITAN_REPO_URL="file://$bare/missing" "$bash_bin" -c "$script" >/dev/null 2>&1) && exit 1
test ! -e "$bare/h5/el-capitan" && test ! -e "$bare/h5/.agent"

# A clone of this tree, working-tree changes included, stands in for GitHub.
python3 - "$root" "$bare/src" <<'PY'
import os, shutil, subprocess, sys
root, dest = sys.argv[1], sys.argv[2]
names = subprocess.run(["git", "-C", root, "ls-files", "-co", "--exclude-standard", "-z"], check=True, capture_output=True, text=True).stdout.split("\0")
for name in filter(None, names):
    source = os.path.join(root, name)
    if os.path.lexists(source):
        os.makedirs(os.path.dirname(os.path.join(dest, name)), exist_ok=True)
        shutil.copy2(source, os.path.join(dest, name), follow_symlinks=False)
PY
git -C "$bare/src" init -q
git -C "$bare/src" add -A
git -C "$bare/src" -c user.name=fixture -c user.email=fixture@example.invalid -c commit.gpgsign=false commit -qm tree --no-verify
(cd "$bare/cwd" && HOME="$bare/h6" EL_CAPITAN_REPO_URL="file://$bare/src" "$bash_bin" -c "$script" > "$bare/out")
test -f "$bare/h6/el-capitan/install.sh"
case "$(readlink "$bare/h6/.agent/bin/crew-mem.py")" in "$bare/h6/el-capitan/"*) ;; *) exit 1 ;; esac
grep -q '^Done. Installed:' "$bare/out"
test -z "$(ls -A "$bare/cwd")"
# A second curl-mode run reuses the checkout instead of cloning over it, and says it was not updated.
(cd "$bare/cwd" && HOME="$bare/h6" EL_CAPITAN_REPO_URL="file://$bare/missing" "$bash_bin" -c "$script" > "$bare/out")
grep -qF "Using the existing checkout at $bare/h6/el-capitan (not updated; run git -C $bare/h6/el-capitan pull to upgrade)" "$bare/out"

# The summary prints only after every step: a failing step ends the run without it.
if [ "$(id -u)" = 0 ]; then
  echo "skip: failing install step: root writes through mode 000, so no step fails" >&2
else
  chmod 000 "$bare/h6/.claude"
  if (HOME="$bare/h6" bash "$root/install.sh" > "$bare/out" 2>&1); then chmod 755 "$bare/h6/.claude"; exit 1; fi
  chmod 755 "$bare/h6/.claude"
  if grep -q '^Done. Installed:' "$bare/out"; then exit 1; fi
  grep -q 'Install INCOMPLETE' "$bare/out"
fi
