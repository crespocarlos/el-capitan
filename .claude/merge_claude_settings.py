#!/usr/bin/env python3
"""Merge el-capitan hooks into an existing ~/.claude/settings.json (idempotent).

Usage: merge_claude_settings.py <src_template.json> <dest_settings.json> [--manifest <home>] [--auto-memory-off]

The source is `.claude/settings.template.json`; the checkout's own `.claude/settings.json` is its project
settings and carries no hooks.

`autoMemoryEnabled: false` (`AUTO_MEMORY_OFF`, not in the template) is merged only with `--auto-memory-off`,
which install passes once the dir's Claude memory entries are in crew memory; a value the destination holds
is never changed, and uninstall removes the key only while it is still false.

With `--manifest`, what the merge added (rules, hooks and keys the destination lacked) is recorded in
`<home>/.agent/install-manifest.json`, under the destination's config dir (`install_blocks.settings_section`);
`uninstall.py` removes only that (`unmerge`). A rule an earlier install recorded and the template has since
dropped is removed on the next install (`retire_rules`) and forgotten by the manifest; a user's own copy,
never recorded, stays.

hooks is a dict keyed by event type, with each value an array of
{matcher, hooks} entries. Merge per event type at the inner hook level:

- A hook whose command appears in the template takes the template's entry
  verbatim, so flag changes (failClosed, loop_limit, timeouts) reach an
  existing install.
- Every hook whose command is not in the template is preserved untouched.

Matcher is not a unique key (the template registers several matcher-less
entries per event), so entries are never replaced wholesale: that would
delete user hooks that share a matcher.

A retired hook — one this repository used to ship and has since merged or
removed — is dropped from the destination. Leaving it registered is worse
than a missing file: the guard fails closed, so a deleted script would deny
every command it used to inspect. The list and the match live in
`hooks_retirement.py`, shared with the Cursor merger.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import install_blocks
from hooks_retirement import retired
from install_blocks import write_json

# Written by install, not carried in the template: install turns auto-memory off in a config dir only once
# that dir's Claude memory entries are imported, and a template key would turn it off before any migration.
AUTO_MEMORY_OFF = {"autoMemoryEnabled": False}


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
    body = rule[len("Bash(") : -1]
    return body[:-2] if body.endswith(" *") else body.rstrip(":*")


def same_rule(rule):
    """A rule in one spelling: the legacy `Bash(X:*)` is the template's `Bash(X *)`."""
    if isinstance(rule, str) and rule.startswith("Bash(") and rule.endswith(":*)"):
        return f"{rule[:-3]} *)"
    return rule


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
    shared = old[1][: -len("/**")]
    return new[1].startswith(shared + "/")


def merge_permissions(dest, src):
    """Reconcile the three permission lists, template rules winning for the commands it names.

    `allow` and `ask` are merged rather than replaced so a user's own rules survive; a template rule
    for a command the destination lists elsewhere is moved to the template's list, because two lists
    claiming one command is the defect this exists to prevent. `deny` is additive: nothing is ever
    un-denied by an install. `additionalDirectories` is additive too, and `added` records only the
    directories the destination lacked, so an uninstall keeps the user's own.
    """
    dest_perm = dest.setdefault("permissions", {})
    src_perm = src.get("permissions", {})
    changed = []
    for name in ("allow", "ask"):
        template = src_perm.get(name, [])
        spelled = {same_rule(rule) for rule in template}
        held = {same_rule(rule) for rule in dest_perm.get(name, [])}
        # A rule the user already holds in another spelling keeps the user's spelling, and is not added twice.
        incoming = [rule for rule in template if same_rule(rule) not in held]
        owned = {rule_command(rule) for rule in template} - {None}
        existing = [rule for rule in dest_perm.get(name, []) if rule_command(rule) not in owned or same_rule(rule) in spelled]
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
    for name in ("deny", "additionalDirectories"):
        for rule in src_perm.get(name, []):
            if rule not in dest_perm.setdefault(name, []):
                dest_perm[name].append(rule)
    for note in changed:
        print(f"  permissions: {note}")
    return dest


