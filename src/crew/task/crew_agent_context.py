#!/usr/bin/env python3
"""Print AGENTS.md guidance that applies to each target path, as JSON.

Per directory from the repository root to the target, AGENTS.md, else CLAUDE.md. Relative targets resolve against
the current directory. Each file's content appears once under "files"; targets list paths in root-to-nearest order.
`--kind` ranks each file's sections for that agent kind under its cap, and adds `kind` and `note` (what the cap
dropped). Logic: `task_guidance`, `task_guidance_kinds`.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from crew.task.task_guidance import collect, repo_root
from crew.task.task_guidance_kinds import kinds, narrow


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="+", type=Path)
    parser.add_argument("--root", type=Path)
    parser.add_argument("--kind", choices=kinds(), help="rank each file's sections for this agent kind, under its cap")
    args = parser.parse_args()
    try:
        root = repo_root(args.root)
    except (OSError, ValueError) as error:
        # Nothing on stdout: a caller's redirect then holds an empty file, which `crew-assemble-packages.py` refuses.
        parser.error(f"{str(error).strip()}; run from the reviewed repo's checkout, or pass --root <checkout>")

    record = collect(root, args.paths)
    if args.kind:
        relative = [os.path.relpath(path.resolve(), root) for path in args.paths]  # as guidance text names them
        record["files"], record["note"] = narrow(args.kind, record["files"], relative)
        record["kind"] = args.kind
    print(json.dumps(record, indent=2))
    if all("error" in target for target in record["targets"]):
        print("error: no target resolved", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
