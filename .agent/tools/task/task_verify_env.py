"""What a verify run depends on besides the commands: the Node version, the tree, and the cache.

A gate result is reusable only when nothing it read has changed, so the cache key is the working
tree, the command, the environment the run mirrored, and the Node version it ran under. A result is
cached only when it passed: a failure is re-run, never replayed.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from pathlib import Path

from lib.git import GitError, output

NODE_HOMES = (".nvm/versions/node", ".local/share/fnm/node-versions", "Library/Application Support/fnm/node-versions",
              ".volta/tools/image/node", ".asdf/installs/nodejs")


def required_node(nvmrc: str) -> str:
    """The version `.nvmrc` names without a leading `v`; an alias such as `lts/*` comes back as is."""
    for line in nvmrc.splitlines():
        if line.strip() and not line.lstrip().startswith("#"):
            return line.strip().removeprefix("v")
    return ""


def version_tuple(name: str) -> tuple[int, ...]:
    return tuple(int(part) for part in re.findall(r"\d+", name))


def find_node_bin(required: str, home: Path | None = None) -> Path | None:
    """The `bin` directory of the newest installed Node matching `required`, or None."""
    if not re.match(r"^\d+(\.\d+){0,2}$", required):
        return None
    base = home or Path(os.environ.get("HOME", "~")).expanduser()
    found: list[tuple[tuple[int, ...], Path]] = []
    for relative in NODE_HOMES:
        root = base / relative
        for entry in root.glob("*") if root.is_dir() else []:
            version = entry.name.removeprefix("v")
            if version == required or version.startswith(required + "."):
                for bin_dir in (entry / "bin", entry / "installation" / "bin"):
                    if (bin_dir / "node").exists():
                        found.append((version_tuple(version), bin_dir))
    return max(found, key=lambda pair: pair[0])[1] if found else None


def node_version(path: str) -> str:
    """`node --version` under the given PATH, or `unavailable`."""
    try:
        done = subprocess.run(["node", "--version"], capture_output=True, text=True, timeout=20,
                              env={**os.environ, "PATH": path})
    except (OSError, subprocess.SubprocessError):
        return "unavailable"
    return done.stdout.strip() if done.returncode == 0 and done.stdout.strip() else "unavailable"


def node_env(pin: dict) -> tuple[dict, str]:
    """`({required, used, source}, PATH)`: the pinned Node when installed, else the PATH's own.

    With no pin (`source` is `none`) the PATH is left alone: a repo that names no Node is never forced onto one.
    """
    required = pin["required"]
    found = find_node_bin(required) if required else None
    path = f"{found}{os.pathsep}{os.environ.get('PATH', '')}" if found else os.environ.get("PATH", "")
    return {"required": required, "used": node_version(path), "source": pin["source"]}, path


def tree_key(root: Path) -> str:
    """The tree the gates would run on: HEAD's tree, hashed with the diff and untracked files if dirty."""
    tree = output(root, ["rev-parse", "HEAD^{tree}"]).strip()
    extra = hashlib.sha256(output(root, ["diff", "HEAD", "--binary"]).encode("utf-8", "replace"))
    dirty = bool(extra.digest() != hashlib.sha256(b"").digest())
    for path in sorted(output(root, ["ls-files", "--others", "--exclude-standard"]).splitlines()):
        target = root / path
        extra.update(path.encode() + (target.read_bytes() if target.is_file() else b""))
        dirty = True
    return hashlib.sha256(f"{tree}{extra.hexdigest()}".encode()).hexdigest() if dirty else tree


def cache_key(tree: str, command: str, env: dict[str, str], node: str) -> str:
    """The identity of one gate result: tree hash, command, env and Node version."""
    material = json.dumps([tree, command, sorted(env.items()), node])
    return hashlib.sha256(material.encode()).hexdigest()


def cache_dir(root: Path) -> Path:
    """Shared by every worktree of the repository, under git's common directory."""
    try:
        common = output(root, ["rev-parse", "--git-common-dir"]).strip()
    except GitError:
        return root / ".crew-verify-cache"
    return (root / common).resolve() / "crew-verify"


def cache_get(root: Path, key: str) -> dict | None:
    try:
        return json.loads((cache_dir(root) / f"{key}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def cache_put(root: Path, key: str, result: dict) -> None:
    directory = cache_dir(root)
    try:
        directory.mkdir(parents=True, exist_ok=True)
        (directory / f"{key}.json").write_text(json.dumps(result), encoding="utf-8")
    except OSError:
        pass
