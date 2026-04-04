#!/usr/bin/env python3
"""Merge el-capitan hooks into an existing ~/.claude/settings.json (idempotent).

Usage: merge_claude_settings.py <src_settings.json> <dest_settings.json>

hooks is a dict keyed by event type (PreToolUse, PostToolUse, etc.).
Each value is an array of {matcher, hooks} entries. Merge per event type,
deduping by matcher so re-running install is idempotent.
"""
import json
import os
import sys


def main() -> None:
    if len(sys.argv) != 3:
        print("usage: merge_claude_settings.py <src> <dest>", file=sys.stderr)
        sys.exit(2)
    src_path, dest_path = sys.argv[1], sys.argv[2]
    with open(src_path, encoding="utf-8") as f:
        src = json.load(f)
    with open(dest_path, encoding="utf-8") as f:
        dest = json.load(f)

    src_hooks = src.get("hooks", {})
    dest_hooks = dest.get("hooks", {})
    for event_type, entries in src_hooks.items():
        if event_type not in dest_hooks:
            dest_hooks[event_type] = entries
        else:
            existing_matchers = {e.get("matcher", "") for e in dest_hooks[event_type]}
            for entry in entries:
                if entry.get("matcher", "") not in existing_matchers:
                    dest_hooks[event_type].append(entry)
    dest["hooks"] = dest_hooks
    for k, v in src.items():
        if k != "hooks" and k not in dest:
            dest[k] = v

    tmp = dest_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(dest, f, indent=2)
    os.rename(tmp, dest_path)
    print("  Merged ~/.claude/settings.json")


if __name__ == "__main__":
    main()
