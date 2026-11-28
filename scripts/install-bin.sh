#!/usr/bin/env bash
# Install a pinned release binary into DIR, checked against its published SHA-256: gitleaks (the credentials rule's
# scanner, install.sh) or shfmt (the hooks' optional parser; CI runs the hook tests through it).
# Usage: bash scripts/install-bin.sh gitleaks|shfmt DIR   (Linux or macOS, amd64 or arm64; needs curl)
set -euo pipefail
name=${1:?usage: install-bin.sh gitleaks|shfmt DIR}
dir=${2:?usage: install-bin.sh gitleaks|shfmt DIR}
case "$name:$(uname -s)/$(uname -m)" in
    shfmt:Linux/x86_64) asset=linux_amd64 sum=76e77641faa025814b77f153b29796b8e6fa2fca03e0c76a691608b86c7ea7bf ;;
    shfmt:Linux/aarch64 | shfmt:Linux/arm64) asset=linux_arm64 sum=5f2db09dae91fca848f7adbdd014632e921a383863a2ad7e0450ad3aba0c6489 ;;
    shfmt:Darwin/arm64) asset=darwin_arm64 sum=b7c872db63553ccffc7253aba3ed7d4885a27d83f1ba567b1138c6315a5847e5 ;;
    shfmt:Darwin/x86_64) asset=darwin_amd64 sum=d33eee0da0f92835b3562e9767a05cee7e4eaeef47daa03bfd09da17b4b590a6 ;;
    gitleaks:Linux/x86_64) asset=linux_x64 sum=551f6fc83ea457d62a0d98237cbad105af8d557003051f41f3e7ca7b3f2470eb ;;
    gitleaks:Linux/aarch64 | gitleaks:Linux/arm64) asset=linux_arm64 sum=e4a487ee7ccd7d3a7f7ec08657610aa3606637dab924210b3aee62570fb4b080 ;;
    gitleaks:Darwin/arm64) asset=darwin_arm64 sum=b40ab0ae55c505963e365f271a8d3846efbc170aa17f2607f13df610a9aeb6a5 ;;
    gitleaks:Darwin/x86_64) asset=darwin_x64 sum=dfe101a4db2255fc85120ac7f3d25e4342c3c20cf749f2c20a18081af1952709 ;;
    *) echo "install-bin.sh: no pinned $name for $(uname -s)/$(uname -m)" >&2; exit 2 ;;
esac
case "$name" in
    shfmt) url="https://github.com/mvdan/sh/releases/download/v3.14.1/shfmt_v3.14.1_$asset" ;;
    gitleaks) url="https://github.com/gitleaks/gitleaks/releases/download/v8.30.1/gitleaks_8.30.1_$asset.tar.gz" ;;
esac
mkdir -p "$dir"
tmp="$dir/.$name.download"
curl -fsSL --retry 3 -o "$tmp" "$url"
if command -v sha256sum >/dev/null 2>&1; then got=$(sha256sum "$tmp"); else got=$(shasum -a 256 "$tmp"); fi
if [ "${got%% *}" != "$sum" ]; then
    rm -f "$tmp"
    echo "install-bin.sh: checksum mismatch for $url" >&2
    exit 1
fi
if [ "$name" = gitleaks ]; then
    tar -xzf "$tmp" -C "$dir" gitleaks
    rm -f "$tmp"
    "$dir/gitleaks" version
else
    chmod +x "$tmp"
    mv "$tmp" "$dir/shfmt"
    "$dir/shfmt" --version
fi
