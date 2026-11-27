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
# and `tempfile.gettempdir()` in every review tool writes there. Both are consulted because a caller
# may name either, and `mktemp` on Linux still uses `/tmp`.
#
# The temp root is allowed only for the pipeline's own directory, `crew-review-<repo>`, never
# wholesale: a repository checked out under `$TMPDIR` would otherwise escape its own boundary,
# because `<repo>/../outside.md` resolves to a path inside the temp root and a bare-prefix match
# would allow it. That is a fixture case, and it failed when this list used `$TMPDIR` alone.
for prefix in "$HOME/.agent" "$HOME/.claude" "$HOME/.cursor" "/tmp"; do
  resolved=$(resolve "$prefix") || continue
  [ -n "$resolved" ] || continue
  case "$path" in "$resolved"/*) hook_allow ;; esac
done

# A background job's own scratch directory, `<config dir>/jobs/<job>/tmp`, for every Claude config dir the
# install manifest records (~/.claude is allowed whole above). The job is one path segment and the path is
# already resolved, so `jobs/a/b/tmp` and `..` escapes do not match; the rest of such a config dir stays denied.
# A missing or unreadable manifest allows no job directory. Any agent may write the manifest (it is under
# ~/.agent), so an entry counts only when it resolves to a direct child of $HOME named `.claude*`.
manifest="$HOME/.agent/install-manifest.json"
config_dirs=$(jq -r '.config_dirs[]? | strings' "$manifest" 2>/dev/null) || config_dirs=""  # crew-lint: allow-swallow
home_dir=$(resolve "$HOME") || home_dir=""
while IFS= read -r config_dir; do
  [ -n "$config_dir" ] && [ -n "$home_dir" ] || continue
  resolved=$(resolve "$config_dir") || continue
  case "$resolved" in "$home_dir"/.claude*) ;; *) continue ;; esac
  case "${resolved#"$home_dir"/}" in */*) continue ;; esac
  case "$path" in "$resolved"/jobs/?*/tmp | "$resolved"/jobs/?*/tmp/*) ;; *) continue ;; esac
  job=${path#"$resolved"/jobs/}
  job=${job%%/*}
  case "${path#"$resolved"/jobs/"$job"}" in /tmp | /tmp/*) hook_allow ;; esac
done <<<"$config_dirs"

# The pipeline's scratch directory inside the temp root, matched as a glob rather than resolved:
# `realpath` keeps `crew-review-*` literal, so a prefix comparison could never match it. Only the
# directory the tools create is allowed, so a repository checked out elsewhere under `$TMPDIR`
# still cannot be escaped through `<repo>/../outside.md`.
temp_root=$(resolve "${TMPDIR:-/tmp}") || temp_root=""
if [ -n "$temp_root" ]; then
  case "$path" in "$temp_root"/crew-review-*/*) hook_allow ;; esac
fi

# Probe the nearest existing ancestor; a missing directory is not evidence of an escape. A failure
# here leaves `repo` empty, which the branch below reads as "outside permitted worktrees": refusing
# the write is the safe direction, so the call is allowed to fail.
probe=$(dirname "$path")
while [ ! -d "$probe" ] && [ "$probe" != "/" ] && [ "$probe" != "." ]; do
  probe=$(dirname "$probe")
done
repo=$(git -C "$probe" rev-parse --show-toplevel 2>/dev/null || true)  # crew-lint: allow-swallow
[ -n "$repo" ] && repo=$(cd "$repo" && pwd -P)

[ -n "$repo" ] || hook_deny "Write blocked: $path is outside permitted worktrees."
case "$path" in "$repo"/*) hook_allow ;; esac
hook_deny "Write blocked: $path is outside $repo."
