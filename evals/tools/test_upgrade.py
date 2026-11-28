#!/usr/bin/env python3
"""An upgrade from the previous release leaves every prompt reference resolvable.

The previous tree (`origin/main`, or `UPGRADE_FROM_REF`) is exported with `git archive` into a
temporary directory (no worktree is registered, so the main checkout's `.git` is untouched) and
installed into a fake HOME; then this tree's `install.sh` runs into the same HOME. Afterwards:

- every `crew-*` command, `~/.agent/bin/...`, `~/.cursor/skills/...`, `~/.cursor/agents/...` and `~/.claude/agents/...`
  path named in a prompt (rules, agents, skills, `.claude/CLAUDE.md`) resolves under the fake HOME, and
  every repo skill and agent file is installed for Claude Code and in the Cursor plugin;
- no registration of the previous layout is left: no hook under ~/.claude/hooks in settings.json or ~/.cursor/hooks.json,
  no link in ~/.cursor/rules;
- every command in the fake `~/.claude/settings.json` allow-list exists (a `~/` path under the fake
  HOME, a bare program on PATH unless listed in `EXTERNAL`);
- the generated `el-capitan:imports` block imports exactly the `.mdc` files `.claude/CLAUDE.md`
  imports, each one resolving (the Phase 1 import check), none of `FORBIDDEN_IMPORTS`, the `Read <path> before ...`
  pointer line that replaces each of those, and is printed so the report records it;
- every command in `NEW_COMMANDS` is allow-listed and runs through its installed link.

Every install runs with HOME set to the temporary directory; the real HOME's install surface is
fingerprinted before and after and must not change.
"""
from __future__ import annotations

import importlib.util
import json
import os
import re
import subprocess
from pathlib import Path

import pytest

# Two installs into one HOME (each allowed 300 s): more than the suite's 60 s per test.
pytestmark = pytest.mark.timeout(600)
ROOT = Path(__file__).resolve().parents[2]
PREVIOUS = os.environ.get("UPGRADE_FROM_REF", "origin/main")
# Bare programs in the allow-list that el-capitan does not install; each needs a reason.
EXTERNAL = {"agent-builder": "a user tool the allow-list pre-approves; not shipped here",
            "uuidgen": "optional (absent on ubuntu-latest); crew-specwriter falls back to python3 uuid"}
# Rules the always-on block must not charge every request for, each with the pointer that replaces it.
FORBIDDEN_IMPORTS = {"typescript.md": "~/.claude/el-capitan/typescript.md",
                     "prompt-engineering.mdc": "~/.cursor/skills/prompt-authoring/SKILL.md"}
PROMPT_GLOBS = ("rules/*.mdc", ".cursor/agents/**/*.md", ".cursor/skills/**/*.md", ".claude/CLAUDE.md")
HOME_PATH = re.compile(r"~/\.(?:agent/bin|cursor/skills|cursor/agents|claude/agents)/[A-Za-z0-9._/-]+")
BARE_COMMAND = re.compile(r"\bcrew-[a-z0-9-]+\.(?:py|sh)\b")
GIT_ID = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
          "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid"}
# Commands new in this release: each must be linked, run from the fake HOME, and be allow-listed.
NEW_COMMANDS = {"crew-task.py": ["normalize-status", "--tasks-dir", "{tasks}"], "crew-verify.py": ["--help"]}
REAL_SURFACE = (".claude/settings.json", ".claude/CLAUDE.md", ".cursor/hooks.json",
                ".codex/AGENTS.md", ".agent/bin", ".cursor/rules", ".cursor/skills", ".cursor/agents",
                ".claude/hooks")


def fingerprint(home: Path) -> dict[str, object]:
    """Names, link targets, sizes and mtimes of the install surface under one HOME."""
    seen: dict[str, object] = {}
    for rel in REAL_SURFACE:
        path = home / rel
        entries = sorted(path.iterdir()) if path.is_dir() and not path.is_symlink() else [path]
        for entry in entries:
            if entry.is_symlink():
                seen[str(entry)] = ("link", os.readlink(entry))
            elif entry.exists():
                stat = entry.stat()
                seen[str(entry)] = ("file", stat.st_size, stat.st_mtime_ns)
    return seen


