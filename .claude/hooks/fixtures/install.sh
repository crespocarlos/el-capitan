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

# A retired hook in an event the template no longer has is dropped too, with the event left empty.
python3 - "$home/.claude/settings.json" "$home/.cursor/hooks.json" <<'PY'
import json, sys
for path, entry in zip(sys.argv[1:], ({"hooks": [{"type": "command", "command": "bash \"$HOME/.claude/hooks/session-event.sh\" end"}]},
                                      {"command": "bash \"$HOME/.claude/hooks/session-event.sh\" end"})):
    data = json.load(open(path))
    data["hooks"]["SessionEnd" if "settings" in path else "sessionEnd"] = [entry]
    json.dump(data, open(path, "w"), indent=2)
PY
HOME="$home" bash "$root/install.sh" >/dev/null
if grep -qe 'session-event.sh' -e '"SessionEnd"' -e '"sessionEnd"' "$home/.claude/settings.json" "$home/.cursor/hooks.json"; then exit 1; fi

# A skill deleted from the repo leaves no folder behind, not even one holding its dangling reference links.
mkdir -p "$home/.cursor/skills/crew-gone/references"
ln -s "$root/.cursor/skills/crew-gone/SKILL.md" "$home/.cursor/skills/crew-gone/SKILL.md"
ln -s "$root/.cursor/skills/crew-gone/references/policy.md" "$home/.cursor/skills/crew-gone/references/policy.md"
HOME="$home" bash "$root/install.sh" >/dev/null
test ! -e "$home/.cursor/skills/crew-gone"

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
assert any("memory-context.sh" in c for c in commands), "memory-context.sh is not registered"
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

# Uninstall round trip: a HOME holding the user's own CLAUDE.md, settings, Cursor hooks and agent is
# installed into and uninstalled from, and equals its snapshot again, except ~/.agent (data that stays)
# and the settings backup the merge wrote. `--uninstall --dry-run` changes nothing. The user's rule
# `Bash(git *)` and SessionStart hook equal template entries, and survive: uninstall removes only what
# install recorded as added. `Bash(ls:*)` is the legacy spelling of the template's `Bash(ls *)`: install
# keeps the user's spelling, adds no second rule, and records nothing for it.
round=$(mktemp -d)
trap 'rm -rf "$home" "$round"' EXIT
mkdir -p "$round/.claude" "$round/.cursor/agents"
printf '# Mine\n\n@AGENTS.md\n' > "$round/.claude/CLAUDE.md"
printf -- '---\nname: mine\n---\n' > "$round/.cursor/agents/mine.md"
ln -s "$round/unmounted/hook.sh" "$round/.cursor/agents/dangling.md"
python3 - "$round" <<'PY'
import json, sys
home = sys.argv[1]
reconcile = {"type": "command", "command": "bash \"${CLAUDE_PROJECT_DIR:-$PWD}/.claude/hooks/spec-status-reconcile.sh\"; exit 0"}
for path, data in ((f"{home}/.claude/settings.json", {"hooks": {"Stop": [{"hooks": [{"type": "command", "command": "bash mine.sh"}]}],
                                                                 "SessionStart": [{"hooks": [reconcile]}]},
                                                       "permissions": {"allow": ["Bash(my-own *)", "Bash(git *)", "Bash(ls:*)"]}}),
                   (f"{home}/.cursor/hooks.json", {"version": 1, "hooks": {"stop": [{"command": "bash mine.sh"}]}})):
    with open(path, "w") as handle:
        handle.write(json.dumps(data, indent=2) + "\n")
