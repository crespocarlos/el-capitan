"""The checks `crew-doctor.py` runs against an install: links, hooks, blocks, auto-memory, tools, state.

Each check returns `Line`s; a `FAIL` line is a problem the command's exit code counts, `ok`, `note` and
`WARN` are not. The checkout is the one this file resolves into, so a doctor run through `~/.agent/bin`
checks the install against the tree it links to. The block text is `.claude/install_blocks.py`'s.
"""

from __future__ import annotations

import importlib.util
import json
import os
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType

from crew.core.memory.memory_claude import remaining
from crew.core.task.task_gc import shown as tilde
from crew.harness import adapters, claude_code, harness_install
from crew.lib.files import checkout

ROOT = checkout()
SHOWN = 3
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


def check_links(home: Path, root: Path = ROOT) -> list[Line]:
    """Every installed catalog command (all but `dev`) is linked into ~/.agent/bin to its venv launcher, no managed link broken."""
    data = json.loads((root / "src" / "crew" / "tools.json").read_text(encoding="utf-8"))
    commands = {e["name"]: home / ".agent" / "venv" / "bin" / e["name"] for e in data["tools"] if e.get("kind") == "command" and e.get("audience") != "dev"}
    bin_dir = home / ".agent" / "bin"
    unlinked = [name for name in commands if not (bin_dir / name).is_symlink()]
    layout = install_blocks(root).LINKS
    broken = sorted({link for directory, depth in layout for link in links_under(home / directory, depth) if not link.exists()})
    elsewhere = sorted(
        os.path.realpath(bin_dir / name)
        for name, source in commands.items()
        if name not in unlinked and os.path.realpath(bin_dir / name) != os.path.realpath(source)
    )
    lines = [
        Line(
            "ok" if not unlinked else "FAIL",
            "links",
            f"{len(commands) - len(unlinked)} of {len(commands)} commands linked in ~/.agent/bin"
            + (f"; missing: {capped(unlinked)}{RERUN}" if unlinked else ""),
        )
    ]
    if broken:
        shown = capped([f"{tilde(link, home)} -> {os.readlink(link)}" for link in broken])
        lines.append(Line("FAIL", "links", f"{len(broken)} broken: {shown}{RERUN}"))
    if elsewhere:
        lines.append(Line("note", "links", f"{len(elsewhere)} commands resolve outside {root} and ~/.agent/venv: {capped(elsewhere)}"))
    return lines + check_config_links(home, root)


def config_dirs(home: Path, root: Path = ROOT) -> list[Path]:
    """The Claude config dirs install recorded, ~/.claude first (only it when the manifest is unreadable)."""
    blocks = install_blocks(root)
    try:
        return blocks.config_dirs(home)
    except blocks.ManifestError:
        return [home / ".claude"]


def config_dir_links(directory: Path, source_dir: Path, root: Path) -> tuple[list[str], list[str]]:
    """The `agents`/`skills` entries of one config dir that are missing, and those the user owns (kept by install)."""
    missing, kept = [], []
    for name in ("agents", "skills"):
        path, source = directory / name, source_dir / name
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
    """Each other config dir links `agents` and `skills`, or each crew entry inside a real one, to ~/.claude.

    An entry the user owns there (a link elsewhere, or a file of the same name) is kept by install: a WARN.
    """
    lines = []
    for directory in config_dirs(home, root)[1:]:
        missing, kept = config_dir_links(directory, home / ".claude", root)
        if missing:
            text = f"{tilde(directory, home)}: not linked to ~/.claude: {capped(missing)}{RERUN}"
            lines.append(Line("FAIL", "links", text))
        if kept:
            text = f"{tilde(directory, home)}: yours, so crew entries are not linked there: {capped(kept)}"
            lines.append(Line("WARN", "links", text))
    return lines


def registrations(hooks: object) -> set[tuple[str, str, str]]:
    """(event, matcher, command) of a Claude-shaped `hooks` object. Within an event a command counts once, under its
    first matcher, as the settings merge registers it."""
    found: set[tuple[str, str, str]] = set()
    for event, entries in hooks.items() if isinstance(hooks, dict) else []:
        seen: set[str] = set()
        for entry in entries if isinstance(entries, list) else []:
            inner = entry.get("hooks", []) if isinstance(entry, dict) else []
            for hook in inner if isinstance(inner, list) else []:
                command = hook.get("command") if isinstance(hook, dict) else None
                if isinstance(command, str) and command not in seen:
                    seen.add(command)
                    found.add((event, str(entry.get("matcher") or ""), command))
    return found