def install(tree: Path, home: Path, cwd: Path) -> None:
    env = {**os.environ, **GIT_ID, "HOME": str(home)}
    for key in ("CREW_MEMORY_DIR", "CREW_JOURNAL_DIR", "CREW_TASK_DIR"):
        env.pop(key, None)
    done = subprocess.run(["bash", str(tree / "install.sh")], cwd=cwd, env=env,
                          capture_output=True, text=True, timeout=300)
    if done.returncode != 0:
        raise AssertionError(f"install from {tree} exited {done.returncode}\n{done.stdout[-1500:]}"
                         f"\n{done.stderr[-1500:]}")


def export_previous(destination: Path) -> None:
    destination.mkdir()
    archive = subprocess.run(["git", "-C", str(ROOT), "archive", PREVIOUS], capture_output=True)
    if archive.returncode != 0:
        raise AssertionError(f"cannot export {PREVIOUS} (fetch it, or set UPGRADE_FROM_REF): "
                         f"{archive.stderr.decode(errors='replace').strip()}")
    subprocess.run(["tar", "-x", "-C", str(destination)], input=archive.stdout, check=True)


def prompt_text() -> str:
    files = sorted({path for pattern in PROMPT_GLOBS for path in ROOT.glob(pattern)})
    return "\n".join(path.read_text(encoding="utf-8", errors="replace") for path in files)


def reference_failures(home: Path) -> list[str]:
    text, failures = prompt_text(), []
    for ref in sorted(set(HOME_PATH.findall(text))):
        ref = ref.rstrip(".,/")
        if ref.endswith("-"):  # a pattern such as `crew-<name>.md`, not a path
            continue
        if not (home / ref[2:]).exists():
            failures.append(f"prompt names {ref}, which does not resolve after the upgrade")
    for name in sorted(set(BARE_COMMAND.findall(text))):
        if not (home / ".agent" / "bin" / name).exists():
            failures.append(f"prompt names command {name}, missing from ~/.agent/bin")
    for skill in sorted((ROOT / ".cursor" / "skills").glob("*/SKILL.md")):
        if not (home / ".cursor" / "skills" / skill.parent.name / "SKILL.md").exists():
            failures.append(f"skill {skill.parent.name} is not installed")
    for agent in sorted((ROOT / ".cursor" / "agents").glob("*.md")):
        for place in (".claude/agents", ".cursor/plugins/local/el-capitan/agents"):
            if not (home / place / agent.name).exists():
                failures.append(f"agent {agent.name} is not installed in ~/{place}")
    return failures


def commands(data: object) -> list[str]:
    """Every `command` string in a hooks document, whatever its nesting."""
    if isinstance(data, dict):
        return [str(data.get("command"))] + [c for value in data.values() for c in commands(value)]
    return [c for value in data for c in commands(value)] if isinstance(data, list) else []


def test_every_registration_of_the_previous_release_is_retired() -> None:
    """Each hook command the previous release's templates registered is one `hooks_retirement.retired` drops, so an
    upgrade never keeps a registration whose script is gone."""
    spec = importlib.util.spec_from_file_location("hooks_retirement", ROOT / ".claude" / "hooks_retirement.py")
    assert spec is not None and spec.loader is not None
    retirement = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(retirement)
    found = []
    for name in (".claude/settings.template.json", ".cursor/hooks.template.json"):
        shown = subprocess.run(["git", "-C", str(ROOT), "show", f"{PREVIOUS}:{name}"], capture_output=True, text=True)
        found += commands(json.loads(shown.stdout)) if shown.returncode == 0 else []
    kept = [command for command in found if command != "None" and not retirement.retired(command)]
    assert not kept, kept


def legacy_failures(home: Path) -> list[str]:
    """What the previous layout registered is gone: hooks run through crew-hook.py only, no rule links in ~/.cursor."""
    failures = [f"{name} still registers a script under ~/.claude/hooks" for name in (".claude/settings.json", ".cursor/hooks.json")
                if (home / name).is_file() and any("/.claude/hooks/" in c for c in commands(json.loads((home / name).read_text(encoding="utf-8"))))]
    rules = home / ".cursor" / "rules"
    return failures + [f"{link} is left from the previous layout" for link in (sorted(rules.iterdir()) if rules.is_dir() else []) if link.is_symlink()]