PY
tree_state() {
  (cd "$1" && find . ! -path './Library*' ! -path './.agent' ! -path './.agent/*' ! -name '*.json.bak.*' | sort | while IFS= read -r p; do
    if [ -L "$p" ]; then echo "$p -> $(readlink "$p")"; elif [ -f "$p" ]; then echo "$p $(cksum < "$p")"; else echo "$p/"; fi
  done)
}
pristine=$(tree_state "$round")
mode() { stat -c '%a' "$1" 2>/dev/null || stat -f '%OLp' "$1"; }
settings_mode=$(mode "$round/.claude/settings.json")
HOME="$round" bash "$root/install.sh" >/dev/null
grep -q '"Bash(ls:\*)"' "$round/.claude/settings.json"
if grep -q '"Bash(ls \*)"' "$round/.claude/settings.json"; then exit 1; fi
installed=$(tree_state "$round")
HOME="$round" bash "$root/install.sh" --uninstall --dry-run >/dev/null
test "$installed" = "$(tree_state "$round")"
HOME="$round" bash "$root/install.sh" --uninstall >/dev/null
test "$pristine" = "$(tree_state "$round")"
test "$settings_mode" = "$(mode "$round/.claude/settings.json")"   # the file keeps its mode
test -d "$round/.agent/memory"                              # data stays

# Uninstall unregisters before it deletes. An unreadable settings file stops it before any change; odd but
# valid shapes are skipped with a warning, and no remaining registration runs a script that is gone.
odd=$(mktemp -d)
trap 'rm -rf "$home" "$round" "$odd"' EXIT
HOME="$odd" bash "$root/install.sh" >/dev/null
links=$(find "$odd" -type l | wc -l | tr -d ' ')
cp "$odd/.cursor/hooks.json" "$odd/hooks.good" && cp "$odd/.claude/settings.json" "$odd/settings.good"
printf '{bad' > "$odd/.cursor/hooks.json"
if HOME="$odd" bash "$root/install.sh" --uninstall >/dev/null 2>&1; then exit 1; fi
test "$links" = "$(find "$odd" -type l | wc -l | tr -d ' ')"
cmp -s "$odd/settings.good" "$odd/.claude/settings.json"
python3 - "$odd" <<'PY'
import json, sys
home = sys.argv[1]
claude, cursor = json.load(open(f"{home}/settings.good")), json.load(open(f"{home}/hooks.good"))
claude["hooks"]["Stop"] = {"x": 1}
claude["hooks"]["PreToolUse"].append("a string")
cursor["hooks"]["stop"] = "x"
cursor["hooks"]["beforeShellExecution"].append(7)
json.dump(claude, open(f"{home}/.claude/settings.json", "w"))
json.dump(cursor, open(f"{home}/.cursor/hooks.json", "w"))
PY
HOME="$odd" bash "$root/install.sh" --uninstall > "$odd/out"
grep -q 'warning: ~/.claude/settings.json: hooks.Stop is not a list' "$odd/out"
python3 - "$odd" <<'PY'
import json, os, re, sys
home = sys.argv[1]
for path in (f"{home}/.claude/settings.json", f"{home}/.cursor/hooks.json"):
    text = open(path).read()
    for script in re.findall(r'\$HOME/(\.claude/hooks/[^"\s;]+)', text):
        assert os.path.exists(os.path.join(home, script)), f"{path} registers {script}, which is gone"
assert json.load(open(f"{home}/.claude/settings.json"))["hooks"]["Stop"] == {"x": 1}
PY

