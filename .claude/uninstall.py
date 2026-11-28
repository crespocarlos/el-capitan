#!/usr/bin/env python3
"""`install.sh --uninstall`: remove what install created, unregistering before deleting.

Usage: uninstall.py <home> <checkout> [--dry-run]

Order: every file is read and checked first, and an unreadable one stops the run (exit 2) before
anything changes. Then the settings entries install recorded as added (`~/.agent/install-manifest.json`)
and the managed blocks go, and only then the links. The links are found by the install layout
(`install_blocks.LINKS`) and removed when they point into the recorded checkout, by real path; each recorded Claude
config dir loses its settings entries, blocks and `agents`/`skills` links into ~/.claude; every file the adapters
rendered (`rendered` in the manifest) and what the layout before the adapters registered
(`harness_install.retire_legacy`) go with the links; the directories install created go when empty, and
~/.agent/venv goes once nothing else is left. Exit 0 when nothing of the install is left, 1 when links remain (each
is reported), 2 when the run refused before changing anything. ~/.agent data stays.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import sys
from pathlib import Path

import install_blocks
import merge_claude_settings
from install_blocks import MANIFEST, commands_in, inside, layout_links, target_of, write_json

from crew.harness import claude_code, harness_install

SHOWN = 5
# A dangling link whose target ends in a path the install layout links from: an install from a checkout
# that was moved or deleted. A user's own dangling link names some other path.
STRAY = re.compile(r"/(src/crew/|\.agent/_\w+\.md$|\.cursor/(agents|skills)/|rules/[^/]+\.mdc$|\.claude/hooks)")


class Refused(Exception):
    """A reason to stop before anything changes."""


def tilde(path: Path, home: Path) -> str:
    text = str(path)
    return "~" + text[len(str(home)) :] if text.startswith(str(home) + os.sep) else text


def checkout_of(path: str) -> str | None:
    """The el-capitan checkout an existing path lies in (a directory holding install.sh and the tool catalog)."""
    for parent in Path(path).parents:
        if (parent / "install.sh").is_file() and (parent / "src" / "crew" / "tools.json").is_file():
            return str(parent)
    return None


def settings_files(home: Path) -> dict[str, Path]:
    """Each settings file install merges into, by manifest section: every Claude config dir's."""
    return {install_blocks.settings_section(home, directory): directory / "settings.json" for directory in install_blocks.config_dirs(home)}


def config_links(home: Path) -> list[Path]:
    """The links install wrote into the other config dirs: `agents` and `skills`, or, inside a real one, each link
    named after the ~/.claude (or, from an earlier install, ~/.cursor) entry it points to. A user's link elsewhere, or
    under another name, is not one."""
    sources = [os.path.realpath(home / ".claude"), os.path.realpath(home / ".cursor")]
    found = []
    for directory in install_blocks.config_dirs(home)[1:]:
        for name in ("agents", "skills"):
            link = directory / name
            if link.is_symlink():
                found += [link] if target_of(link) in [os.path.join(source, name) for source in sources] else []
            elif link.is_dir():
                found += [
                    entry for entry in sorted(link.iterdir()) if entry.is_symlink() and any(points_at(entry, os.path.join(source, name)) for source in sources)
                ]
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


def entry_ids(data: dict) -> tuple[set[str], set[tuple[str, str]]]:
    """The rules and (event, command) registrations a settings document holds."""
    return merge_claude_settings.held_rules(data), merge_claude_settings.hook_ids(data.get("hooks"))


def plan_settings(home: Path, checkout: Path, manifest: dict | None, current: dict, roots: set[str]) -> tuple[dict, list[str]]:
    """The settings documents after removing the recorded entries, and the lines that say what was kept or retired."""
    after, notes = {}, []
    for section, data in current.items():
        if data is None:
            continue
        # Install wrote the fragment's directories expanded; compare with what it wrote.
        fragment = json.loads(claude_code.render(checkout, home)[".claude/settings.json"][1])
        template = merge_claude_settings.expand_dirs(fragment, str(home))
        name = tilde(settings_files(home)[section], home)
        left = json.loads(json.dumps(data))
        recorded = (manifest or {}).get(section)
        if manifest is None:
            rules = {r for rs in template.get("permissions", {}).values() for r in rs}
            kept = sorted(set(commands_in(left)) & set(commands_in(template))) + sorted(entry_ids(left)[0] & rules)
            if kept:
                notes.append(
                    f"  kept {len(kept)} entries of {name} that match the template (no install record: installed before it existed); review by hand: {capped(kept)}"
                )
        elif recorded:
            retired = sorted(
                {r for rs in recorded.get("rules", {}).values() for r in rs}
                & entry_ids(left)[0] - {r for rs in template.get("permissions", {}).values() for r in rs}
            )
            if retired:
                notes.append(f"  removed {len(retired)} rule(s) of {name} that install added and the current template no longer has: {capped(retired)}")

            def warn(text: str, name: str = name) -> None:
                print(f"  warning: {name}: {text}")

            left = merge_claude_settings.unmerge(left, recorded, template, warn)
        after[section] = left
    return after, notes


