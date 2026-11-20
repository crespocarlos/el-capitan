#!/usr/bin/env bash
# Print the default branch of a remote (default: origin). Order: local <remote>/HEAD ref,
# then `git remote show` (network). If both fail: `main` with a stderr warning, or exit 1
# with no output under --strict.
set -euo pipefail

strict=0
remote=origin
for arg in "$@"; do
  case "$arg" in
    --help)
      echo "usage: default-branch.sh [--strict] [remote]   (prints the remote's default branch; defaults to origin)"
      exit 0
      ;;
    --strict) strict=1 ;;
    -*)
      echo "default-branch.sh: unknown option: $arg" >&2
      exit 2
      ;;
    *) remote="$arg" ;;
  esac
done

ref=$(git symbolic-ref --quiet --short "refs/remotes/$remote/HEAD" 2>/dev/null || true)
if [ -n "$ref" ]; then
  echo "${ref#"$remote"/}"
  exit 0
fi

echo "default-branch.sh: querying '$remote' (local $remote/HEAD is unset)..." >&2
# LC_ALL=C keeps the "HEAD branch:" label untranslated.
branch=$(LC_ALL=C git remote show "$remote" 2>/dev/null | sed -n 's/^ *HEAD branch: *//p' | head -1 || true)
if [ -n "$branch" ] && [ "$branch" != "(unknown)" ] && [ "$branch" != "(not queried)" ]; then
  echo "$branch"
  exit 0
fi

if [ "$strict" = 1 ]; then
  exit 1
fi
echo "warning: default branch of '$remote' unknown; assuming main (run: git remote set-head $remote -a)" >&2
echo main