def retire_rules(dest, recorded, src):
    """Drop from `dest` the rules an earlier install added (`recorded`) that the template no longer has.

    A rule the user held before that install was never recorded, so it stays; a list install created
    goes once empty. Returns {list: [rule, ...]} of what was dropped, for the manifest to forget.
    """
    permissions = dest.get("permissions")
    template = src.get("permissions", {})
    dropped = {}
    if not isinstance(permissions, dict) or not isinstance(recorded, dict):
        return dropped
    for name, rules in (recorded.get("rules") or {}).items():
        current = permissions.get(name)
        if not isinstance(current, list) or not isinstance(rules, list):
            continue
        gone = [rule for rule in rules if rule in current and rule not in template.get(name, [])]
        if not gone:
            continue
        permissions[name] = [rule for rule in current if rule not in gone]
        dropped[name] = gone
        for rule in gone:
            print(f"  permissions: retired {name} rule {rule}")
        if not permissions[name] and name in recorded.get("lists", []):
            del permissions[name]
    return dropped


def retire_recorded(manifest_home, dest_path, dest, src):
    """(manifest section, rules dropped) for a merge recorded under `manifest_home`; (None, {}) without one."""
    if not manifest_home:
        return None, {}
    section = install_blocks.settings_section(Path(manifest_home), Path(dest_path).parent)
    recorded = (install_blocks.load_manifest(Path(manifest_home)) or {}).get(section)
    return section, retire_rules(dest, recorded, src)


def forget(home: Path, section: str, dropped: dict) -> None:
    """Remove the retired rules from the manifest's record, so a later rule of the user's spelled the same is theirs."""
    manifest = install_blocks.load_manifest(home)
    recorded = (manifest or {}).get(section)
    if not dropped or not isinstance(recorded, dict) or not isinstance(recorded.get("rules"), dict):
        return
    for name, gone in dropped.items():
        kept = [rule for rule in recorded["rules"].get(name, []) if rule not in gone]
        if kept:
            recorded["rules"][name] = kept
        else:
            recorded["rules"].pop(name, None)
    write_json(manifest, home / install_blocks.MANIFEST)


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
    return {rule for rules in permissions.values() if isinstance(rules, list) for rule in rules if isinstance(rule, str)}


def added(before, src, created):
    """What a merge of `src` into `before` adds that `before` lacked, and the template entries it already held.

    A rule the destination held in any list, or a hook it registered under the same event, is the
    user's even when the template has it too, so it is never recorded and an uninstall keeps it; a key
    the template's copy of such a hook adds (`onFailure`) is recorded in `hook_keys` and taken back.
    """
    permissions = before.get("permissions") if isinstance(before.get("permissions"), dict) else {}
    held = {same_rule(rule) for rule in held_rules(before)}
    template_rules = src.get("permissions", {})
    hooks, theirs, ours = before.get("hooks"), hook_dicts(before.get("hooks")), hook_dicts(src.get("hooks", {}))
    keys = [
        [event, command, key] for (event, command), hook in ours.items() if (event, command) in theirs for key in hook if key not in theirs[(event, command)]
    ]
    record = {
        "created": created,
        "keys": [key for key in src if key not in before],
        "lists": [name for name in template_rules if name not in permissions],
        "events": [event for event in src.get("hooks", {}) if not isinstance(hooks, dict) or event not in hooks],
        "rules": {
            name: [r for r in rules if same_rule(r) not in held] for name, rules in template_rules.items() if any(same_rule(r) not in held for r in rules)
        },
        "hooks": sorted([list(pair) for pair in set(ours) - set(theirs)]),
        "hook_keys": sorted(keys),
    }
    present = {
        "rules": {name: [r for r in rules if same_rule(r) in held] for name, rules in template_rules.items() if any(same_rule(r) in held for r in rules)},
        "hooks": sorted([list(pair) for pair in set(ours) & set(theirs)]),
    }
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
        elif key in dest and dest[key] == {**AUTO_MEMORY_OFF, **src}.get(key):
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


def expand_dirs(src, home):
    """`src` with each `~/` entry of `permissions.additionalDirectories` written as an absolute path under `home`.

    Claude Code's docs do not say that `~` is expanded in that key, so install writes the path itself; the
    manifest records the expanded string, and uninstall expands the template the same way to match it.
    """
    permissions = src.get("permissions") if isinstance(src, dict) else None
    dirs = permissions.get("additionalDirectories") if isinstance(permissions, dict) else None
    if not isinstance(dirs, list):
        return src
    expanded = [f"{home}/{d[2:]}" if isinstance(d, str) and d.startswith("~/") else d for d in dirs]
    return {**src, "permissions": {**permissions, "additionalDirectories": expanded}}


