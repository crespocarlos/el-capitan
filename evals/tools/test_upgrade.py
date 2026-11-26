#!/usr/bin/env python3
"""An upgrade from the previous release leaves every prompt reference resolvable.

The previous tree (`origin/main`, or `UPGRADE_FROM_REF`) is exported with `git archive` into a
temporary directory (no worktree is registered, so the main checkout's `.git` is untouched) and
installed into a fake HOME; then this tree's `install.sh` runs into the same HOME. Afterwards:

- every `crew-*` command, `~/.agent/bin/...`, `~/.cursor/skills/...` and `~/.cursor/agents/...` path
  named in a prompt (rules, agents, skills, `.claude/CLAUDE.md`) resolves under the fake HOME, and
  every repo skill and agent file is installed;
- every command in the fake `~/.claude/settings.json` allow-list exists (a `~/` path under the fake
  HOME, a bare program on PATH unless listed in `EXTERNAL`);
- the generated `el-capitan:imports` block imports exactly the `.mdc` files `.claude/CLAUDE.md`
  imports, none of `FORBIDDEN_IMPORTS`, a `Read ~/.cursor/rules/<name> before ...` pointer line for
  each of those, and is printed so the report records it.

Every install runs with HOME set to the temporary directory; the real HOME's install surface is
fingerprinted before and after and must not change.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PREVIOUS = os.environ.get("UPGRADE_FROM_REF", "origin/main")
# Bare programs in the allow-list that el-capitan does not install; each needs a reason.
EXTERNAL = {"agent-builder": "a user tool the allow-list pre-approves; not shipped here"}
# Glob-scoped rules the always-on block must not charge every request for (prompt-engineering.mdc
# joins in Phase D, when it becomes a skill).
FORBIDDEN_IMPORTS: tuple[str, ...] = ("typescript.mdc",)
PROMPT_GLOBS = ("rules/*.mdc", ".cursor/agents/**/*.md", ".cursor/skills/**/*.md", ".claude/CLAUDE.md")
HOME_PATH = re.compile(r"~/\.(?:agent/bin|cursor/skills|cursor/agents)/[A-Za-z0-9._/-]+")
BARE_COMMAND = re.compile(r"\bcrew-[a-z0-9-]+\.(?:py|sh)\b")
GIT_ID = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
          "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid"}
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
        raise SystemExit(f"FAIL: install from {tree} exited {done.returncode}\n{done.stdout[-1500:]}"
                         f"\n{done.stderr[-1500:]}")


def export_previous(destination: Path) -> None:
    destination.mkdir()
    archive = subprocess.run(["git", "-C", str(ROOT), "archive", PREVIOUS], capture_output=True)
    if archive.returncode != 0:
        raise SystemExit(f"FAIL: cannot export {PREVIOUS} (fetch it, or set UPGRADE_FROM_REF): "
                         f"{archive.stderr.decode(errors='replace').strip()}")
    subprocess.run(["tar", "-x", "-C", str(destination)], input=archive.stdout, check=True)


def prompt_text() -> str:
    files = sorted({path for pattern in PROMPT_GLOBS for path in ROOT.glob(pattern)})
    return "\n".join(path.read_text(encoding="utf-8", errors="replace") for path in files)


def reference_failures(home: Path) -> list[str]:
    text, failures = prompt_text(), []
    for ref in sorted(set(HOME_PATH.findall(text))):
        ref = ref.rstrip(".,/")
        if not (home / ref[2:]).exists():
            failures.append(f"prompt names {ref}, which does not resolve after the upgrade")
    for name in sorted(set(BARE_COMMAND.findall(text))):
        if not (home / ".agent" / "bin" / name).exists():
            failures.append(f"prompt names command {name}, missing from ~/.agent/bin")
    for skill in sorted((ROOT / ".cursor" / "skills").glob("*/SKILL.md")):
        if not (home / ".cursor" / "skills" / skill.parent.name / "SKILL.md").exists():
            failures.append(f"skill {skill.parent.name} is not installed")
    for agent in sorted((ROOT / ".cursor" / "agents").glob("*.md")):
        if not (home / ".cursor" / "agents" / agent.name).exists():
            failures.append(f"agent {agent.name} is not installed")
    return failures


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
    wanted = list(dict.fromkeys(re.findall(r"@(\S+\.mdc)", (ROOT / ".claude" / "CLAUDE.md").read_text())))
    failures = [] if got == wanted else [f"imports block {got} differs from .claude/CLAUDE.md {wanted}"]
    # A rule left out of the imports keeps a one-line pointer, so other repos still learn to read it.
    pointers = re.findall(r"^Read ~/\.cursor/rules/(\S+\.mdc) before .+$", block.group(0), re.M)
    failures += [f"imports block has no pointer line for {name}" for name in FORBIDDEN_IMPORTS if name not in pointers]
    return failures + [f"imports block still imports {name}" for name in FORBIDDEN_IMPORTS
                       if any(item.endswith("/" + name) for item in got)]


def main() -> int:
    real_home = Path.home()
    before = fingerprint(real_home)
    tmp = Path(tempfile.mkdtemp(prefix="upgrade-")).resolve()
    try:
        home, cwd, previous = tmp / "home", tmp / "cwd", tmp / "previous"
        home.mkdir()
        cwd.mkdir()
        export_previous(previous)
        install(previous, home, cwd)
        install(ROOT, home, cwd)
        failures = reference_failures(home) + allow_list_failures(home) + imports_failures(home)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    if fingerprint(real_home) != before:
        failures.append(f"the real HOME's install surface changed under {real_home}")
    for failure in failures:
        print(f"FAIL: {failure}")
    if failures:
        return 1
    print(f"pass: upgrade from {PREVIOUS} resolves every prompt reference and allow-list command")
    return 0


if __name__ == "__main__":
    sys.exit(main())
