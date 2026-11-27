"""The checks `crew-doctor.py` runs against an install: links, hook registrations, managed blocks, tools, state.

Each check returns `Line`s; a `FAIL` line is a problem the command's exit code counts, `ok` and `note`
are not. The checkout is the one this file resolves into, so a doctor run through `~/.agent/bin`
checks the install against the tree it links to. The block text is `.claude/install_blocks.py`'s.
"""
from __future__ import annotations

import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType

from task_gc import TELEMETRY_NOTICE, Places, size_of
from task_gc import shown as tilde

from lib.git import GitError, gh, run_git

ROOT = Path(__file__).resolve().parents[3]
SHOWN = 3
REQUIRED = ("gh", "git", "jq")  # what install.sh's preflight requires besides python3
RERUN = " (re-run install.sh)"


@dataclass(frozen=True)
class Line:
    level: str  # "ok", "note" or "FAIL"
    area: str
    text: str


def capped(items: list[str]) -> str:
    more = len(items) - SHOWN
    return "; ".join(items[:SHOWN]) + (f"; +{more} more" if more > 0 else "")


def links_under(directory: Path, depth: int) -> list[Path]:
    """Symlinks under `directory` to `depth` levels, never descending through a link."""
    found: list[Path] = []
    if depth < 1 or not directory.is_dir() or directory.is_symlink():
        return found
    for entry in sorted(directory.iterdir()):
        if entry.is_symlink():
            found.append(entry)
        elif entry.is_dir():
            found += links_under(entry, depth - 1)
    return found


def catalog_commands(root: Path = ROOT) -> dict[str, Path]:
    """Each `kind: command` basename and its file in the checkout."""
    data = json.loads((root / ".agent" / "tools" / "tools.json").read_text(encoding="utf-8"))
    return {e["name"]: root / ".agent" / "tools" / e["dir"] / e["name"]
            for section in ("tools", "scripts") for e in data.get(section, []) if e.get("kind") == "command"}


def check_links(home: Path, root: Path = ROOT) -> list[Line]:
    """Every catalog command is linked into ~/.agent/bin, and no managed link is broken."""
    commands, bin_dir = catalog_commands(root), home / ".agent" / "bin"
    unlinked = [name for name in commands if not (bin_dir / name).is_symlink()]
    layout = install_blocks(root).LINKS
    broken = sorted({link for directory, depth in layout for link in links_under(home / directory, depth)
                     if not link.exists()})
    elsewhere = sorted(os.path.realpath(bin_dir / name) for name, source in commands.items()
                       if name not in unlinked and os.path.realpath(bin_dir / name) != os.path.realpath(source))
    lines = [Line("ok" if not unlinked else "FAIL", "links",
                  f"{len(commands) - len(unlinked)} of {len(commands)} commands linked in ~/.agent/bin"
                  + (f"; missing: {capped(unlinked)}{RERUN}" if unlinked else ""))]
    if broken:
        shown = capped([f"{tilde(link, home)} -> {os.readlink(link)}" for link in broken])
        lines.append(Line("FAIL", "links", f"{len(broken)} broken: {shown}{RERUN}"))
    if elsewhere:
        lines.append(Line("note", "links", f"{len(elsewhere)} commands resolve outside {root}: {capped(elsewhere)}"))
    return lines


def registrations(path: Path, nested: bool) -> set[tuple[str, str, str]] | None:
    """(event, matcher, command) of a Claude (`nested`) or Cursor settings file, or None when unreadable.

    Within an event a command counts once, under its first matcher, as the settings merge registers it.
    """
    try:
        hooks = json.loads(path.read_text(encoding="utf-8")).get("hooks", {})
    except (OSError, ValueError, AttributeError):
        return None
    found: set[tuple[str, str, str]] = set()
    for event, entries in hooks.items() if isinstance(hooks, dict) else []:
        seen: set[str] = set()
        for entry in entries if isinstance(entries, list) else []:
            if not isinstance(entry, dict):
                continue
            inner = entry.get("hooks", []) if nested else [entry]
            for hook in inner if isinstance(inner, list) else []:
                command = hook.get("command") if isinstance(hook, dict) else None
                if isinstance(command, str) and command not in seen:
                    seen.add(command)
                    found.add((event, str(entry.get("matcher") or ""), command))
    return found


