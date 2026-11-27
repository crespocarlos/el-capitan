#!/usr/bin/env python3
"""Merge el-capitan hooks into an existing ~/.claude/settings.json (idempotent).

Usage: merge_claude_settings.py <src_settings.json> <dest_settings.json> [--manifest <home>]

With `--manifest`, what the merge added (rules, hooks and keys the destination lacked) is recorded in
`<home>/.agent/install-manifest.json`; `uninstall.py` removes only that (`unmerge`).

hooks is a dict keyed by event type, with each value an array of
{matcher, hooks} entries. Merge per event type at the inner hook level:

- A hook whose command appears in the template takes the template's entry
  verbatim, so flag changes (failClosed, loop_limit, timeouts) reach an
  existing install.
- Every hook whose command is not in the template is preserved untouched.

Matcher is not a unique key (settings.json registers several matcher-less
entries per event), so entries are never replaced wholesale: that would
delete user hooks that share a matcher.

A retired hook — one this repository used to ship and has since merged or
removed — is dropped from the destination. Leaving it registered is worse
than a missing file: the guard fails closed, so a deleted script would deny
every command it used to inspect. The list and the match live in
`hooks_retirement.py`, shared with the Cursor merger.
"""
import json
import os
import sys
from pathlib import Path

import install_blocks
from hooks_retirement import retired
from install_blocks import write_json


def template_commands(entries):
    return {hook.get("command") for entry in entries for hook in entry.get("hooks", [])}


def merge_event(existing, incoming):
    ours = template_commands(incoming)
    kept = []
    for entry in existing:
        remaining = []
        for hook in entry.get("hooks", []):
            if hook.get("command") in ours:
                continue
            if retired(hook.get("command")):
                print(f"  Retiring hook registration: {hook.get('command')}")
                continue
            remaining.append(hook)
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


def rule_command(rule):
    """The command a `Bash(...)` rule names, or None for a rule of another tool.

    A rule is `Bash(<command> *)`, and the command may contain spaces, so the prefix is everything
    before the trailing wildcard. This is the identity used to decide whether the template owns a
    rule: the same command must not end up in both `allow` and `ask`, which is the collision that
    makes a permission decision depend on evaluation order.
    """
    if not isinstance(rule, str) or not rule.startswith("Bash(") or not rule.endswith(")"):
        return None
    body = rule[len("Bash("):-1]
    return body[:-2] if body.endswith(" *") else body.rstrip(":*")


def rule_scope(rule):
    """(tool, glob) for a path-scoped rule such as `Write(~/.agent/tasks/**)`, else None."""
    if not isinstance(rule, str) or "(" not in rule or not rule.endswith(")"):
        return None
    tool, _, scope = rule[:-1].partition("(")
    if tool.startswith("Bash") or not scope:
        return None
    return tool, scope


def superseded(existing, incoming):
    """True when `incoming` narrows `existing`: same tool, and a scope inside the same glob prefix.

    Narrowing must retire the broader rule. Merging them additively leaves `**` beside `*/SPEC.md`,
    and the broader one still matches everything, so the install would report a fix that changes
    nothing — the defect this reconciliation exists to prevent.

    The comparison strips the wildcard portion rather than taking the parent directory: `tasks/**`
    and `tasks/*/SPEC.md` have different parents (`tasks` and `tasks/*`) but share the prefix
    `tasks/`, which is what makes one a narrowing of the other.
    """
    old, new = rule_scope(existing), rule_scope(incoming)
    if not old or not new or old[0] != new[0]:
        return False
    if not old[1].endswith("/**") or new[1].endswith("/**"):
        return False
    shared = old[1][:-len("/**")]
    return new[1].startswith(shared + "/")


