#!/usr/bin/env python3
"""Checks for the installed command surface: catalog kinds, wrapper parity, and install links.

Three properties, each with its own failure that no other suite covers:

- every catalog entry declares what it is (`command`, `module`, `asset`), and every command basename
  follows one rule, so the surface cannot drift back to 22 commands with four ad-hoc names;
- a deprecated wrapper behaves exactly like the command it names — same exit code, same stdout,
  same stderr apart from its one deprecation line — because a wrapper that silently drops a flag or
  changes an exit code breaks callers that were never touched by the rename;
- `install.sh` links commands and nothing else, so an internal module cannot reappear in
  `~/.agent/bin` as a fake command.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / ".agent" / "tools"
MANIFEST = TOOLS / "tools.json"
LINT = TOOLS / "maintenance" / "crew-lint.py"
INSTALL = ROOT / "install.sh"

SECTIONS = {"tools": "command", "scripts": "command", "modules": "module", "assets": "asset"}
COMMAND_NAME = re.compile(r"^crew-[a-z0-9-]+\.(py|sh)$")
SOURCE_ONLY = {"task-env.sh"}
WARNING = re.compile(r"^warning: \S+ is deprecated; use \S+ instead$")

FAILED: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"pass: {name}")
        return
    FAILED.append(name)
    print(f"FAIL: {name}{': ' + detail if detail else ''}")


def entries() -> list[tuple[str, dict]]:
    data = json.loads(MANIFEST.read_text())
    return [(section, entry) for section in SECTIONS for entry in data.get(section, [])]


def catalog() -> list[tuple[str, dict]]:
    """Every entry declares the `kind` its section implies, and commands follow the name rule."""
    listed = entries()
    check("catalog is non-empty", bool(listed))

    missing = [entry.get("name") for _, entry in listed if "kind" not in entry]
    check("every entry declares kind", not missing, f"missing kind: {missing}")

    mismatched = [(section, entry.get("name"), entry.get("kind")) for section, entry in listed
                  if entry.get("kind") not in (None, SECTIONS[section])]
    check("kind matches the section it is listed in", not mismatched, str(mismatched))

    bad = []
    for section, entry in listed:
        name, kind = entry.get("name", ""), entry.get("kind")
        if kind != "command" or name in SOURCE_ONLY:
            continue
        if entry.get("status") == "deprecated":
            continue
        if not COMMAND_NAME.match(name):
            bad.append(name)
    check("every command basename is crew-<kebab>.(py|sh)", not bad, f"not renamed: {bad}")

    commands = {entry.get("name") for _, entry in listed if entry.get("kind") == "command"}
    wrappers = [(entry.get("name"), entry.get("replacement")) for _, entry in listed
                if entry.get("status") == "deprecated"]
    check("the catalog declares deprecated wrappers", bool(wrappers))
    for name, replacement in wrappers:
        check(f"{name} names a cataloged replacement", replacement in commands, str(replacement))
        old = entry_path(name)
        new = entry_path(replacement) if replacement else None
        check(f"{name} wrapper exists", old is not None and old.is_file(), str(old))
        check(f"{replacement} exists beside it", new is not None and new.is_file(), str(new))


def entry_path(name: str) -> Path | None:
    for _, entry in entries():
        if entry.get("name") == name:
            return TOOLS / str(entry.get("dir", ".")) / name
    return None


def invoke(path: Path, arguments: list[str]) -> subprocess.CompletedProcess:
    if path.suffix == ".sh":
        return subprocess.run(["bash", str(path), *arguments],
                              capture_output=True, text=True)
    return subprocess.run([sys.executable, str(path), *arguments],
                          capture_output=True, text=True)


def without_warning(text: str) -> str:
    return "\n".join(line for line in text.splitlines() if not WARNING.match(line))


def smoke_arguments(entry: dict) -> list[str]:
    """The invocation the catalog declares safe: `--help`, or `--stat` for a source-only script."""
    smoke = str(entry.get("smoke", ""))
    if smoke == "source-only":
        return ["--stat"]
    return smoke.split()


def parity() -> None:
    """Each wrapper reproduces its replacement's exit code, stdout, and stderr."""
    for _, entry in entries():
        name = entry.get("name", "")
        replacement = entry.get("replacement")
        if entry.get("status") != "deprecated" or not replacement:
            continue
        old, new = entry_path(name), entry_path(replacement)
        if old is None or new is None or not old.is_file() or not new.is_file():
            check(f"{name} has a wrapper and a target to compare", False)
            continue
        arguments = smoke_arguments(entry)
        through_wrapper = invoke(old, arguments)
        direct = invoke(new, arguments)
        detail = (f"argv={arguments} wrapper rc={through_wrapper.returncode} "
                  f"replacement rc={direct.returncode}")
        check(f"{name} exits like {replacement}", through_wrapper.returncode == direct.returncode, detail)
        check(f"{name} prints what {replacement} prints", through_wrapper.stdout == direct.stdout,
              detail + f"\n--- wrapper\n{through_wrapper.stdout[:400]}\n--- replacement\n{direct.stdout[:400]}")
        check(f"{name} adds only its deprecation line",
              without_warning(through_wrapper.stderr) == without_warning(direct.stderr),
              detail + f"\n--- wrapper\n{through_wrapper.stderr[:400]}\n--- replacement\n{direct.stderr[:400]}")
        if entry.get("smoke") != "source-only":
            check(f"{name} warns exactly once", len(through_wrapper.stderr.splitlines()) -
                  len(without_warning(through_wrapper.stderr).splitlines()) == 1,
                  through_wrapper.stderr[:400])


