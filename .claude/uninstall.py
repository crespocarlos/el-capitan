#!/usr/bin/env python3
"""`install.sh --uninstall`: remove what install created, unregistering before deleting.

Usage: uninstall.py <home> <checkout> [--dry-run]

Order: every file is read and checked first, and an unreadable one stops the run (exit 2) before
anything changes. Then the settings entries install recorded as added (`~/.agent/install-manifest.json`)
and the managed blocks go, and only then the links, so a guard is never registered without its
script. A link whose script a remaining registration still runs is kept. The links are found by the
install layout (`install_blocks.LINKS`) and removed when they point into the recorded checkout, by
real path; each recorded Claude config dir loses its settings entries, blocks and `agents`/`skills`
links into ~/.cursor; the directories install created go when empty. Exit 0 when nothing of the install is left,
1 when links remain (each is reported), 2 when the run refused before changing anything.
~/.agent data stays.
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

import install_blocks
import merge_claude_settings
import merge_cursor_hooks
from install_blocks import MANIFEST, commands_in, hook_scripts, inside, layout_links, target_of, write_json

TEMPLATES = {"claude_settings": Path(".claude/settings.json"), "cursor_hooks": Path(".cursor/hooks.template.json")}
SHOWN = 5
# A dangling link whose target ends in a path the install layout links from: an install from a checkout
# that was moved or deleted. A user's own dangling link names some other path.
STRAY = re.compile(r"/(\.agent/tools/|\.agent/_\w+\.md$|\.cursor/(agents|skills)/|rules/[^/]+\.mdc$|\.claude/hooks/)")


class Refused(Exception):
    """A reason to stop before anything changes."""


def tilde(path: Path, home: Path) -> str:
    text = str(path)
    return "~" + text[len(str(home)):] if text.startswith(str(home) + os.sep) else text


def checkout_of(path: str) -> str | None:
    """The el-capitan checkout an existing path lies in (a directory holding install.sh and the tool catalog)."""
    for parent in Path(path).parents:
        if (parent / "install.sh").is_file() and (parent / ".agent" / "tools" / "tools.json").is_file():
            return str(parent)
    return None


def settings_files(home: Path) -> dict[str, Path]:
    """Each settings file install merges into, by manifest section: every Claude config dir's, then Cursor's."""
    found = {install_blocks.settings_section(home, directory): directory / "settings.json"
             for directory in install_blocks.config_dirs(home)}
    return {**found, "cursor_hooks": home / ".cursor" / "hooks.json"}


def template_of(section: str) -> Path:
    return TEMPLATES["claude_settings" if section.startswith("claude_settings") else section]


def config_links(home: Path) -> list[Path]:
    """The links install wrote into the other config dirs: `agents` and `skills`, or, inside a real one, each link
    named after the ~/.cursor entry it points to. A user's link elsewhere, or under another name, is not one."""
    cursor = os.path.realpath(home / ".cursor")
    found = []
    for directory in install_blocks.config_dirs(home)[1:]:
        for name in ("agents", "skills"):
            link = directory / name
            if link.is_symlink():
                found += [link] if target_of(link) == os.path.join(cursor, name) else []
            elif link.is_dir():
                found += [entry for entry in sorted(link.iterdir()) if entry.is_symlink()
                          and points_at(entry, os.path.join(cursor, name))]
    return found


def points_at(entry: Path, directory: str) -> bool:
    """True when the link names `directory`/<its own name>; the entry there may itself be a link, so the
    link text is compared, not its fully resolved target."""
    raw = os.readlink(entry)
    return os.path.basename(raw) == entry.name and os.path.realpath(os.path.dirname(raw)) == directory


def owned_links(home: Path, roots: set[str]) -> tuple[list[Path], dict[str, int]]:
    """The links into `roots` (plus the config dirs' agents and skills links), and other checkouts' link counts."""
    owned, others = config_links(home), {}
    for link in layout_links(home):
        target = target_of(link)
        if link.parent == home / ".claude":
            if link.name in ("agents", "skills") and target == os.path.realpath(home / ".cursor" / link.name):
                owned.append(link)
        elif inside(target, roots):
            owned.append(link)
        elif os.path.exists(target) and (other := checkout_of(target)):
            others[other] = others.get(other, 0) + 1
    return owned, others


def read_settings(home: Path) -> dict[str, dict | None]:
    """Each settings file as JSON (None when absent); an unreadable one or a non-object refuses."""
    found = {}
    for section, path in settings_files(home).items():
        if not path.exists():
            found[section] = None
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            raise Refused(f"cannot read {tilde(path, home)}: {error}") from error
        if not isinstance(data, dict):
            raise Refused(f"{tilde(path, home)} is not a JSON object")
        found[section] = data
    return found


def capped(items: list[str]) -> str:
    return "; ".join(items[:SHOWN]) + (f"; +{len(items) - SHOWN} more" if len(items) > SHOWN else "")


