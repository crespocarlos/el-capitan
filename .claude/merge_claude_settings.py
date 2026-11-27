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

A retired hook — one this repository used to ship and has since merged or
removed — is dropped from the destination. Leaving it registered is worse
than a missing file: the guard fails closed, so a deleted script would deny
every command it used to inspect. The list and the match live in
`hooks_retirement.py`, shared with the Cursor merger.
"""
import json
import os
import sys
import tempfile
import time

from hooks_retirement import retired


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
    # An event the template dropped can still hold a retired registration; one left empty goes.
    for event_type in [e for e in dest_hooks if e not in src.get("hooks", {})]:
        dest_hooks[event_type] = merge_event(dest_hooks[event_type], [])
        if not dest_hooks[event_type]:
            del dest_hooks[event_type]

    merge_permissions(dest, src)

    for key, value in src.items():
        if key not in ("hooks", "permissions") and key not in dest:
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
