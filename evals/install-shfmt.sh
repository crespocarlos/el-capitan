#!/usr/bin/env bash
# Install the pinned shfmt release binary into DIR, checked against its published SHA-256, so CI runs
# the hooks' shfmt parser path (the hook tests also run the awk path by hiding shfmt from PATH).
# Usage: bash evals/install-shfmt.sh DIR   (Linux or macOS, amd64 or arm64; needs curl)
set -euo pipefail
version=3.14.1
dir=${1:?usage: install-shfmt.sh DIR}
case "$(uname -s)/$(uname -m)" in
    Linux/x86_64) asset=linux_amd64 sum=76e77641faa025814b77f153b29796b8e6fa2fca03e0c76a691608b86c7ea7bf ;;
    Linux/aarch64 | Linux/arm64) asset=linux_arm64 sum=5f2db09dae91fca848f7adbdd014632e921a383863a2ad7e0450ad3aba0c6489 ;;
    Darwin/arm64) asset=darwin_arm64 sum=b7c872db63553ccffc7253aba3ed7d4885a27d83f1ba567b1138c6315a5847e5 ;;
    Darwin/x86_64) asset=darwin_amd64 sum=d33eee0da0f92835b3562e9767a05cee7e4eaeef47daa03bfd09da17b4b590a6 ;;
    *) echo "install-shfmt.sh: no pinned shfmt for $(uname -s)/$(uname -m)" >&2; exit 2 ;;
esac
mkdir -p "$dir"
tmp="$dir/.shfmt.download"
curl -fsSL --retry 3 -o "$tmp" "https://github.com/mvdan/sh/releases/download/v$version/shfmt_v${version}_$asset"
if command -v sha256sum >/dev/null 2>&1; then got=$(sha256sum "$tmp"); else got=$(shasum -a 256 "$tmp"); fi
if [ "${got%% *}" != "$sum" ]; then
    rm -f "$tmp"
    echo "install-shfmt.sh: checksum mismatch for shfmt_v${version}_$asset" >&2
    exit 1
fi
chmod +x "$tmp"
mv "$tmp" "$dir/shfmt"
"$dir/shfmt" --version