def check_hooks(home: Path, root: Path = ROOT) -> list[Line]:
    """Every template hook is registered under its event and matcher, and every registered script exists."""
    lines = []
    scripts = install_blocks(root).hook_scripts
    for harness, template, installed, nested in (
            ("Claude Code", root / ".claude" / "settings.json", home / ".claude" / "settings.json", True),
            ("Cursor", root / ".cursor" / "hooks.template.json", home / ".cursor" / "hooks.json", False)):
        wanted, have = registrations(template, nested) or set(), registrations(installed, nested)
        if have is None:
            lines.append(Line("FAIL", "hooks", f"{harness}: {tilde(installed, home)} is missing or unreadable{RERUN}"))
            continue
        missing = sorted(f"{event} {matcher or '*'}: {command}" for event, matcher, command in wanted - have)
        text = f"{harness}: {len(wanted) - len(missing)} of {len(wanted)} registered as the template has them"
        if missing:
            text += f"; missing or different {capped(missing)}{RERUN}"
        lines.append(Line("FAIL" if missing else "ok", "hooks", text))
        gone = sorted({f"~/{script}" for script in scripts([command for _, _, command in have], home)
                       if not (home / script).exists()})
        if gone:
            text = f"{harness}: registered hook scripts are missing: {capped(gone)}{RERUN}"
            lines.append(Line("FAIL", "hooks", text))
    return lines


def install_blocks(root: Path = ROOT) -> ModuleType:
    """`.claude/install_blocks.py` of the checkout, loaded by path: the one writer of the block text."""
    spec = importlib.util.spec_from_file_location("install_blocks", root / ".claude" / "install_blocks.py")
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {root / '.claude' / 'install_blocks.py'}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def check_blocks(home: Path, root: Path = ROOT) -> list[Line]:
    """Each managed block in CLAUDE.md and AGENTS.md equals what install.sh would write today."""
    blocks = install_blocks(root)
    stale = []
    for target, wanted in blocks.expected(root).items():
        path = home / target
        text = path.read_text(encoding="utf-8", errors="replace") if path.is_file() else ""
        stale += [f"~/{target} {name} block {'missing' if blocks.current(text, name) is None else 'stale'}"
                  for name, body in wanted.items() if blocks.current(text, name) != body]
    return [Line("FAIL", "blocks", capped(stale) + RERUN) if stale else Line("ok", "blocks", "managed blocks current")]


def version(argv: list[str]) -> str | None:
    """The version number `argv` prints ("present" when it prints none), or None when absent or failing."""
    if not shutil.which(argv[0]):
        return None
    try:
        done = (run_git(None, argv[1:], check=False, timeout=10) if argv[0] == "git"
                else gh(*argv[1:], timeout=10) if argv[0] == "gh"
                else subprocess.run(argv, capture_output=True, text=True, timeout=10))
    except (OSError, subprocess.SubprocessError, GitError):
        return None
    number = re.search(r"\d+(?:\.\d+)+", done.stdout or done.stderr or "")
    return (number.group(0) if number else "present") if done.returncode == 0 else None


def check_tools(sign_in: bool = True) -> list[Line]:
    """python3 >= 3.9, gh, git and jq (required); shfmt and uv (optional); which hook parser runs; gh sign-in."""
    found = {name: version([name, "--version"]) for name in (*REQUIRED, "shfmt", "uv")}
    python = ".".join(map(str, sys.version_info[:3]))
    missing = [name for name in REQUIRED if not found[name]]
    listed = ", ".join(f"{name} {found[name] or 'MISSING'}" for name in REQUIRED)
    fixes = ([f"install {', '.join(missing)} (install.sh's preflight lists what it needs)"] if missing else []) + (
        ["python3 3.9 or newer is required"] if sys.version_info < (3, 9) else [])
    text = f"python3 {python}, {listed}" + "".join(f"; {fix}" for fix in fixes)
    lines = [Line("FAIL" if fixes else "ok", "tools", text)]
    parser = ("shfmt (bash syntax tree)" if found["shfmt"] and found["jq"]
              else "awk fallback (install shfmt for a real syntax tree)")
    uv = found["uv"] or "absent (needed for the tests only)"
    lines.append(Line("note", "tools", f"shfmt {found['shfmt'] or 'absent'}, uv {uv}; hook parser: {parser}"))
    if found["gh"] and sign_in:
        try:
            signed_in = gh("auth", "status", timeout=20).returncode == 0
        except (OSError, subprocess.SubprocessError):
            signed_in = False
        lines.append(Line("ok", "gh", "signed in") if signed_in
                     else Line("FAIL", "gh", "not signed in: run gh auth login"))
    return lines


def check_state(places: Places, limits: dict) -> list[Line]:
    """Task and session state against the `doctor` limits of ~/.agent/config.json, and the legacy telemetry."""
    lines = []
    for label, path, key in (("tasks", places.tasks, "tasks_mb"),
                             ("sessions", places.memory / ".sessions", "sessions_mb")):
        size = size_of(path) / 1e6 if path.exists() else 0.0
        over = size > limits[key]
        lines.append(Line("FAIL" if over else "ok", "state", f"{label} {size:.1f} MB (limit {limits[key]} MB)"
                          + ("; crew gc lists what it would collect" if over else "")))
    telemetry = places.agent / "telemetry"
    if telemetry.exists():
        size = size_of(telemetry) / 1e6
        text = (f"~/.agent/telemetry {size:.1f} MB: {TELEMETRY_NOTICE}; "
                "crew-task.py gc --only telemetry --apply removes only it")
        lines.append(Line("FAIL", "state", text))
    return lines
