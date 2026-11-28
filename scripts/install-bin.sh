#!/usr/bin/env bash
# Install the pinned gitleaks release binary (the credentials rule's scanner) into DIR, checked against its published
# SHA-256. shfmt comes from the `shfmt-py` wheel in the venv instead; gitleaks has no vetted PyPI package.
# Usage: bash scripts/install-bin.sh gitleaks DIR   (Linux or macOS, amd64 or arm64; needs curl)
set -euo pipefail
name=${1:?usage: install-bin.sh gitleaks DIR}
dir=${2:?usage: install-bin.sh gitleaks DIR}
case "$name:$(uname -s)/$(uname -m)" in
    gitleaks:Linux/x86_64) asset=linux_x64 sum=551f6fc83ea457d62a0d98237cbad105af8d557003051f41f3e7ca7b3f2470eb ;;
    gitleaks:Linux/aarch64 | gitleaks:Linux/arm64) asset=linux_arm64 sum=e4a487ee7ccd7d3a7f7ec08657610aa3606637dab924210b3aee62570fb4b080 ;;
    gitleaks:Darwin/arm64) asset=darwin_arm64 sum=b40ab0ae55c505963e365f271a8d3846efbc170aa17f2607f13df610a9aeb6a5 ;;
    gitleaks:Darwin/x86_64) asset=darwin_x64 sum=dfe101a4db2255fc85120ac7f3d25e4342c3c20cf749f2c20a18081af1952709 ;;
    *) echo "install-bin.sh: no pinned $name for $(uname -s)/$(uname -m)" >&2; exit 2 ;;
esac
url="https://github.com/gitleaks/gitleaks/releases/download/v8.30.1/gitleaks_8.30.1_$asset.tar.gz"
mkdir -p "$dir"
tmp="$dir/.$name.download"
curl -fsSL --retry 3 -o "$tmp" "$url"
if command -v sha256sum >/dev/null 2>&1; then got=$(sha256sum "$tmp"); else got=$(shasum -a 256 "$tmp"); fi
if [ "${got%% *}" != "$sum" ]; then
    rm -f "$tmp"
    echo "install-bin.sh: checksum mismatch for $url" >&2
    exit 1
fi
tar -xzf "$tmp" -C "$dir" gitleaks
rm -f "$tmp"
"$dir/gitleaks" version
