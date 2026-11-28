#!/usr/bin/env python3
"""Print AGENTS.md guidance that applies to each target path, as JSON.

Per directory from the repository root to the target, AGENTS.md is used; CLAUDE.md
only when that directory has no AGENTS.md. Relative targets resolve against the
current directory. Each file's content appears once under "files"; targets list
paths in root-to-nearest order. Logic: `task_guidance`.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import task_bootstrap  # noqa: F401

from task_guidance import collect, repo_root


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="+", type=Path)
    parser.add_argument("--root", type=Path)
    args = parser.parse_args()
    try:
        root = repo_root(args.root)
    except (OSError, ValueError) as error:
        # Nothing on stdout: a caller's redirect then holds an empty file, which `crew-assemble-packages.py` refuses.
        parser.error(f"{str(error).strip()}; run from the reviewed repo's checkout, or pass --root <checkout>")

    record = collect(root, args.paths)
    print(json.dumps(record, indent=2))
    if all("error" in target for target in record["targets"]):
        print("error: no target resolved", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
