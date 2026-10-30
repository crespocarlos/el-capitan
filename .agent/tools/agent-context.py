#!/usr/bin/env python3
"""Print AGENTS.md guidance that applies to each target path, as JSON.

Per directory from the repository root to the target, AGENTS.md is used; CLAUDE.md
only when that directory has no AGENTS.md. Relative targets resolve against the
current directory. Each file's content appears once under "files"; targets list
paths in root-to-nearest order.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


def repo_root(explicit: Path | None) -> Path:
    if explicit:
        return explicit.resolve()
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise ValueError(result.stderr.strip() or "not inside a git repository")
    return Path(result.stdout.strip()).resolve()


def guidance_for(root: Path, target: Path) -> list[Path]:
    resolved = target if target.is_absolute() else Path.cwd() / target
    directory = resolved if resolved.is_dir() else resolved.parent
    try:
        directory = directory.resolve()
        relative = directory.relative_to(root)
    except ValueError as error:
        raise ValueError(f"target is outside repository: {target}") from error

    ancestors = [root]
    current = root
    for part in relative.parts:
        current = current / part
        ancestors.append(current)

    result = []
    for ancestor in ancestors:
        agents = ancestor / "AGENTS.md"
        claude = ancestor / "CLAUDE.md"
        if agents.is_file():
            result.append(agents)
        elif claude.is_file():
            result.append(claude)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="+", type=Path)
    parser.add_argument("--root", type=Path)
    args = parser.parse_args()
    try:
        root = repo_root(args.root)
    except (OSError, ValueError) as error:
        parser.error(str(error))

    files: dict[str, str] = {}
    targets = []
    failed = 0
    for path in args.paths:
        try:
            guidance = guidance_for(root, path)
            for item in guidance:
                files.setdefault(
                    str(item), item.read_text(encoding="utf-8", errors="replace")
                )
            targets.append({"path": str(path), "guidance": [str(item) for item in guidance]})
        except (OSError, ValueError) as error:
            failed += 1
            targets.append({"path": str(path), "guidance": [], "error": str(error)})

    print(json.dumps({"root": str(root), "files": files, "targets": targets}, indent=2))
    if failed == len(args.paths):
        print("error: no target resolved", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