def entry_ids(section: str, data: dict) -> tuple[set[str], set[tuple[str, str]]]:
    """The rules and (event, command) registrations a settings document holds."""
    if section.startswith("claude_settings"):
        return merge_claude_settings.held_rules(data), merge_claude_settings.hook_ids(data.get("hooks"))
    return set(), merge_cursor_hooks.pairs(data.get("hooks"))


def installed_hook(home: Path, command: str, roots: set[str]) -> bool:
    """True when the command runs a script under ~/.claude/hooks whose link points into an install checkout."""
    for script in hook_scripts([command], home):
        top = home / ".claude" / "hooks" / Path(script).relative_to(".claude/hooks").parts[0]
        if top.is_symlink() and inside(target_of(top), roots):
            return True
    return False


def resolve_legacy(home: Path, section: str, recorded: dict, template: dict, since: object,
                   roots: set[str]) -> tuple[dict, list[str]]:
    """`recorded` plus the `legacy` entries the user did not have; with no evidence, the rules to review.

    `legacy` holds the template entries an install from before the manifest may have added. The oldest
    backup written before that install was found (`since`) is the closest record of what the user had:
    an entry it held stays. Without such a backup, a hook whose script is a link into an install
    checkout is the install's (the script exists only because of it); a permission rule is kept and listed.
    """
    legacy = recorded.get("legacy")
    if not legacy:
        return recorded, []
    before = since if isinstance(since, (int, float)) and not isinstance(since, bool) else None
    oldest = install_blocks.oldest_backup(settings_files(home)[section], before)
    try:
        snapshot = json.loads(oldest.read_text(encoding="utf-8")) if oldest else None
    except (OSError, ValueError):
        snapshot = None
    if not isinstance(snapshot, dict):
        ours = [pair for pair in legacy.get("hooks", []) if installed_hook(home, pair[1], roots)]
        listed = ([rule for rules in legacy.get("rules", {}).values() for rule in rules]
                  + [pair[1] for pair in legacy.get("hooks", []) if pair not in ours])
        extra = {"hooks": ours, "events": list(template.get("hooks", {}))} if ours else {}
        return install_blocks.union(recorded, extra), listed
    rules, hooks = entry_ids(section, snapshot)
    old_hooks = snapshot.get("hooks") if isinstance(snapshot.get("hooks"), dict) else {}
    old_lists = snapshot.get("permissions") if isinstance(snapshot.get("permissions"), dict) else {}
    extra = {"rules": {name: [r for r in rs if r not in rules] for name, rs in legacy.get("rules", {}).items()},
             "hooks": [pair for pair in legacy.get("hooks", []) if tuple(pair) not in hooks],
             "events": [event for event in template.get("hooks", {}) if event not in old_hooks],
             "lists": [name for name in template.get("permissions", {}) if name not in old_lists],
             "keys": [key for key in (*template, *merge_claude_settings.AUTO_MEMORY_OFF, "version")
                      if key not in snapshot]}
    return install_blocks.union(recorded, extra), []


def plan_settings(home: Path, checkout: Path, manifest: dict | None, current: dict,
                  roots: set[str]) -> tuple[dict, list[str]]:
    """The settings documents after removing the recorded entries, and the lines that say what was kept or retired."""
    after, notes = {}, []
    for section, data in current.items():
        if data is None:
            continue
        template = json.loads((checkout / template_of(section)).read_text(encoding="utf-8"))
        name = tilde(settings_files(home)[section], home)
        left = json.loads(json.dumps(data))
        recorded = (manifest or {}).get(section)
        if manifest is None:
            rules = {r for rs in template.get("permissions", {}).values() for r in rs}
            kept = (sorted(set(commands_in(left)) & set(commands_in(template)))
                    + sorted(entry_ids(section, left)[0] & rules))
            if kept:
                notes.append(f"  kept {len(kept)} entries of {name} that match the template (no install record: "
                             f"installed before it existed); review by hand: {capped(kept)}")
        elif recorded:
            recorded, review = resolve_legacy(home, section, recorded, template, manifest.get("legacy"), roots)
            if review:
                notes.append(f"  kept {len(review)} entries of {name} added by an install before the manifest, "
                             f"review by hand (no backup to compare with): {capped(review)}")
            retired = sorted({r for rs in recorded.get("rules", {}).values() for r in rs} & entry_ids(section, left)[0]
                             - {r for rs in template.get("permissions", {}).values() for r in rs})
            if retired:
                notes.append(f"  removed {len(retired)} rule(s) of {name} that install added and the current "
                             f"template no longer has: {capped(retired)}")

            def warn(text: str, name: str = name) -> None:
                print(f"  warning: {name}: {text}")
            merger = merge_claude_settings if section.startswith("claude_settings") else merge_cursor_hooks
            left = merger.unmerge(left, recorded, template, warn)
        after[section] = left
    return after, notes