def allow_list_failures(home: Path) -> list[str]:
    settings = json.loads((home / ".claude" / "settings.json").read_text(encoding="utf-8"))
    failures = []
    for rule in settings.get("permissions", {}).get("allow", []):
        match = re.fullmatch(r"Bash\(([^ )]+)[^)]*\)", rule)
        if not match:
            continue
        program = match.group(1)
        if program.startswith("~/"):
            if not (home / program[2:]).exists():
                failures.append(f"allow-list names {program}, missing after the upgrade")
        elif "/" not in program and program not in EXTERNAL and not runnable(program):
            failures.append(f"allow-list names {program}, which is neither a builtin nor on PATH")
    return failures


def allowed_programs(home: Path) -> set[str]:
    settings = json.loads((home / ".claude" / "settings.json").read_text(encoding="utf-8"))
    return {match.group(1) for rule in settings.get("permissions", {}).get("allow", [])
            if (match := re.fullmatch(r"Bash\(([^ )]+)[^)]*\)", rule))}


def new_command_failures(home: Path, tasks: Path) -> list[str]:
    """Each new command is allow-listed and runs through its installed link."""
    failures = [f"allow-list has no entry for {name}" for name in NEW_COMMANDS
                if f"~/.agent/bin/{name}" not in allowed_programs(home)]
    env = {**os.environ, "HOME": str(home)}
    for name, arguments in NEW_COMMANDS.items():
        argv = [str(home / ".agent" / "bin" / name), *[a.replace("{tasks}", str(tasks)) for a in arguments]]
        done = subprocess.run(argv, capture_output=True, text=True, env=env, timeout=60)
        if done.returncode != 0:
            failures.append(f"{name} {' '.join(arguments)} exited {done.returncode}: {done.stderr.strip()[-300:]}")
    return failures


def runnable(program: str) -> bool:
    """A bash builtin (`source`, `cd`) or a program on PATH."""
    found = subprocess.run(["bash", "-c", 'type -t "$1"', "bash", program], capture_output=True, text=True)
    return found.stdout.strip() in {"builtin", "file", "keyword"}


def imports_failures(home: Path) -> list[str]:
    text = (home / ".claude" / "CLAUDE.md").read_text(encoding="utf-8")
    block = re.search(r"<!-- el-capitan:imports -->.*?<!-- /el-capitan:imports -->", text, re.S)
    if not block:
        return ["the fake ~/.claude/CLAUDE.md has no el-capitan:imports block"]
    print("imports block:\n" + block.group(0))
    got = re.findall(r"^@(\S+)$", block.group(0), re.M)
    wanted = list(dict.fromkeys(re.findall(r"^@(\S+\.mdc?)$", (ROOT / ".claude" / "CLAUDE.md").read_text(), re.M)))
    failures = [] if got == wanted else [f"imports block {got} differs from .claude/CLAUDE.md {wanted}"]
    failures += [f"imports block names {item}, which does not resolve" for item in got if not (home / item[2:]).exists()]
    # A rule left out of the imports keeps a one-line pointer, so other repos still learn to read it.
    pointers = re.findall(r"^Read (\S+) before .+$", block.group(0), re.M)
    failures += [f"imports block has no pointer line for {name} ({pointer})"
                 for name, pointer in FORBIDDEN_IMPORTS.items() if pointer not in pointers]
    return failures + [f"imports block still imports {name}" for name in FORBIDDEN_IMPORTS
                       if any(item.endswith("/" + name) for item in got)]


def test_upgrade_from_the_previous_release(tmp: Path) -> None:
    real_home = Path.home()
    before = fingerprint(real_home)
    tmp = tmp.resolve()
    home, cwd, previous = tmp / "home", tmp / "cwd", tmp / "previous"
    home.mkdir()
    cwd.mkdir()
    export_previous(previous)
    install(previous, home, cwd)
    install(ROOT, home, cwd)
    (tmp / "tasks").mkdir()
    failures = (reference_failures(home) + legacy_failures(home) + allow_list_failures(home) + imports_failures(home)
                + new_command_failures(home, tmp / "tasks"))
    if fingerprint(real_home) != before:
        failures.append(f"the real HOME's install surface changed under {real_home}")
    assert not failures, "\n".join(failures)
