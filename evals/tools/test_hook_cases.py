#!/usr/bin/env python3
"""Table-driven guard cases, each run through every shell guard in both harness payload shapes.

A command is sent as Claude's `PreToolUse` (`tool_input.command`) and as Cursor's
`beforeShellExecution` (top-level `command`) to each script under `.claude/hooks/guard/`, under the
`bash` on PATH and under `/bin/bash` (bash 3.2 on macOS). The verdict is the join of the guards:
deny when any guard denies, allow when every guard is silent. A deny case also names the guard that
must be among the deniers; an allow case fails on any output at all, so an internal error that
prints a line or exits nonzero fails the allow corpus as surely as a wrong denial. Only a
missing-tool row is `loose`: its allow may carry one stderr line, and Cursor's must be `{}`.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from hook_cases import ALLOW, DENY, MISSING, OFF, PAYLOADS, SECRET

ROOT = Path(__file__).resolve().parents[2]
GUARDS = sorted((ROOT / ".claude" / "hooks" / "guard").glob("*.sh"))
GIT_ID = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid"}


def git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, env={**os.environ, **GIT_ID})


def repository(path: Path, files: dict[str, str]) -> Path:
    """A repository on `main` with `files` committed."""
    path.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", "-b", "main", str(path)], check=True)
    for name, text in {"base.txt": "base\n", **files}.items():
        (path / name).parent.mkdir(parents=True, exist_ok=True)
        (path / name).write_text(text, encoding="utf-8")
        git(path, "add", name)
    git(path, "commit", "-qm", "base")
    return path


def fixture(home: Path) -> dict[str, Path]:
    trees = {name: repository(home / name, {}) for name in ("clean", "locked", "stale", "detached")}
    trees["source"] = repository(home / "source", {"tracked.txt": "one\n", "src/pull/handler.ts": "x\n"})
    trees["large"] = repository(home / "large", {})
    (trees["large"] / "big.txt").write_text("".join(f"{n}\n" for n in range(40000)), encoding="utf-8")
    git(trees["large"], "add", "big.txt")
    trees["addable"] = repository(home / "addable", {})
    (trees["addable"] / "notes.txt").write_text("plain notes\n", encoding="utf-8")
    trees["leaky"] = repository(home / "leaky", {"config.txt": "a=1\n"})
    (trees["leaky"] / "leak.txt").write_text(SECRET + "\n", encoding="utf-8")
    (trees["leaky"] / "config.txt").write_text(SECRET + "\n", encoding="utf-8")
    trees["loose"] = repository(home / "loose", {})
    (trees["loose"] / ".env.local").write_text(SECRET + "\n", encoding="utf-8")
    (trees["loose"] / "base.txt").write_text("changed\n", encoding="utf-8")
    trees["corrupt"] = repository(home / "corrupt", {})
    (trees["corrupt"] / ".git" / "index").write_bytes(b"not an index")
    git(trees["detached"], "checkout", "-q", "--detach", "HEAD")
    git(trees["clean"], "remote", "add", "upstream", "https://example.invalid/upstream.git")
    for name, age in (("locked", 60), ("stale", 7 * 3600)):
        (trees[name] / ".crew-worker.lock").write_text(f"task=T-1\nstarted={int(time.time()) - age}\n")
    trees["nogit"] = home / "nogit"
    trees["nogit"].mkdir()
    return trees


def classify(claude: bool, code: int, out: str, err: str, loose: bool = False) -> str:
    if loose and code == 0 and len(err.splitlines()) <= 1 and out == ("" if claude else "{}"):
        return "allow"
    if claude and code == 2 and len(err.splitlines()) == 1 and not out:
        return "deny"
    if claude and (code, out, err) == (0, "", ""):
        return "allow"
    if not claude and code == 0 and not err and out in ("", "{}"):
        return "allow"
    if not claude and code == 0 and not err and out.startswith("{"):
        return "deny" if json.loads(out).get("permission") == "deny" else "unknown"
    return "unknown"


def run_guard(bash: str, guard: Path, row: dict, env: dict) -> str:
    """`deny`, `allow`, or `error: ...` for one guard run in one shape; a deny names its off switch."""
    done = subprocess.run([bash, str(guard)], input=json.dumps(row["payload"]), capture_output=True,
                          text=True, env=env, cwd=str(row["cwd"]), timeout=120)
    out, err = done.stdout.strip(), done.stderr.strip()
    claude = row["payload"].get("hook_event_name") == "PreToolUse"
    verdict = classify(claude, done.returncode, out, err, row.get("loose", False))
    switch = "EL_CAPITAN_GUARD_" + guard.stem.upper().replace("-", "_") + "=off"
    if verdict == "deny" and not (switch in out + err and "EL_CAPITAN_GUARDS=off" in out + err):
        return f"error: {guard.name} denies without naming {switch} and EL_CAPITAN_GUARDS=off"
    if verdict != "unknown":
        return verdict
    return f"error: {guard.name} exit {done.returncode} stdout={out[:200]!r} stderr={err[:300]!r}"


def shapes(command: str, cwd: Path) -> list[dict]:
    return [{"session_id": "s", "hook_event_name": "PreToolUse", "tool_name": "Bash",
             "tool_input": {"command": command}, "cwd": str(cwd)},
            {"hook_event_name": "beforeShellExecution", "command": command, "cwd": str(cwd)}]


def path_without(home: Path, tool: str) -> str:
    """Every executable on PATH except `tool`, linked into one directory."""
    shim = home / f"no-{tool}-bin"
    shim.mkdir()
    for directory in filter(os.path.isdir, os.environ.get("PATH", "").split(os.pathsep) + ["/usr/bin", "/bin"]):
        for entry in os.listdir(directory):
            target = os.path.join(directory, entry)
            if entry != tool and not (shim / entry).exists() and os.access(target, os.X_OK):
                (shim / entry).symlink_to(target)
    return str(shim)


def expand(command: str, trees: dict[str, Path]) -> str:
    for name, path in trees.items():
        command = command.replace("{" + name + "}", str(path))
    return command


def rows_for(kind: str, table: list, trees: dict[str, Path], env: dict, guards: list) -> list[dict]:
    rows = []
    for command, tree, by in table:
        for payload in shapes(expand(command, trees), trees[tree]):
            rows.append({"label": f"{kind} {command[:70]!r} in {tree}", "payload": payload,
                         "cwd": trees[tree], "by": by, "env": env, "guards": guards})
    return rows


def cases(home: Path, trees: dict[str, Path]) -> list[dict]:
    """One row per table entry and payload shape: what to send, where, and what must come back."""
    rows = rows_for("deny", DENY, trees, {}, GUARDS)
    rows += rows_for("allow", [(command, tree, None) for command, tree in ALLOW], trees, {}, GUARDS)
    credentials = [guard for guard in GUARDS if guard.stem == "credentials"]
    paths = {tool: path_without(home, tool) for tool in sorted({case[2] for case in MISSING})}
    for command, tree, tool, env, by in MISSING:
        found = rows_for(f"no-{tool} {env}", [(command, tree, by)], trees, {**env, "PATH": paths[tool]}, credentials)
        rows += [{**row, "loose": True} for row in found]
    for command, tree, env, by in OFF:
        rows += rows_for(f"off {env}", [(command, tree, by)], trees, env, GUARDS)
    for label, claude, cursor in PAYLOADS:
        rows += [{"label": f"allow payload {label}", "payload": payload, "cwd": trees["nogit"],
                  "by": None, "env": {}, "guards": GUARDS} for payload in (claude, cursor)]
    return rows


def failure(row: dict, verdicts: dict[str, str]) -> str:
    where = f"{row['label']} [{row['payload'].get('hook_event_name')}]"
    errors = [v for v in verdicts.values() if v.startswith("error")]
    deniers = sorted(name for name, v in verdicts.items() if v == "deny")
    if errors:
        return f"{where}: {errors[0]}"
    if row["by"] is None and deniers:
        return f"{where}: denied by {deniers}"
    if row["by"] is not None and row["by"] not in deniers:
        return f"{where}: expected a deny from {row['by']}, got {deniers or 'allow'}"
    return ""


def bashes() -> list[str]:
    found = [shutil.which("bash") or "/bin/bash", "/bin/bash"]
    unique = {os.path.realpath(path): path for path in found if os.path.exists(path)}
    return sorted(unique.values())


def judge(job: tuple[str, dict], env: dict) -> str:
    bash, row = job
    verdicts = {guard.stem: run_guard(bash, guard, row, {**env, **row["env"]}) for guard in row["guards"]}
    found = failure(row, verdicts)
    return f"{bash}: {found}" if found else ""


def main() -> int:
    home = Path(tempfile.mkdtemp(prefix="hook-cases-")).resolve()
    env = {**os.environ, **GIT_ID, "HOME": str(home), "SHELL": "/bin/zsh"}
    for key in [k for k in env if k.startswith(("CREW_", "EL_CAPITAN_"))]:
        env.pop(key)
    try:
        rows = cases(home, fixture(home))
        jobs = [(bash, row) for bash in bashes() for row in rows]
        with ThreadPoolExecutor(max_workers=max(4, (os.cpu_count() or 2) * 2)) as pool:
            failures = [line for line in pool.map(lambda job: judge(job, env), jobs) if line]
    finally:
        shutil.rmtree(home, ignore_errors=True)
    for line in failures:
        print(f"FAIL: {line}")
    if failures:
        print(f"fail: {len(failures)} of {len(jobs)} case run(s)")
        return 1
    print(f"pass: {len(DENY)} deny, {len(ALLOW)} allow, {len(MISSING)} missing-tool, {len(OFF)} off-switch and "
          f"{len(PAYLOADS)} payload case(s), {len(GUARDS)} guards, both shapes, under {', '.join(bashes())}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