def merge_permissions(dest, src):
    """Reconcile the three permission lists, template rules winning for the commands it names.

    `allow` and `ask` are merged rather than replaced so a user's own rules survive; a template rule
    for a command the destination lists elsewhere is moved to the template's list, because two lists
    claiming one command is the defect this exists to prevent. `deny` is additive: nothing is ever
    un-denied by an install.
    """
    dest_perm = dest.setdefault("permissions", {})
    src_perm = src.get("permissions", {})
    changed = []
    for name in ("allow", "ask"):
        incoming = src_perm.get(name, [])
        owned = {rule_command(rule) for rule in incoming} - {None}
        existing = [rule for rule in dest_perm.get(name, []) if rule_command(rule) not in owned]
        narrowed = [rule for rule in existing if any(superseded(rule, new) for new in incoming)]
        if narrowed:
            existing = [rule for rule in existing if rule not in narrowed]
            for rule in narrowed:
                replacement = next(new for new in incoming if superseded(rule, new))
                print(f"  permissions: {rule} -> {replacement}")
        for other in ("allow", "ask"):
            if other == name:
                continue
            before = dest_perm.get(other, [])
            after = [rule for rule in before if rule_command(rule) not in owned]
            if len(after) != len(before):
                dest_perm[other] = after
                changed.extend(f"moved from {other}: {rule}" for rule in before if rule not in after)
        merged = list(dict.fromkeys(existing + incoming))
        if merged != dest_perm.get(name, []):
            dest_perm[name] = merged
    for rule in src_perm.get("deny", []):
        if rule not in dest_perm.setdefault("deny", []):
            dest_perm["deny"].append(rule)
    for note in changed:
        print(f"  permissions: {note}")
    return dest


def hook_dicts(hooks):
    """{(event, command): hook} of every registration in a `hooks` object (first wins), odd shapes skipped."""
    found = {}
    for event, entries in hooks.items() if isinstance(hooks, dict) else []:
        for entry in entries if isinstance(entries, list) else []:
            inner = entry.get("hooks") if isinstance(entry, dict) else None
            for hook in inner if isinstance(inner, list) else []:
                if isinstance(hook, dict):
                    found.setdefault((event, hook.get("command")), hook)
    return found


def hook_ids(hooks):
    """(event, command) of every registration in a `hooks` object, skipping shapes the merge never writes."""
    return set(hook_dicts(hooks))


def held_rules(data):
    """Every rule string in any permission list of a settings document."""
    permissions = data.get("permissions") if isinstance(data.get("permissions"), dict) else {}
    return {rule for rules in permissions.values() if isinstance(rules, list)
            for rule in rules if isinstance(rule, str)}


def added(before, src, created):
    """What a merge of `src` into `before` adds that `before` lacked, and the template entries it already held.

    A rule the destination held in any list, or a hook it registered under the same event, is the
    user's even when the template has it too, so it is never recorded and an uninstall keeps it; a key
    the template's copy of such a hook adds (`onFailure`) is recorded in `hook_keys` and taken back.
    """
    permissions = before.get("permissions") if isinstance(before.get("permissions"), dict) else {}
    held = held_rules(before)
    template_rules = src.get("permissions", {})
    hooks, theirs, ours = before.get("hooks"), hook_dicts(before.get("hooks")), hook_dicts(src.get("hooks", {}))
    keys = [[event, command, key] for (event, command), hook in ours.items()
            if (event, command) in theirs for key in hook if key not in theirs[(event, command)]]
    record = {"created": created,
              "keys": [key for key in src if key not in before],
              "lists": [name for name in template_rules if name not in permissions],
              "events": [event for event in src.get("hooks", {}) if not isinstance(hooks, dict) or event not in hooks],
              "rules": {name: [r for r in rules if r not in held] for name, rules in template_rules.items()
                        if any(r not in held for r in rules)},
              "hooks": sorted([list(pair) for pair in set(ours) - set(theirs)]),
              "hook_keys": sorted(keys)}
    present = {"rules": {name: [r for r in rules if r in held] for name, rules in template_rules.items()
                         if any(r in held for r in rules)},
               "hooks": sorted([list(pair) for pair in set(ours) & set(theirs)])}
    return record, present


