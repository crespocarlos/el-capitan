#!/usr/bin/env python3
"""Merge el-capitan hooks into an existing ~/.claude/settings.json (idempotent).

Usage: merge_claude_settings.py <src_settings.json> <dest_settings.json>

hooks is a dict keyed by event type, with each value an array of
{matcher, hooks} entries. Merge per event type at the inner hook level:

- A hook whose command appears in the template takes the template's entry
  verbatim, so flag changes (failClosed, loop_limit, timeouts) reach an
  existing install.
- Every hook whose command is not in the template is preserved untouched.

Matcher is not a unique key (settings.json registers several matcher-less
entries per event), so entries are never replaced wholesale: that would
delete user hooks that share a matcher.
"""
import json
import os
import sys
import tempfile
import time


def template_commands(entries):
    return {hook.get("command") for entry in entries for hook in entry.get("hooks", [])}


def merge_event(existing, incoming):
    ours = template_commands(incoming)
    kept = []
    for entry in existing:
        remaining = [h for h in entry.get("hooks", []) if h.get("command") not in ours]
        if remaining:
            kept.append({**entry, "hooks": remaining})
    seen, appended = set(), []
    for entry in incoming:
        # The template may list one command under several matchers; register it once.
        unique = [h for h in entry.get("hooks", []) if h.get("command") not in seen]
        if unique:
            seen.update(h.get("command") for h in unique)
            appended.append({**entry, "hooks": unique})
    return kept + appended


def main() -> int:
    if len(sys.argv) != 3:
        print("usage: merge_claude_settings.py <src> <dest>", file=sys.stderr)
        return 2
    src_path, dest_path = sys.argv[1], sys.argv[2]
    try:
        with open(src_path, encoding="utf-8") as f:
            src = json.load(f)
    except (OSError, json.JSONDecodeError) as error:
        print(f"merge_claude_settings: cannot read template: {error}", file=sys.stderr)
        return 2

    original = ""
    if os.path.exists(dest_path):
        try:
            with open(dest_path, encoding="utf-8") as f:
                original = f.read()
            dest = json.loads(original)
        except (OSError, json.JSONDecodeError) as error:
            print(f"merge_claude_settings: cannot read {dest_path}: {error}", file=sys.stderr)
            return 2
    else:
        dest = {}

    dest_hooks = dest.setdefault("hooks", {})
    for event_type, entries in src.get("hooks", {}).items():
        dest_hooks[event_type] = merge_event(dest_hooks.get(event_type, []), entries)

    for key, value in src.items():
        if key != "hooks" and key not in dest:
            dest[key] = value

    if original:
        backup = f"{dest_path}.bak.{int(time.time())}"
        with open(backup, "w", encoding="utf-8") as f:
            f.write(original)

    descriptor, temporary = tempfile.mkstemp(dir=os.path.dirname(dest_path) or ".",
                                             prefix=".settings-")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as f:
            f.write(json.dumps(dest, indent=2) + "\n")
        os.replace(temporary, dest_path)
    except OSError as error:
        print(f"merge_claude_settings: cannot write {dest_path}: {error}", file=sys.stderr)
        return 2
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    print(f"  Merged {dest_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
