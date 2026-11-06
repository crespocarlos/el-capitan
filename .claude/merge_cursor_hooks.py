#!/usr/bin/env python3
"""Merge a hook template into a Cursor hooks file (idempotent).

Usage: merge_cursor_hooks.py <template.json> <dest.json>

Entries whose command appears in the template are replaced by the template's
entry, so changed flags (failClosed, loop_limit, matcher) reach an existing
install. Every other entry is preserved, so user-registered hooks survive.
"""
import json
import os
import sys
import tempfile


def main() -> int:
    if len(sys.argv) != 3:
        print("usage: merge_cursor_hooks.py <template.json> <dest.json>", file=sys.stderr)
        return 2
    src, dst = sys.argv[1:]
    with open(src, encoding="utf-8") as f:
        template = json.load(f)
    if os.path.exists(dst):
        with open(dst, encoding="utf-8") as f:
            dest = json.load(f)
    else:
        dest = {"version": 1, "hooks": {}}
    hooks = dest.setdefault("hooks", {})
    for event, entries in template["hooks"].items():
        ours = {entry.get("command") for entry in entries}
        kept = [entry for entry in hooks.get(event, []) if entry.get("command") not in ours]
        hooks[event] = kept + [dict(entry) for entry in entries]
    descriptor, temporary = tempfile.mkstemp(dir=os.path.dirname(dst) or ".", text=True)
    with os.fdopen(descriptor, "w", encoding="utf-8") as f:
        json.dump(dest, f, indent=2)
        f.write("\n")
    os.replace(temporary, dst)
    return 0


if __name__ == "__main__":
    sys.exit(main())
