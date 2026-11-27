"""The checks `crew-doctor.py` runs against an install: links, hooks, blocks, auto-memory, tools, state.

Each check returns `Line`s; a `FAIL` line is a problem the command's exit code counts, `ok`, `note` and
`WARN` are not. The checkout is the one this file resolves into, so a doctor run through `~/.agent/bin`
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

from memory_claude import remaining
from task_gc import TELEMETRY_NOTICE, Places, size_of
from task_gc import shown as tilde

from lib.git import GitError, gh, run_git

ROOT = Path(__file__).resolve().parents[3]
SHOWN = 3
REQUIRED = ("gh", "git", "jq")  # what install.sh's preflight requires besides python3
RERUN = " (re-run install.sh)"


@dataclass(frozen=True)
class Line:
    level: str  # "ok", "note", "WARN" or "FAIL"
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
    return lines + check_config_links(home, root)


def config_dirs(home: Path, root: Path = ROOT) -> list[Path]:
    """The Claude config dirs install recorded, ~/.claude first (only it when the manifest is unreadable)."""
    blocks = install_blocks(root)
    try:
        return blocks.config_dirs(home)
    except blocks.ManifestError:
        return [home / ".claude"]


def config_dir_links(directory: Path, cursor: Path, root: Path) -> tuple[list[str], list[str]]:
    """The `agents`/`skills` entries of one config dir that are missing, and those the user owns (kept by install)."""
    missing, kept = [], []
    for name in ("agents", "skills"):
        path, source = directory / name, cursor / name
        if path.is_symlink() and os.path.realpath(path) != os.path.realpath(source):
            kept.append(name)
        elif path.is_dir() and not path.is_symlink():
            for entry in sorted(p.name for p in (root / ".cursor" / name).iterdir() if not p.name.startswith(".")):
                link = path / entry
                if os.path.realpath(link) == os.path.realpath(source / entry):
                    continue
                (kept if os.path.lexists(link) else missing).append(f"{name}/{entry}")
        elif os.path.realpath(path) != os.path.realpath(source):
            missing.append(name)
    return missing, kept


def check_config_links(home: Path, root: Path = ROOT) -> list[Line]:
    """Each other config dir links `agents` and `skills`, or each crew entry inside a real one, to ~/.cursor.

    An entry the user owns there (a link elsewhere, or a file of the same name) is kept by install: a WARN.
    """
    lines = []
    for directory in config_dirs(home, root)[1:]:
        missing, kept = config_dir_links(directory, home / ".cursor", root)
        if missing:
            text = f"{tilde(directory, home)}: not linked to ~/.cursor: {capped(missing)}{RERUN}"
            lines.append(Line("FAIL", "links", text))
        if kept:
            text = f"{tilde(directory, home)}: yours, so crew entries are not linked there: {capped(kept)}"
            lines.append(Line("WARN", "links", text))
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
    """Each config dir registers every template hook under its event and matcher; every registered script exists."""
    lines = []
    scripts = install_blocks(root).hook_scripts
    claude = [(f"Claude Code ({tilde(directory, home)})", root / ".claude" / "settings.template.json",
               directory / "settings.json", True) for directory in config_dirs(home, root)]
    for harness, template, installed, nested in (
            *claude, ("Cursor", root / ".cursor" / "hooks.template.json", home / ".cursor" / "hooks.json", False)):
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
    return lines + check_cursor_fail_closed(home, root)


def fail_closed_commands(path: Path) -> set[tuple[str, str]] | None:
    """(event, command) of every Cursor hook entry registered `failClosed: true`, or None when unreadable."""
    try:
        hooks = json.loads(path.read_text(encoding="utf-8")).get("hooks", {})
    except (OSError, ValueError, AttributeError):
        return None
    return {(event, entry.get("command")) for event, entries in (hooks.items() if isinstance(hooks, dict) else [])
            for entry in (entries if isinstance(entries, list) else [])
            if isinstance(entry, dict) and entry.get("failClosed") is True}


def check_cursor_fail_closed(home: Path, root: Path = ROOT, jq: str | None = "") -> list[Line]:
    """Each Cursor security guard the template registers `failClosed: true` is installed that way too: without it a
    guard that crashes, times out or prints invalid JSON lets the action through. A missing guard is `check_hooks`'s.
    Without `jq` (`jq`: its path, "" to look it up) a guard cannot answer, so a fail-closed one blocks every Cursor
    call (FAIL), and install registers them fail-open (WARN)."""
    wanted = fail_closed_commands(root / ".cursor" / "hooks.template.json") or set()
    installed = home / ".cursor" / "hooks.json"
    have = fail_closed_commands(installed)
    if have is None:
        return []
    if not (shutil.which("jq") if jq == "" else jq):
        if have:
            return [Line("FAIL", "hooks", f"Cursor: jq is not on PATH and {len(have)} guards are failClosed: true, so "
                                          f"every Cursor call is blocked; install jq{RERUN}")]
        return [Line("WARN", "hooks", f"Cursor: jq is not on PATH, so the guards are registered fail-open; install "
                                      f"jq{RERUN}")]
    registered = {(event, command) for event, _, command in registrations(installed, False) or set()}
    open_guards = sorted(f"{event}: {command}" for event, command in (wanted & registered) - have)
    if not open_guards:
        return [Line("ok", "hooks", f"Cursor: {len(wanted)} security guards fail closed")]
    return [Line("FAIL", "hooks", "Cursor: security guards without failClosed: true (a crash lets the action "
                                  f"through): {capped(open_guards)}{RERUN}")]


HOOK_SCRIPT = re.compile(r"/\.claude/hooks/([\w./-]+\.sh)")
STAND_DOWN = re.compile(r"^hook_stand_down[ \t]+(\S+)([ \t]+fail-closed)?[ \t]*$", re.M)


# A counterpart is `bash "$HOME/.claude/hooks/<script>"`, then only the redirection and `; exit 0` the templates use,
# under the event `lib/cursor-counterparts.json` names: `hook_stand_down` in lib/hook.sh makes the same match.
COUNTERPART_COMMAND = 'bash "$HOME/.claude/hooks/{}"'
COUNTERPART_TAIL = re.compile(r"(\s+2>/dev/null)?(\s*;\s*exit 0)?\s*")


def is_counterpart(command: str, script: str) -> bool:
    head, form = command.lstrip(), COUNTERPART_COMMAND.format(script)
    return head.startswith(form) and COUNTERPART_TAIL.fullmatch(head[len(form):]) is not None


def stands_down(script: str, home: Path, cursor: set[tuple[str, str]], closed: set[tuple[str, str]]) -> bool:
    """Whether `script` calls `hook_stand_down` and Cursor registers (`cursor`: event, command) the counterpart it
    names under its expected event, in `closed` too when the call asks for `fail-closed`: the hook's own test."""
    hooks = home / ".claude" / "hooks"
    try:
        call = STAND_DOWN.search((hooks / script).read_text(encoding="utf-8"))
        events = json.loads((hooks / "lib" / "cursor-counterparts.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    if not call or not isinstance(events, dict):
        return False
    return any(event == events.get(call.group(1)) and is_counterpart(command, call.group(1))
               and (not call.group(2) or (event, command) in closed) for event, command in cursor)


def toplevel(path: Path) -> Path | None:
    return next((folder for folder in (path, *path.parents) if (folder / ".git").exists()), None)


def by_script(commands: list[str]) -> dict[str, set[str]]:
    found: dict[str, set[str]] = {}
    for command in commands:
        script = HOOK_SCRIPT.search(command)
        if script:
            found.setdefault(script.group(1), set()).add(command)
    return found


def check_cursor_duplicates(home: Path, cwd: Path) -> list[Line]:
    """A script registered in ~/.cursor/hooks.json and in a Claude-format file Cursor also loads (~/.claude's
    settings.json, the current repository's `.claude/settings.json` and `settings.local.json`), however each spells
    its command, runs twice in Cursor unless it stands down there (docs/hooks.md, "Each hook in Cursor"). Claude Code
    runs an identical command that several of its settings files register once, so it has no such duplicate."""
    installed = home / ".cursor" / "hooks.json"
    cursor = {(event, command) for event, _, command in registrations(installed, False) or set()}
    closed = fail_closed_commands(installed) or set()
    repo = toplevel(cwd)
    files = [home / ".claude" / "settings.json"]
    files += [repo / ".claude" / name for name in ("settings.json", "settings.local.json")] if repo else []
    claude = by_script([command for path in files for _, _, command in registrations(path, True) or set()])
    native = by_script([command for _, command in cursor])
    shared = sorted(set(claude) & set(native))
    twice = [f"{script} ({' | '.join(sorted(claude[script] | native[script]))})" for script in shared
             if not stands_down(script, home, cursor, closed)]
    if twice:
        return [Line("WARN", "hooks", f"Cursor: {len(twice)} hook scripts run twice, registered in "
                                      "~/.cursor/hooks.json and in a Claude-format file Cursor loads, with no "
                                      f"stand-down: {capped(twice)}")]
    if shared:
        return [Line("ok", "hooks", f"Cursor: {len(shared)} hook scripts registered in both formats stand down in the "
                                    "Claude-format copy")]
    return []


def check_auto_memory(home: Path, root: Path = ROOT) -> list[Line]:
    """Claude Code auto-memory is off in each recorded config dir and the environment; entries left are named.

    Crew memory is the one store. A user's own `true` is kept by install, so it is a WARN, never a FAIL;
    project-level settings are not checked.
    """
    lines, switch = [], os.environ.get("CLAUDE_CODE_DISABLE_AUTO_MEMORY")
    if switch == "0":
        lines.append(Line("WARN", "memory", "CLAUDE_CODE_DISABLE_AUTO_MEMORY=0 forces Claude Code auto-memory on; "
                                            "crew memory is the only store"))
    for directory in config_dirs(home, root):
        name, (pending, review) = tilde(directory, home), remaining([directory])
        left = pending or review
        try:
            value = json.loads((directory / "settings.json").read_text(encoding="utf-8")).get("autoMemoryEnabled")
        except (OSError, ValueError, AttributeError):
            value = None
        if pending:
            lines.append(Line("note", "memory", f"{name}: Claude auto-memory entries to import: {len(pending)}; "
                                                f"run ~/.agent/bin/crew-mem.py import-claude --config-dir "
                                                f"{directory}, import the drafts, then re-run install.sh"))
        if review:
            lines.append(Line("note", "memory", f"{name}: Claude auto-memory entries for your review: {len(review)} "
                                                f"(crew-mem.py import-claude --check --config-dir {directory} "
                                                "lists them); decide, then delete or move each file"))
        if value is True:
            lines.append(Line("WARN", "memory", f"{name}/settings.json: autoMemoryEnabled is true (your value, kept); "
                                                "crew memory is the only store, so set it to false"))
        elif value is None and switch != "1" and not left:
            lines.append(Line("note", "memory", f"{name}: auto-memory is on (autoMemoryEnabled unset){RERUN}"))
    if not lines:
        text = "Claude Code auto-memory off in every config dir (project settings not checked)"
        lines.append(Line("ok", "memory", text))
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
    try:
        wanted_blocks = blocks.expected(root, home)
    except blocks.ManifestError as error:
        return [Line("FAIL", "blocks", f"{error}{RERUN}")]
    for path, wanted in wanted_blocks.items():
        text = path.read_text(encoding="utf-8", errors="replace") if path.is_file() else ""
        stale += [f"{tilde(path, home)} {name} block {'missing' if blocks.current(text, name) is None else 'stale'}"
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
