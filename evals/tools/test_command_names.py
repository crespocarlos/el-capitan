#!/usr/bin/env python3
"""Checks for the installed command surface: catalog kinds and install links.

Three properties, each with its own failure that no other suite covers:

- every catalog entry declares what it is (`command`, `module`, `asset`), and every command basename
  follows one rule, so the surface cannot drift back to 22 commands with four ad-hoc names;
- the naming rule is enforced by lint, not only documented, so an unprefixed command fails the gate;
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


def catalog() -> None:
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
        if not COMMAND_NAME.match(name):
            bad.append(name)
    check("every command basename is crew-<kebab>.(py|sh)", not bad, f"not renamed: {bad}")


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
        script = root / ".agent" / "tools" / "task" / "task-progress.py"
        script.write_text("#!/usr/bin/env python3\n")
        script.chmod(0o755)
        (root / ".agent" / "tools" / "tools.json").write_text(json.dumps({
            "schema_version": 1,
            "tools": [{"name": "task-progress.py", "dir": "task", "kind": "command",
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
    install_links()
    naming_finding()
    if FAILED:
        print(f"\n{len(FAILED)} failed")
        return 1
    print("\nall command-surface checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