def remove_rendered(checkout: Path, home: Path, manifest: dict, roots: set[str], removing: list[Path], verb: str, dry_run: bool) -> None:
    """Remove the links, the files the adapters rendered and the layout before them, then each directory install
    created that is left empty."""
    rendered = [home / name for name in manifest.get("rendered", []) if (home / name).is_symlink() or (home / name).is_file()]
    if rendered:
        print(f"  {verb} {len(rendered)} file(s) and link(s) the adapters rendered")
    if dry_run:
        return
    for line in harness_install.retire_legacy(checkout, home, roots, manifest):
        print(line)
    for path in dict.fromkeys([*removing, *rendered]):
        if os.path.lexists(path):
            path.unlink()
    # `dirs` are relative to HOME; `created_config_dirs` are absolute, wherever the config dir lives.
    relative = sorted(manifest.get("dirs", []), key=lambda d: d.count("/"), reverse=True)
    absolute = [Path(name) for name in manifest.get("created_config_dirs", []) if os.path.isabs(name)]
    for directory in [home / name for name in relative if not os.path.isabs(name)] + absolute:
        if directory.is_dir() and not directory.is_symlink() and not any(directory.iterdir()):
            directory.rmdir()


def uninstall(home: Path, checkout: Path, dry_run: bool) -> int:
    manifest = install_blocks.load_manifest(home)
    # This checkout and every one install recorded: a link into any of them is the install's.
    venv = home / ".agent" / "venv"
    roots = {os.path.realpath(checkout), str(checkout), os.path.realpath(venv), *(manifest or {}).get("checkouts", [])}
    links, others = owned_links(home, roots)
    in_config = set(config_links(home))
    # The venv's launchers belong to whichever checkout installed last; they never show which one.
    launchers = {link for link in links if inside(target_of(link), {os.path.realpath(venv)})}
    if others and all(link.parent == home / ".claude" or link in in_config | launchers for link in links):
        other = max(others, key=others.get)
        raise Refused(f"installed from {other}; run {other}/install.sh --uninstall")
    current = read_settings(home)
    after, review = plan_settings(home, checkout, manifest, current, roots)
    blocks = install_blocks.block_removals(home)
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
    print(f"  {verb} {len(links)} link(s) into {', '.join(sorted(roots))}")
    remove_rendered(checkout, home, manifest or {}, roots, links, verb, dry_run)
    for line in review:
        print(line)
    return report_leftovers(home, roots, others, dry_run)


def report_leftovers(home: Path, roots: set[str], others: dict[str, int], dry_run: bool) -> int:
    """Say which links remain and why; exit 1 while any does, else drop the manifest and exit 0."""
    for other, count in sorted(others.items()):
        print(f"  {count} link(s) point into another checkout, {other}; run {other}/install.sh --uninstall")
    stray = [link for link in layout_links(home) if not os.path.exists(link) and STRAY.search(os.readlink(link)) and not inside(target_of(link), roots)]
    if stray:
        names = ", ".join(f"{tilde(link, home)} -> {os.readlink(link)}" for link in stray[:SHOWN])
        print(f"  {len(stray)} dangling link(s) into a checkout that no longer exists (moved?): {names}")
    if dry_run:
        return 0
    left = len(owned_links(home, roots)[0]) + sum(others.values()) + len(stray)
    venv = home / ".agent" / "venv"
    if left:
        print(f"  {left} link(s) left; not fully uninstalled")
        if venv.is_dir():
            print("  kept ~/.agent/venv: the links left above still run its commands")
        return 1
    shutil.rmtree(venv, ignore_errors=True)
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