def unmerge(dest, recorded, src, warn):
    """`dest` without what install recorded as added (`added`); every other entry is the user's and stays.

    A key goes only while it still equals the template's value; a list, event or key install created goes
    once empty. A shape the merge never writes is skipped with a `warn` line, never an error.
    """
    drop_hooks(dest.get("hooks"), recorded, warn)
    template = hook_dicts(src.get("hooks", {}))
    for (event, command), hook in hook_dicts(dest.get("hooks")).items():
        for _, _, key in [k for k in recorded.get("hook_keys", []) if (k[0], k[1]) == (event, command)]:
            if key in hook and hook[key] == template.get((event, command), {}).get(key):
                del hook[key]
    permissions = dest.get("permissions")
    for name, rules in recorded.get("rules", {}).items():
        current = permissions.get(name) if isinstance(permissions, dict) else None
        if current is None:
            continue
        if not isinstance(current, list):
            warn(f"permissions.{name} is not a list; left as it is")
            continue
        permissions[name] = [rule for rule in current if rule not in rules]
        if not permissions[name] and name in recorded.get("lists", []):
            del permissions[name]
    for key in recorded.get("keys", []):
        if key in ("hooks", "permissions"):
            if dest.get(key) in ({}, None):
                dest.pop(key, None)
        elif key in dest and dest[key] == src.get(key):
            del dest[key]
    return dest


def drop_hooks(hooks, recorded, warn):
    """Remove the recorded (event, command) registrations from a `hooks` object in place."""
    ours = {tuple(pair) for pair in recorded.get("hooks", [])}
    for event in list(hooks) if isinstance(hooks, dict) else []:
        if not any(event == e for e, _ in ours):
            continue
        entries = hooks[event]
        if not isinstance(entries, list):
            warn(f"hooks.{event} is not a list; left as it is")
            continue
        kept = []
        for entry in entries:
            inner = entry.get("hooks") if isinstance(entry, dict) else None
            if not isinstance(inner, list):
                warn(f"an entry of hooks.{event} is not an object with a hooks list; left as it is")
                kept.append(entry)
                continue
            left = [h for h in inner if not (isinstance(h, dict) and (event, h.get("command")) in ours)]
            if left or not inner:
                kept.append(entry if len(left) == len(inner) else {**entry, "hooks": left})
        hooks[event] = kept
        if not kept and event in recorded.get("events", []):
            del hooks[event]


def main() -> int:
    arguments = sys.argv[1:]
    manifest_home = None
    if arguments[2:3] == ["--manifest"] and len(arguments) == 4:
        manifest_home, arguments = arguments[3], arguments[:2]
    if len(arguments) != 2:
        print("usage: merge_claude_settings.py <src> <dest> [--manifest <home>]", file=sys.stderr)
        return 2
    src_path, dest_path = arguments
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
    if not isinstance(dest, dict):
        print(f"merge_claude_settings: {dest_path} is not a JSON object", file=sys.stderr)
        return 2
    record, present = added(json.loads(original) if original else {}, src, not os.path.exists(dest_path))

    dest_hooks = dest.setdefault("hooks", {})
    for event_type, entries in src.get("hooks", {}).items():
        dest_hooks[event_type] = merge_event(dest_hooks.get(event_type, []), entries)
    # An event the template dropped can still hold a retired registration; one left empty goes.
    for event_type in [e for e in dest_hooks if e not in src.get("hooks", {})]:
        dest_hooks[event_type] = merge_event(dest_hooks[event_type], [])
        if not dest_hooks[event_type]:
            del dest_hooks[event_type]

    merge_permissions(dest, src)

    for key, value in src.items():
        if key not in ("hooks", "permissions") and key not in dest:
            dest[key] = value

    try:
        if original:
            install_blocks.backup(Path(dest_path), original)
        write_json(dest, Path(dest_path))
        if manifest_home:
            install_blocks.record(Path(manifest_home), "claude_settings", record, present)
    except (OSError, install_blocks.ManifestError) as error:
        print(f"merge_claude_settings: cannot write {dest_path} or its install record: {error}", file=sys.stderr)
        return 2
    print(f"  Merged {dest_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