# A registration uninstall keeps keeps its script, whatever form names it: `~/` in settings.json, an
# absolute path in a failClosed Cursor entry. The user's own credentials.sh hook loses only the
# `onFailure` install added to it.
kept=$(mktemp -d)
trap 'rm -rf "$home" "$round" "$odd" "$kept"' EXIT
mkdir -p "$kept/.claude"
printf '%s\n' '{"hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": "bash \"$HOME/.claude/hooks/guard/credentials.sh\""}]}]}}' > "$kept/.claude/settings.json"
HOME="$kept" bash "$root/install.sh" >/dev/null
python3 - "$kept" <<'PY'
import json, sys
home = sys.argv[1]
claude, cursor = f"{home}/.claude/settings.json", f"{home}/.cursor/hooks.json"
data = json.load(open(claude))
data["hooks"]["PreToolUse"].append({"matcher": "Write", "hooks": [{"type": "command", "command": "bash ~/.claude/hooks/check-write-boundary.sh"}]})
json.dump(data, open(claude, "w"))
data = json.load(open(cursor))
data["hooks"]["beforeShellExecution"].append({"command": f'bash "{home}/.claude/hooks/notify-idle.sh"', "failClosed": True})
json.dump(data, open(cursor, "w"))
PY
if HOME="$kept" bash "$root/install.sh" --uninstall > "$kept/out" 2>&1; then exit 1; fi
grep -q 'check-write-boundary.sh' "$kept/out" && grep -q 'notify-idle.sh' "$kept/out" && grep -q 'guard/credentials.sh' "$kept/out"
test -e "$kept/.claude/hooks/check-write-boundary.sh" && test -e "$kept/.claude/hooks/notify-idle.sh"
test -e "$kept/.claude/hooks/guard/credentials.sh" && test -e "$kept/.claude/hooks/lib/hook.sh"
python3 - "$kept/.claude/settings.json" <<'PY'
import json, sys
hooks = [h for e in json.load(open(sys.argv[1]))["hooks"]["PreToolUse"] for h in e["hooks"]]
assert [h for h in hooks if "credentials" in h["command"]] == [{"type": "command", "command": 'bash "$HOME/.claude/hooks/guard/credentials.sh"'}], hooks
PY

# A settings.json that is a link (dotfiles) keeps its link; a rule install added that the template has
# since dropped is named when it goes.
linked=$(mktemp -d)
trap 'rm -rf "$home" "$round" "$odd" "$kept" "$linked"' EXIT
mkdir -p "$linked/.claude" "$linked/dotfiles"
ln -s "$linked/dotfiles/settings.json" "$linked/.claude/settings.json"
HOME="$linked" bash "$root/install.sh" >/dev/null
python3 - "$linked" <<'PY'
import json, sys
home = sys.argv[1]
for path, change in ((f"{home}/.agent/install-manifest.json", lambda d: d["claude_settings"]["rules"]["allow"].append("Bash(retired-tool *)")),
                     (f"{home}/.claude/settings.json", lambda d: d["permissions"]["allow"].append("Bash(retired-tool *)"))):
    data = json.load(open(path))
    change(data)
    json.dump(data, open(path, "w"))
PY
HOME="$linked" bash "$root/install.sh" --uninstall > "$linked/out"
grep -q 'no longer has: Bash(retired-tool \*)' "$linked/out"
test -L "$linked/.claude/settings.json" && test "$(cat "$linked/dotfiles/settings.json")" = '{}'