def read_template(src_path: str, auto_memory_off: bool) -> dict:
    """The template, plus `AUTO_MEMORY_OFF` when install found no Claude memory entry left to import, with its
    directories expanded under $HOME (`expand_dirs`)."""
    with open(src_path, encoding="utf-8") as f:
        src = json.load(f)
    if auto_memory_off and isinstance(src, dict):
        src = {**AUTO_MEMORY_OFF, **src}
    return expand_dirs(src, os.path.expanduser("~"))


class MergeError(Exception):
    """A merge that cannot proceed; its message is the one stderr line, and the exit is 2."""


def parse_arguments(argv: list[str]) -> tuple[str, str, str | None, bool]:
    """(src, dest, manifest home or None, auto-memory-off) from the command line, or MergeError with the usage."""
    auto_memory_off = "--auto-memory-off" in argv
    arguments = [argument for argument in argv if argument != "--auto-memory-off"]
    manifest_home = None
    if arguments[2:3] == ["--manifest"] and len(arguments) == 4:
        manifest_home, arguments = arguments[3], arguments[:2]
    if len(arguments) != 2:
        raise MergeError("usage: merge_claude_settings.py <src> <dest> [--manifest <home>] [--auto-memory-off]")
    return arguments[0], arguments[1], manifest_home, auto_memory_off


def read_destination(dest_path: str) -> tuple[dict, str]:
    """The destination object and its original text, ({}, "") when the file does not exist."""
    if not os.path.exists(dest_path):
        return {}, ""
    try:
        with open(dest_path, encoding="utf-8") as f:
            original = f.read()
        dest = json.loads(original)
    except (OSError, json.JSONDecodeError) as error:
        raise MergeError(f"merge_claude_settings: cannot read {dest_path}: {error}") from error
    if not isinstance(dest, dict):
        raise MergeError(f"merge_claude_settings: {dest_path} is not a JSON object")
    return dest, original


def merge_hooks(dest: dict, src: dict) -> None:
    """Merge each template event into `dest`. An event the template dropped can still hold a retired registration,
    so it is merged against nothing; one left empty goes."""
    dest_hooks = dest.setdefault("hooks", {})
    for event_type, entries in src.get("hooks", {}).items():
        dest_hooks[event_type] = merge_event(dest_hooks.get(event_type, []), entries)
    for event_type in [e for e in dest_hooks if e not in src.get("hooks", {})]:
        dest_hooks[event_type] = merge_event(dest_hooks[event_type], [])
        if not dest_hooks[event_type]:
            del dest_hooks[event_type]


def write_merged(dest: dict, src: dict, dest_path: str, original: str, manifest_home: str | None, recorded: tuple[dict, dict]) -> None:
    """Back up and write the merged file, then record in the install manifest what the merge added."""
    try:
        # Before anything is written: an unreadable manifest stops the merge with the file unchanged.
        section, dropped = retire_recorded(manifest_home, dest_path, dest, src)
        if original:
            install_blocks.backup(Path(dest_path), original)
        write_json(dest, Path(dest_path))
        if section:
            forget(Path(manifest_home), section, dropped)
            install_blocks.record(Path(manifest_home), section, *recorded)
    except (OSError, install_blocks.ManifestError) as error:
        raise MergeError(f"merge_claude_settings: cannot write {dest_path} or its install record: {error}") from error


def merge(argv: list[str]) -> str:
    """Run one merge from its command line; the destination path, or MergeError."""
    src_path, dest_path, manifest_home, auto_memory_off = parse_arguments(argv)
    try:
        src = read_template(src_path, auto_memory_off)
    except (OSError, json.JSONDecodeError) as error:
        raise MergeError(f"merge_claude_settings: cannot read template: {error}") from error
    dest, original = read_destination(dest_path)
    recorded = added(json.loads(original) if original else {}, src, not os.path.exists(dest_path))
    merge_hooks(dest, src)
    merge_permissions(dest, src)
    for key, value in src.items():
        if key not in ("hooks", "permissions") and key not in dest:
            dest[key] = value
    write_merged(dest, src, dest_path, original, manifest_home, recorded)
    return dest_path


def main() -> int:
    try:
        dest_path = merge(sys.argv[1:])
    except MergeError as error:
        print(error, file=sys.stderr)
        return 2
    print(f"  Merged {dest_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
