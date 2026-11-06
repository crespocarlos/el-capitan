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
test "$(stat -f '%OLp' "$home/.claude/CLAUDE.md" 2>/dev/null || stat -c '%a' "$home/.claude/CLAUDE.md")" = 644
ls -d "$home"/.claude/agents.bak.* >/dev/null              # originals retained

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
printf '{bad' > "$home/broken.json"
if python3 "$root/.claude/merge_claude_settings.py" "$root/.claude/settings.json" "$home/broken.json" >/dev/null 2>&1; then exit 1; fi
test "$(cat "$home/broken.json")" = '{bad'

# Dry-run must change nothing.
before=$(find "$home" -type f | wc -l | tr -d ' ')
HOME="$home" bash "$root/install.sh" --dry-run >/dev/null
test "$before" = "$(find "$home" -type f | wc -l | tr -d ' ')"
