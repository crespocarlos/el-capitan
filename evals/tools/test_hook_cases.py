#!/usr/bin/env python3
"""Every hook's contract, table-driven, in both harness payload shapes and under both bashes.

A shell command is sent as Claude's `PreToolUse` (`tool_input.command`) and as Cursor's
`beforeShellExecution` (top-level `command`) to each script under `.claude/hooks/guard/`; a file write
as `PreToolUse` and Cursor's `preToolUse` to each `Write|Edit` hook. Each runs under the `bash` on PATH
and under `/bin/bash` (bash 3.2 on macOS). The verdict is the join of the hooks: deny when any denies,
allow when every one is silent. A deny names its off switches and the hook that must be among the
deniers; an allow fails on any output at all, so an internal error fails the allow corpus as surely as
a wrong denial. Then every hook, the silent ones included, must survive unreadable input and a missing
`jq` with exit 0 and at most one stderr line, and every hook file must be classified here.
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

from hook_cases import ALLOW, DENY, ENV, FILES, MESSAGES, MISSING, PAYLOADS, SECRET, SILENT

ROOT = Path(__file__).resolve().parents[2]
HOOKS = ROOT / ".claude" / "hooks"
GUARDS = sorted((HOOKS / "guard").glob("*.sh"))
FILE_HOOKS = [HOOKS / "check-write-boundary.sh", HOOKS / "check-task-spec-owner.sh"]
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


def stage(repo: Path, name: str, text: str) -> None:
    (repo / name).write_text(text, encoding="utf-8")
    git(repo, "add", name)


def fixture(home: Path) -> dict[str, Path]:
    trees = {name: repository(home / name, {}) for name in ("clean", "locked", "stale", "detached", "large", "addable", "staged",
                                                            "bigleak", "loose", "corrupt")}
    trees["source"] = repository(home / "source", {"tracked.txt": "one\n", "src/pull/handler.ts": "x\n"})
    trees["source-sub"] = trees["source"] / "src" / "pull"
    big = "".join(f"{n}\n" for n in range(40000))
    stage(trees["large"], "big.txt", big)
    (trees["addable"] / "notes.txt").write_text("plain notes\n", encoding="utf-8")
    trees["leaky"] = repository(home / "leaky", {"config.txt": "a=1\n"})
    (trees["leaky"] / "leak.txt").write_text(SECRET + "\n", encoding="utf-8")
    (trees["leaky"] / "config.txt").write_text(SECRET + "\n", encoding="utf-8")
    stage(trees["staged"], "leak.txt", SECRET + "\n")
    stage(trees["bigleak"], "c.txt", SECRET + "\n" + big)
    (trees["loose"] / ".env.local").write_text(SECRET + "\n", encoding="utf-8")
    (trees["loose"] / "base.txt").write_text("changed\n", encoding="utf-8")
    (trees["corrupt"] / ".git" / "index").write_bytes(b"not an index")
    git(trees["detached"], "checkout", "-q", "--detach", "HEAD")
    git(trees["clean"], "remote", "add", "upstream", "https://example.invalid/upstream.git")
    for name, age in (("locked", 60), ("stale", 7 * 3600)):
        (trees[name] / ".crew-worker.lock").write_text(f"task=T-1\nstarted={int(time.time()) - age}\n")
    trees["nogit"] = home / "nogit"
    trees["nogit"].mkdir()
    tasks = home / ".agent" / "tasks"
    for name, slug in (("AAA-other", "align-agent-tool-frontmatter"), ("CCC-fresh", "cut-duplicated-is-it-normal-work-in-discovery-and-")):
        (tasks / name).mkdir(parents=True)
        (tasks / name / ".task-id").write_text(json.dumps({"slug": slug}), encoding="utf-8")
    (tasks / "AAA-other" / "SPEC.md").write_text("# Spec: Align agent tool frontmatter\n", encoding="utf-8")
    (tasks / "BBB-new").mkdir()
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


def run(bash: str, hook: Path, stdin: str, env: dict, cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run([bash, str(hook)], input=stdin, capture_output=True, text=True, env=env, cwd=str(cwd), timeout=120)


def run_guard(bash: str, guard: Path, row: dict, env: dict) -> str:
    """`deny`, `allow`, or `error: ...` for one hook run in one shape; a deny names its off switches."""
    done = run(bash, guard, json.dumps(row["payload"]), env, row["cwd"])
    out, err = done.stdout.strip(), done.stderr.strip()
    claude = row["payload"].get("hook_event_name") == "PreToolUse"
    verdict = classify(claude, done.returncode, out, err, row.get("loose", False))
    switch = "EL_CAPITAN_GUARD_" + guard.stem.upper().replace("-", "_") + "=off"
    if verdict == "deny" and not (switch in out + err and "EL_CAPITAN_GUARDS=off" in out + err):
        return f"error: {guard.name} denies without naming {switch} and EL_CAPITAN_GUARDS=off"
    says, never = MESSAGES.get(guard.stem, ((), ()))
    if verdict == "deny" and row["by"] == guard.stem and (any(text not in out + err for text in says) or any(text in out + err for text in never)):
        return f"error: {guard.name} denial must say {says} and never {never}: {(out + err)[:300]!r}"
    if verdict != "unknown":
        return verdict
    return f"error: {guard.name} exit {done.returncode} stdout={out[:200]!r} stderr={err[:300]!r}"


def shapes(command: str, cwd: Path) -> list[dict]:
    return [{"session_id": "s", "hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {"command": command}, "cwd": str(cwd)},
            {"hook_event_name": "beforeShellExecution", "command": command, "cwd": str(cwd)}]


def file_shapes(fields: dict, cwd: Path) -> list[dict]:
    return [{"hook_event_name": "PreToolUse", "tool_name": "Write", "tool_input": fields, "cwd": str(cwd)},
            {"hook_event_name": "preToolUse", "tool_name": "Write", **fields, "cwd": str(cwd)}]


def path_without(home: Path, tool: str) -> str:
    """Every executable on PATH except `tool`, linked into one directory."""
    shim = home / f"no-{tool}-bin"
    if shim.is_dir():
        return str(shim)
    shim.mkdir()
    for directory in filter(os.path.isdir, os.environ.get("PATH", "").split(os.pathsep) + ["/usr/bin", "/bin"]):
        for entry in os.listdir(directory):
            target = os.path.join(directory, entry)
            if entry != tool and not (shim / entry).exists() and os.access(target, os.X_OK):
                (shim / entry).symlink_to(target)
    return str(shim)


def expand(text: str, places: dict[str, Path]) -> str:
    for name, path in places.items():
        text = text.replace("{" + name + "}", str(path))
    return text


def rows_for(kind: str, table: list, places: dict[str, Path], env: dict, guards: list) -> list[dict]:
    rows = []
    for command, tree, by in table:
        for payload in shapes(expand(command, places), places[tree]):
            rows.append({"label": f"{kind} {command[:70]!r} in {tree}", "payload": payload, "cwd": places[tree], "by": by, "env": env,
                         "guards": guards})
    return rows


def cases(home: Path, places: dict[str, Path]) -> list[dict]:
    """One row per table entry and payload shape: what to send, where, and what must come back."""
    rows = rows_for("deny", DENY, places, {}, GUARDS)
    rows += rows_for("allow", [(command, tree, None) for command, tree in ALLOW], places, {}, GUARDS)
    credentials = [guard for guard in GUARDS if guard.stem == "credentials"]
    paths = {tool: path_without(home, tool) for tool in sorted({case[2] for case in MISSING})}
    for command, tree, tool, env, by in MISSING:
        found = rows_for(f"no-{tool} {env}", [(command, tree, by)], places, {**env, "PATH": paths[tool]}, credentials)
        rows += [{**row, "loose": True} for row in found]
    for command, tree, env, by in ENV:
        rows += rows_for(f"env {env}", [(command, tree, by)], places, env, GUARDS)
    for label, claude, cursor in PAYLOADS:
        rows += [{"label": f"allow payload {label}", "payload": payload, "cwd": places["nogit"], "by": None, "env": {}, "guards": GUARDS}
                 for payload in (claude, cursor)]
    for fields, tree, by in FILES:
        filled = {key: expand(value, places) for key, value in fields.items()}
        rows += [{"label": f"file {fields}", "payload": payload, "cwd": places[tree], "by": by, "env": {}, "guards": FILE_HOOKS}
                 for payload in file_shapes(filled, places[tree])]
    # A deny row asks only the guard that must deny; the allow rows run every guard over every parser path.
    return [{**row, "guards": [g for g in row["guards"] if g.stem == row["by"]]} if row["by"] else row for row in rows]


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


def unreadable(job: tuple[str, Path, str, str], env: dict, places: dict[str, Path]) -> str:
    """A hook that cannot read its input or lacks `jq` reports one line and gets out of the way."""
    bash, hook, label, stdin = job
    blocking = hook.parent.name == "guard" or hook in FILE_HOOKS
    run_env = {**env, "PATH": places[label.replace(" ", "-")]} if label in ("no jq", "no awk") else env
    done = run(bash, hook, stdin, run_env, places["nogit"])
    lines = len(done.stderr.strip().splitlines())
    quiet = done.stdout.strip() in (("", "{}") if hook.stem == "credentials" and label != "no jq" else ("",))
    ok = done.returncode == 0 and (lines == 1 and quiet if blocking else lines <= 1)
    if label == "no awk":  # a hook that needs awk says so in one line; one that does not judges as usual (2 is a deny)
        ok = done.returncode in (0, 2) and lines <= 1 and "not found" not in done.stderr
    if ok:
        return ""
    return f"{bash}: {hook.name} {label}: exit {done.returncode} stdout={done.stdout[:200]!r} stderr={done.stderr[:300]!r}"


def failure_jobs() -> list[tuple[str, Path, str, str]]:
    probe = json.dumps({"hook_event_name": "PreToolUse", "tool_input": {"command": "git reset --hard", "file_path": "/outside/file"}})
    hooks = GUARDS + FILE_HOOKS + [HOOKS / name for name in SILENT]
    inputs = (("malformed JSON", "{not json"), ("empty input", ""), ("no jq", probe), ("no awk", probe))
    return [(bash, hook, label, stdin) for bash in bashes() for hook in hooks for label, stdin in inputs]


def unclassified() -> list[str]:
    known = {path.name for path in FILE_HOOKS} | set(SILENT)
    present = {path.name for path in HOOKS.glob("*.sh")}
    return [f"unclassified hook: {name}" for name in sorted(present - known)] + [f"missing hook: {name}" for name in sorted(known - present)]


def shell_choice(env: dict) -> list[str]:
    """The zsh rule follows the executing shell: Cursor's event always means zsh, Claude's follows `$SHELL`
    (bash reads `=` as text), and with no SHELL at all it still decides rather than aborting under `set -u`."""
    guard, found = HOOKS / "guard" / "zsh-equals.sh", []
    cursor = json.dumps({"hook_event_name": "beforeShellExecution", "command": "echo ====="})
    claude = json.dumps({"hook_event_name": "PreToolUse", "tool_input": {"command": "echo ====="}})
    bash_claude = run("bash", guard, claude, {**env, "SHELL": "/bin/bash"}, ROOT)
    if (bash_claude.returncode, bash_claude.stdout, bash_claude.stderr) != (0, "", ""):
        found.append(f"SHELL=/bin/bash, Claude: expected a silent allow, got {bash_claude}")
    bare = {key: value for key, value in env.items() if key != "SHELL"}
    unset_cursor, unset_claude = run("bash", guard, cursor, bare, ROOT), run("bash", guard, claude, bare, ROOT)
    if not (unset_cursor.returncode == 0 and '"deny"' in unset_cursor.stdout):
        found.append(f"unset SHELL, Cursor: expected the JSON deny, got {unset_cursor}")
    return found + ([] if unset_claude.returncode in (0, 2) else [f"unset SHELL, Claude: exit {unset_claude.returncode}"])


def bashes() -> list[str]:
    found = [shutil.which("bash") or "/bin/bash", "/bin/bash"]
    unique = {os.path.realpath(path): path for path in found if os.path.exists(path)}
    return sorted(unique.values())


def judge(job: tuple[str, dict], env: dict) -> str:
    bash, row = job
    verdicts = {guard.stem: run_guard(bash, guard, row, {**env, **row["env"]}) for guard in row["guards"]}
    found = failure(row, verdicts)
    return f"{bash}: {found}" if found else ""


def fixture_home() -> Path:
    """A home outside every root the write boundary permits ($HOME/.agent, .claude, .cursor and /tmp).

    A bare `mkdtemp` lands under /tmp on Linux, where `<repo>/../outside.md` is allowed by the /tmp rule
    and the escape cases stop meaning anything, so the home then goes under `~/.cache` instead.
    """
    base, temp, slash_tmp = None, Path(tempfile.gettempdir()).resolve(), Path("/tmp").resolve()
    if temp == slash_tmp or slash_tmp in temp.parents:
        base = Path.home() / ".cache" / "el-capitan-fixtures"
        base.mkdir(parents=True, exist_ok=True)
    return Path(tempfile.mkdtemp(prefix="hook-cases-", dir=base)).resolve()


def main() -> int:
    home = fixture_home()
    tmp = home / "tmp"
    tmp.mkdir()
    env = {**os.environ, **GIT_ID, "HOME": str(home), "SHELL": "/bin/zsh", "TMPDIR": str(tmp), "GIT_CEILING_DIRECTORIES": str(home.parent)}
    for key in [k for k in env if k.startswith(("CREW_", "EL_CAPITAN_"))]:
        env.pop(key)
    try:
        places: dict[str, Path] = {**fixture(home), "home": home, "tmp": tmp, "tasks": home / ".agent" / "tasks"}
        review = subprocess.run([sys.executable, str(ROOT / ".agent/tools/review/crew-review-findings.py"), "review-dir", "--repo", "boundary-probe"],
                                capture_output=True, text=True, env=env)
        places["review"] = Path(review.stdout.strip())
        if review.returncode != 0 or not review.stdout.strip() or not places["review"].is_absolute():
            print(f"FAIL: review-dir must print an absolute path (exit {review.returncode}): {review.stdout}{review.stderr}")
            return 1
        rows = cases(home, places)
        places["no-jq"], places["no-awk"] = Path(path_without(home, "jq")), Path(path_without(home, "awk"))
        jobs = [(bash, row) for bash in bashes() for row in rows]
        failed = unclassified() + shell_choice(env)
        with ThreadPoolExecutor(max_workers=max(4, (os.cpu_count() or 2) * 2)) as pool:
            failed += [line for line in pool.map(lambda job: judge(job, env), jobs) if line]
            failed += [line for line in pool.map(lambda job: unreadable(job, env, {k: str(v) for k, v in places.items()}), failure_jobs()) if line]
    finally:
        shutil.rmtree(home, ignore_errors=True)
    for line in failed:
        print(f"FAIL: {line}")
    if failed:
        print(f"fail: {len(failed)} of {len(jobs) + len(failure_jobs())} case run(s)")
        return 1
    print(f"pass: {len(DENY)} deny, {len(ALLOW)} allow, {len(MISSING)} missing-tool, {len(ENV)} environment, {len(FILES)} file and "
          f"{len(PAYLOADS)} payload case(s); {len(GUARDS) + len(FILE_HOOKS) + len(SILENT)} hooks survive bad input; both shapes, under "
          f"{', '.join(bashes())}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