def install_links() -> None:
    """The dry-run link set is exactly the catalog's commands, with no module among them."""
    with tempfile.TemporaryDirectory() as temporary:
        environment = {**os.environ, "HOME": temporary}
        for key in ("CREW_MEMORY_DIR", "CREW_JOURNAL_DIR", "CREW_TASK_DIR"):
            environment.pop(key, None)
        result = subprocess.run(["bash", str(INSTALL), "--dry-run"],
                                capture_output=True, text=True, env=environment)
    check("install dry-run succeeds", result.returncode == 0, result.stderr[-600:])
    linked = re.findall(r"ln -sf (\S+) ", result.stdout)
    tools_linked = [Path(target) for target in linked if "/.agent/tools/" in target]
    check("install links the tool tree", bool(tools_linked), str(tools_linked[:5]))

    modules = {entry.get("name") for _, entry in entries() if entry.get("kind") == "module"}
    leaked = sorted(path.name for path in tools_linked if path.name in modules)
    check("no module is linked", not leaked, f"linked modules: {leaked}")
    assets = {entry.get("name") for _, entry in entries() if entry.get("kind") == "asset"}
    check("no asset is linked", not [path.name for path in tools_linked if path.name in assets])

    commands = {entry.get("name") for _, entry in entries() if entry.get("kind") == "command"}
    linked_names = {path.name for path in tools_linked}
    check("every command is linked", commands <= linked_names, f"missing: {sorted(commands - linked_names)}")
    check("nothing outside the catalog is linked", linked_names <= commands,
          f"extra: {sorted(linked_names - commands)}")
    duplicated = sorted({name for name in linked_names
                         if sum(1 for path in tools_linked if path.name == name) > 1})
    check("each command is linked once", not duplicated, f"duplicated: {duplicated}")


def naming_finding() -> None:
    """Lint reports a command that lost its prefix, so the rule is enforced, not just documented."""
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary) / "repo"
        (root / ".agent" / "tools" / "task").mkdir(parents=True)
        (root / ".cursor" / "agents").mkdir(parents=True)
        (root / "rules").mkdir()
        script = root / ".agent" / "tools" / "task" / "log-progress.py"
        script.write_text("#!/usr/bin/env python3\n")
        script.chmod(0o755)
        (root / ".agent" / "tools" / "tools.json").write_text(json.dumps({
            "schema_version": 1,
            "tools": [{"name": "log-progress.py", "dir": "task", "kind": "command",
                       "category": "task", "owner": "crew-orchestrator",
                       "help": "argparse", "smoke": "--help"}],
            "scripts": [], "modules": [], "assets": [],
        }))
        result = subprocess.run([sys.executable, str(LINT), "--root", str(root)],
                                capture_output=True, text=True)
    check("unprefixed command fails lint", result.returncode == 1, result.stdout + result.stderr)
    check("lint reports command-name", ": command-name: " in result.stdout, result.stdout)


def main() -> int:
    catalog()
    parity()
    install_links()
    naming_finding()
    if FAILED:
        print(f"\n{len(FAILED)} failed")
        return 1
    print("\nall command-surface checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
