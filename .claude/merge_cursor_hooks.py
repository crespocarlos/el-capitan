#!/usr/bin/env python3
"""Merge a hook template into a Cursor hooks file (idempotent).

Usage: merge_cursor_hooks.py <template.json> <dest.json> [--manifest <home>]

Entries whose command appears in the template are replaced by the template's
entry, so changed flags (failClosed, loop_limit, matcher) reach an existing
install. Every other entry is preserved, so user-registered hooks survive —
except a retired script this repository no longer ships, which is dropped so
a fail-closed guard cannot deny every command after its file is deleted.

With `--manifest`, the (event, command) pairs and keys the destination lacked are
recorded in `<home>/.agent/install-manifest.json`; `uninstall.py` removes only
those (`unmerge`). An existing file is first copied to `<dest>.bak.<epoch>`.
"""

import json
import os
import shutil
import sys
from pathlib import Path

import install_blocks
from hooks_retirement import retired
from install_blocks import write_json


def entries_by_pair(hooks) -> dict:
    """{(event, command): entry} of a `hooks` object (first wins), skipping shapes the merge never writes."""
    found = {}
    for event, entries in hooks.items() if isinstance(hooks, dict) else []:
        for entry in entries if isinstance(entries, list) else []:
            if isinstance(entry, dict):
                found.setdefault((event, entry.get("command")), entry)
    return found


def pairs(hooks) -> set:
    """(event, command) of every entry in a `hooks` object, skipping shapes the merge never writes."""
    return set(entries_by_pair(hooks))


def added(before: dict, template: dict, created: bool) -> tuple:
    """What merging `template` into `before` adds that `before` lacked, and the template entries it already held.

    A key the template's copy of a user's own entry adds (`failClosed`) is recorded in `hook_keys`.
    """
    hooks = before.get("hooks")
    theirs, ours = entries_by_pair(hooks), entries_by_pair(template["hooks"])
    keys = [
        [event, command, key] for (event, command), entry in ours.items() if (event, command) in theirs for key in entry if key not in theirs[(event, command)]
    ]
    record = {
        "created": created,
        "keys": [key for key in ("version", "hooks") if key not in before],
        "events": [event for event in template["hooks"] if not isinstance(hooks, dict) or event not in hooks],
        "hooks": sorted([list(pair) for pair in set(ours) - set(theirs)]),
        "hook_keys": sorted(keys),
    }
    return record, {"hooks": sorted([list(pair) for pair in set(ours) & set(theirs)])}


def unmerge(dest: dict, recorded: dict, template: dict, warn) -> dict:
    """`dest` without the recorded entries and keys; what install created goes once empty, odd shapes stay."""
    ours = {tuple(pair) for pair in recorded.get("hooks", [])}
    hooks = dest.get("hooks")
    shipped = entries_by_pair(template["hooks"])
    for (event, command), entry in entries_by_pair(hooks).items():
        for _, _, key in [k for k in recorded.get("hook_keys", []) if (k[0], k[1]) == (event, command)]:
            if key in entry and entry[key] == shipped.get((event, command), {}).get(key):
                del entry[key]
    for event in list(hooks) if isinstance(hooks, dict) else []:
        if not any(event == e for e, _ in ours):
            continue
        if not isinstance(hooks[event], list):
            warn(f"hooks.{event} is not a list; left as it is")
            continue
        odd = [entry for entry in hooks[event] if not isinstance(entry, dict)]
        if odd:
            warn(f"{len(odd)} entry(ies) of hooks.{event} are not objects; left as they are")
        hooks[event] = [entry for entry in hooks[event] if not (isinstance(entry, dict) and (event, entry.get("command")) in ours)]
        if not hooks[event] and event in recorded.get("events", []):
            del hooks[event]
    if "hooks" in recorded.get("keys", []) and hooks in ({}, None):
        dest.pop("hooks", None)
        if "version" in recorded.get("keys", []) and dest.get("version") == 1:
            del dest["version"]
    return dest


def fail_open_without_jq(template: dict) -> None:
    """Without `jq` on PATH every guard fails before it can answer, and a `failClosed` guard then blocks every Cursor
    call, the ones that would install jq included: register them `failClosed: false` and say so in one line."""
    if shutil.which("jq"):
        return
    closed = [entry for entries in template["hooks"].values() for entry in entries if entry.get("failClosed") is True]
    for entry in closed:
        entry["failClosed"] = False
    if closed:
        print(
            f"  WARNING: jq is not on PATH: {len(closed)} Cursor guards registered failClosed: false (they would block every call); install jq and re-run install.sh"
        )


def main() -> int:
    arguments = sys.argv[1:]
    manifest_home = None
    if arguments[2:3] == ["--manifest"] and len(arguments) == 4:
        manifest_home, arguments = arguments[3], arguments[:2]
    if len(arguments) != 2:
        print("usage: merge_cursor_hooks.py <template.json> <dest.json> [--manifest <home>]", file=sys.stderr)
        return 2
    src, dst = arguments
    try:
        with open(src, encoding="utf-8") as f:
            template = json.load(f)
        if os.path.exists(dst):
            with open(dst, encoding="utf-8") as f:
                before = json.load(f)
        else:
            before = {}
    except (OSError, ValueError) as error:
        print(f"merge_cursor_hooks: cannot read {src} or {dst}: {error}", file=sys.stderr)
        return 2
    if not isinstance(before, dict) or not isinstance(before.get("hooks", {}), dict):
        print(f"merge_cursor_hooks: {dst} is not a JSON object with a hooks object", file=sys.stderr)
        return 2
    fail_open_without_jq(template)
    record, present = added(before, template, not os.path.exists(dst))
    dest = json.loads(json.dumps(before)) if before else {"version": 1, "hooks": {}}
    hooks = dest.setdefault("hooks", {})
    # Every event, the template's and the ones it dropped: a retired registration can sit in either.
    for event in list(dict.fromkeys([*template["hooks"], *hooks])):
        entries = template["hooks"].get(event, [])
        ours = {entry.get("command") for entry in entries}
        kept = []
        for entry in hooks.get(event, []):
            if entry.get("command") in ours:
                continue
            if retired(entry.get("command")):
                print(f"  Retiring hook registration: {entry.get('command')}")
                continue
            kept.append(entry)
        hooks[event] = kept + [dict(entry) for entry in entries]
        if not hooks[event] and event not in template["hooks"]:
            del hooks[event]
    try:
        if os.path.exists(dst):
            install_blocks.backup(Path(dst), Path(dst).read_text(encoding="utf-8"))
        write_json(dest, Path(dst))
        if manifest_home:
            install_blocks.record(Path(manifest_home), "cursor_hooks", record, present)
    except (OSError, install_blocks.ManifestError) as error:
        print(f"merge_cursor_hooks: cannot write {dst} or its install record: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