# An install from before the manifest: the template entries it left are removed unless the oldest
# backup already held them, so the user's `Bash(git *)` stays and every el-capitan entry goes.
legacy=$(mktemp -d)
trap 'rm -rf "$home" "$round" "$odd" "$kept" "$linked" "$legacy"' EXIT
mkdir -p "$legacy/.claude" "$legacy/.cursor"
printf '%s\n' '{"permissions": {"allow": ["Bash(git *)", "Bash(my-own *)"]}}' > "$legacy/.claude/settings.json"
printf '%s\n' '{"version": 1, "hooks": {"stop": [{"command": "bash mine.sh"}]}}' > "$legacy/.cursor/hooks.json"
HOME="$legacy" bash "$root/install.sh" >/dev/null
rm "$legacy/.agent/install-manifest.json"
HOME="$legacy" bash "$root/install.sh" >/dev/null
grep -q '"legacy"' "$legacy/.agent/install-manifest.json"
HOME="$legacy" bash "$root/install.sh" --uninstall >/dev/null
python3 - "$legacy" <<'PY'
import json, sys
home = sys.argv[1]
claude, cursor = json.load(open(f"{home}/.claude/settings.json")), json.load(open(f"{home}/.cursor/hooks.json"))
assert claude == {"permissions": {"allow": ["Bash(git *)", "Bash(my-own *)"]}}, claude   # the user's order, too
assert cursor == {"version": 1, "hooks": {"stop": [{"command": "bash mine.sh"}]}}, cursor
PY
# The same, when the first install created hooks.json, so its only backup is the one the upgrading
# install wrote: that backup is no evidence, and a hook whose script is an install link is the install's.
fresh=$(mktemp -d)
trap 'rm -rf "$home" "$round" "$odd" "$kept" "$linked" "$legacy" "$fresh"' EXIT
mkdir -p "$fresh/.claude"
printf '%s\n' '{"permissions": {"allow": ["Bash(mine *)"]}}' > "$fresh/.claude/settings.json"
HOME="$fresh" bash "$root/install.sh" >/dev/null
rm "$fresh/.agent/install-manifest.json"
HOME="$fresh" bash "$root/install.sh" >/dev/null
HOME="$fresh" bash "$root/install.sh" --uninstall >/dev/null
test -z "$(find "$fresh" -type l)"
python3 - "$fresh" <<'PY'
import json, os, sys
home = sys.argv[1]
assert json.load(open(f"{home}/.claude/settings.json")) == {"permissions": {"allow": ["Bash(mine *)"]}}
cursor = f"{home}/.cursor/hooks.json"
assert not os.path.exists(cursor) or ".claude/hooks/" not in open(cursor).read(), open(cursor).read()
PY

# Preflight and the README `bash -c "$(curl ...)"` form: an empty cwd, a fake HOME, no checkout next
# to the script, and no network (the clone reads a local copy of this tree).
bare=$(mktemp -d)
trap 'rm -rf "$home" "$round" "$odd" "$kept" "$linked" "$legacy" "$fresh" "$bare"' EXIT
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

# Uninstall from a moved checkout: the manifest names the install's checkout, so its dangling links go.
cp -R "$bare/src" "$bare/a"
HOME="$bare/h7" bash "$bare/a/install.sh" >/dev/null
mv "$bare/a" "$bare/a-moved"
HOME="$bare/h7" bash "$bare/a-moved/install.sh" --uninstall >/dev/null
test ! -e "$bare/h7/.claude" && test -z "$(find "$bare/h7/.agent" -maxdepth 2 -type l)"
# Installed from A, then from B, which lacks one of A's skills: uninstall from either removes every link.
cp -R "$bare/src" "$bare/c1" && cp -R "$bare/src" "$bare/c2"
rm -rf "$bare/c2/.cursor/skills/$(ls "$bare/c2/.cursor/skills" | head -1)"
for from in c1 c2; do
  HOME="$bare/h9-$from" bash "$bare/c1/install.sh" >/dev/null
  HOME="$bare/h9-$from" bash "$bare/c2/install.sh" >/dev/null
  HOME="$bare/h9-$from" bash "$bare/$from/install.sh" --uninstall >/dev/null
  test ! -e "$bare/h9-$from/.claude" && test ! -e "$bare/h9-$from/.cursor"
  test -z "$(find "$bare/h9-$from/.agent" -maxdepth 2 -type l)"
done
# Without a manifest, links into another checkout that exists stop the run, and nothing is removed.
cp -R "$bare/src" "$bare/b"
HOME="$bare/h8" bash "$bare/b/install.sh" >/dev/null
rm "$bare/h8/.agent/install-manifest.json"
if HOME="$bare/h8" bash "$root/install.sh" --uninstall > "$bare/out" 2>&1; then exit 1; fi
grep -qF "installed from $(cd "$bare/b" && pwd -P); run $(cd "$bare/b" && pwd -P)/install.sh --uninstall" "$bare/out"
test -L "$bare/h8/.agent/bin/crew-ls.py" && grep -q 'guard/credentials.sh' "$bare/h8/.cursor/hooks.json"

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
