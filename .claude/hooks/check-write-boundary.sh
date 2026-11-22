#!/usr/bin/env bash
# Deny writes outside the active worktree, after normalizing both the path and the allowlist.
set -euo pipefail
HOOK_NAME=check-write-boundary
# shellcheck source=lib/hook.sh
. "$(dirname "$0")/lib/hook.sh"
hook_input
hook_event
path=$(hook_field file_path)
cwd=$HOOK_CWD
[ -n "$path" ] || hook_allow

# Tool paths may be relative to the session cwd, which is not the hook's own cwd.
case "$path" in /*) ;; *) path="$cwd/$path" ;; esac

# Resolve before any containment check: `repo/x/../../outside.md` starts with the repo prefix but
# escapes it, and a symlinked directory inside the repo can reach outside. On macOS /tmp is a
# symlink to /private/tmp, so the allowlist below is resolved the same way, or a raw `/tmp/*` prefix
# would never match a resolved path and every temp write would be denied.
resolve() { python3 -c 'import os,sys; print(os.path.realpath(sys.argv[1]))' "$1" 2>/dev/null; }
normalized=$(resolve "$path") || normalized=""
[ -n "$normalized" ] && path="$normalized"

# The temp root is `$TMPDIR`, not `/tmp`: on macOS it is a per-user `/var/folders/…/T` directory,
# and `tempfile.gettempdir()` in every review tool writes there. Allowing only `/tmp` denied the
# review pipeline its own scratch directory, which is how a guard breaks the workflow it protects.
# Both are consulted because a caller may name either, and `mktemp` on Linux still uses `/tmp`.
for prefix in "$HOME/.agent" "$HOME/.claude" "$HOME/.cursor" "/tmp" "$TMPDIR"; do
  resolved=$(resolve "$prefix") || continue
  [ -n "$resolved" ] || continue
  case "$path" in "$resolved"/*) hook_allow ;; esac
done

# Probe the nearest existing ancestor; a missing directory is not evidence of an escape. A failure
# here leaves `repo` empty, which the branch below reads as "outside permitted worktrees": refusing
# the write is the safe direction, so the call is allowed to fail.
probe=$(dirname "$path")
while [ ! -d "$probe" ] && [ "$probe" != "/" ] && [ "$probe" != "." ]; do
  probe=$(dirname "$probe")
done
repo=$(~/.agent/bin/crew-repo-info.py --root "$probe" --field root 2>/dev/null || true)  # crew-lint: allow-swallow
[ -n "$repo" ] && repo=$(cd "$repo" && pwd -P)

[ -n "$repo" ] || hook_deny "Write blocked: $path is outside permitted worktrees."
case "$path" in "$repo"/*) hook_allow ;; esac
hook_deny "Write blocked: $path is outside $repo."