def still_run(home: Path, after: dict) -> dict[Path, list[str]]:
    """The hook links a remaining registration runs (the script's top entry under ~/.claude/hooks, and `lib`)."""
    scripts = hook_scripts([c for data in after.values() for c in commands_in(data)], home)
    tops: dict[Path, list[str]] = {}
    for script in dict.fromkeys(scripts):
        top = home / ".claude" / "hooks" / Path(script).relative_to(".claude/hooks").parts[0]
        tops.setdefault(top, []).append(f"~/{script}")
    if tops:
        tops.setdefault(home / ".claude" / "hooks" / "lib", ["the hooks above"])
    return tops


def uninstall(home: Path, checkout: Path, dry_run: bool) -> int:
    manifest = install_blocks.load_manifest(home)
    # This checkout and every one install recorded: a link into any of them is the install's.
    roots = {os.path.realpath(checkout), str(checkout), *(manifest or {}).get("checkouts", [])}
    links, others = owned_links(home, roots)
    in_config = set(config_links(home))
    if others and all(link.parent == home / ".claude" or link in in_config for link in links):
        other = max(others, key=others.get)
        raise Refused(f"installed from {other}; run {other}/install.sh --uninstall")
    current = read_settings(home)
    after, review = plan_settings(home, checkout, manifest, current, roots)
    blocks = install_blocks.block_removals(home)
    keep = still_run(home, after)
    removing = [link for link in links if link not in keep]
    kept = {link: keep[link] for link in links if link in keep}
    verb = "would remove" if dry_run else "removed"
    for section, data in after.items():
        path = settings_files(home)[section]
        if data == current[section]:
            continue
        # A symlinked file (dotfiles) keeps its link: it is written as `{}` rather than deleted.
        gone = not data and ((manifest or {}).get(section) or {}).get("created") and not path.is_symlink()
        print(f"  {verb} the el-capitan entries from {tilde(path, home)}" + (" (then empty: deleted)" if gone else ""))
        if dry_run:
            continue
        if gone:
            path.unlink()
        else:
            write_json(data, path)
    for path, text in blocks:
        suffix = " (then empty: deleted)" if text is None else ""
        print(f"  {verb} the el-capitan blocks from {tilde(path, home)}{suffix}")
        if dry_run:
            continue
        if text is None:
            path.unlink()
        else:
            install_blocks.write_atomically(path, text)
    print(f"  {verb} {len(removing)} link(s) into {', '.join(sorted(roots))}")
    if not dry_run:
        for link in removing:
            link.unlink()
        # `dirs` are relative to HOME; `created_config_dirs` are absolute, wherever the config dir lives.
        relative = sorted((manifest or {}).get("dirs", []), key=lambda d: d.count("/"), reverse=True)
        absolute = [Path(name) for name in (manifest or {}).get("created_config_dirs", []) if os.path.isabs(name)]
        for directory in [home / name for name in relative if not os.path.isabs(name)] + absolute:
            if directory.is_dir() and not directory.is_symlink() and not any(directory.iterdir()):
                directory.rmdir()
    for line in review:
        print(line)
    return report_leftovers(home, roots, kept, others, dry_run)


def report_leftovers(home: Path, roots: set[str], kept: dict[Path, list[str]], others: dict[str, int],
                     dry_run: bool) -> int:
    """Say which links remain and why; exit 1 while any does, else drop the manifest and exit 0."""
    if kept:
        names = capped([f"{tilde(link, home)} (runs {', '.join(scripts)})" for link, scripts in kept.items()])
        print(f"  kept {len(kept)} hook link(s) a remaining registration still runs: {names}; "
              "remove those registrations, then run install.sh --uninstall again")
    for other, count in sorted(others.items()):
        print(f"  {count} link(s) point into another checkout, {other}; run {other}/install.sh --uninstall")
    stray = [link for link in layout_links(home) if not os.path.exists(link) and STRAY.search(os.readlink(link))
             and not inside(target_of(link), roots)]
    if stray:
        names = ", ".join(f"{tilde(link, home)} -> {os.readlink(link)}" for link in stray[:SHOWN])
        print(f"  {len(stray)} dangling link(s) into a checkout that no longer exists (moved?): {names}")
    if dry_run:
        return 0
    left = len(owned_links(home, roots)[0]) + sum(others.values()) + len(stray)
    if left:
        print(f"  {left} link(s) left; not fully uninstalled")
        return 1
    (home / MANIFEST).unlink(missing_ok=True)
    return 0


def main(argv: list[str]) -> int:
    if len(argv) not in (2, 3) or argv[2:] not in ([], ["--dry-run"]):
        print("usage: uninstall.py <home> <checkout> [--dry-run]", file=sys.stderr)
        return 2
    try:
        return uninstall(Path(argv[0]), Path(argv[1]), argv[2:] == ["--dry-run"])
    except (Refused, install_blocks.ManifestError) as error:
        print(f"error: {error}. Nothing was changed.", file=sys.stderr)
        return 2
    except OSError as error:
        print(f"error: {error}; the steps printed above are done, re-run install.sh --uninstall", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