def check_hooks(home: Path, root: Path = ROOT) -> list[Line]:
    """Each Claude config dir registers every hook the claude-code adapter renders, under its event and matcher, and no
    registered script under ~/.claude/hooks is missing (an earlier install's, which install retires)."""
    lines = []
    scripts = install_blocks(root).hook_scripts
    wanted = registrations(json.loads(claude_code.render(root, home)[".claude/settings.json"][1])["hooks"])
    for directory in config_dirs(home, root):
        installed, harness = directory / "settings.json", f"Claude Code ({tilde(directory, home)})"
        try:
            have = registrations(json.loads(installed.read_text(encoding="utf-8")).get("hooks"))
        except (OSError, ValueError, AttributeError):
            lines.append(Line("FAIL", "hooks", f"{harness}: {tilde(installed, home)} is missing or unreadable{RERUN}"))
            continue
        missing = sorted(f"{event} {matcher or '*'}: {command}" for event, matcher, command in wanted - have)
        text = f"{harness}: {len(wanted) - len(missing)} of {len(wanted)} registered as the adapter renders them"
        if missing:
            text += f"; missing or different {capped(missing)}{RERUN}"
        lines.append(Line("FAIL" if missing else "ok", "hooks", text))
        gone = sorted({f"~/{script}" for script in scripts([command for _, _, command in have], home) if not (home / script).exists()})
        if gone:
            lines.append(Line("FAIL", "hooks", f"{harness}: registered hook scripts are missing: {capped(gone)}{RERUN}"))
    return lines


def check_harness_files(home: Path, root: Path = ROOT) -> list[Line]:
    """The installed files equal what every adapter's `render()` returns now (crew.harness.harness_install diff); the
    session-start refresh repairs a stale rendered file, a missing one needs install."""
    problems = harness_install.diff(root, home)
    if problems:
        return [Line("FAIL", "harness", f"{len(problems)} installed files differ from render(): {capped(problems)}{RERUN}")]
    return [Line("ok", "harness", f"every file {', '.join(adapters.IDS)} read matches render()")]


def check_auto_memory(home: Path, root: Path = ROOT) -> list[Line]:
    """Claude Code auto-memory is off in each recorded config dir and the environment; entries left are named.

    Crew memory is the one store. A user's own `true` is kept by install, so it is a WARN, never a FAIL;
    project-level settings are not checked.
    """
    lines, switch = [], os.environ.get("CLAUDE_CODE_DISABLE_AUTO_MEMORY")
    if switch == "0":
        lines.append(Line("WARN", "memory", "CLAUDE_CODE_DISABLE_AUTO_MEMORY=0 forces Claude Code auto-memory on; crew memory is the only store"))
    for directory in config_dirs(home, root):
        name, (pending, review) = tilde(directory, home), remaining([directory])
        left = pending or review
        try:
            value = json.loads((directory / "settings.json").read_text(encoding="utf-8")).get("autoMemoryEnabled")
        except (OSError, ValueError, AttributeError):
            value = None
        if pending:
            lines.append(
                Line(
                    "note",
                    "memory",
                    f"{name}: Claude auto-memory entries to import: {len(pending)}; run ~/.agent/bin/crew-mem.py import-claude --config-dir {directory}, import the drafts, then re-run install.sh",
                )
            )
        if review:
            lines.append(
                Line(
                    "note",
                    "memory",
                    f"{name}: Claude auto-memory entries for your review: {len(review)} (crew-mem.py import-claude --check --config-dir {directory} lists them); decide, then delete or move each file",
                )
            )
        if value is True:
            lines.append(
                Line("WARN", "memory", f"{name}/settings.json: autoMemoryEnabled is true (your value, kept); crew memory is the only store, so set it to false")
            )
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
    """Each managed block equals what install.sh would write today; each managed `@` import loads."""
    blocks = install_blocks(root)
    stale = []
    try:
        wanted_blocks = blocks.expected(root, home)
    except blocks.ManifestError as error:
        return [Line("FAIL", "blocks", f"{error}{RERUN}")]
    for path, wanted in wanted_blocks.items():
        text = path.read_text(encoding="utf-8", errors="replace") if path.is_file() else ""
        stale += [
            f"{tilde(path, home)} {name} block {'missing' if blocks.current(text, name) is None else 'stale'}"
            for name, body in wanted.items()
            if blocks.current(text, name) != body
        ]
    skipped = [f"~/.claude/CLAUDE.md {problem}" for problem in blocks.import_problems(home, root)]
    lines = [Line("FAIL", "blocks", capped(stale) + RERUN) if stale else Line("ok", "blocks", "managed blocks current")]
    return lines + ([Line("FAIL", "imports", capped(skipped) + RERUN)] if skipped else [])
