#!/usr/bin/env python3
"""Every hook's contract, table-driven, in both harness payload shapes and under both bashes.

A shell command is sent as Claude's `PreToolUse` (`tool_input.command`) and as Cursor's
`beforeShellExecution` (top-level `command`) to each script under `.claude/hooks/guard/`; a file write
as `PreToolUse` and Cursor's `preToolUse` to each `Write|Edit` hook. Each runs under the `bash` on PATH
and under `/bin/bash` (bash 3.2 on macOS). The verdict is the join of the hooks: deny when any denies,
allow when every one is silent. A deny names its off switches and the hook that must be among the
deniers; an allow fails on any output at all, so an internal error fails the allow corpus as surely as
a wrong denial. Every shell row also runs through both parsers of `hook_segments`: with `shfmt` on
PATH and with PATH stripped of it (the awk fallback), and both must give the expected verdict, so they
agree except on the rows `PARSERS_DIFFER` lists with a reason. Then every hook, the silent ones
included, must survive unreadable input and a missing `jq` with exit 0 and at most one stderr line,
and every hook file must be classified here. `notify-idle.sh` runs the `NOTIFY` rows under a stub
`osascript` that logs its calls.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from hook_cases import (
    ALLOW,
    DENY,
    ENV,
    FILES,
    MESSAGES,
    MISSING,
    NOTIFY,
    PARSERS_DIFFER,
    PAYLOADS,
    PROBE,
    PROBE_VALUES,
    SECRET,
    SILENT,
    STATUS_SPEC,
)

ROOT = Path(__file__).resolve().parents[2]
HOOKS = ROOT / ".claude" / "hooks"
GUARDS = sorted((HOOKS / "guard").glob("*.sh"))
FILE_HOOKS = [HOOKS / "check-write-boundary.sh", HOOKS / "check-task-spec-owner.sh"]
# A hook run may take up to 120 s on a loaded runner (`run`), so these tests get more than the suite's 60 s.
pytestmark = pytest.mark.timeout(300)
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
    trees["ctrlleak"] = repository(home / "ctrlleak", {})
    (trees["ctrlleak"] / "\x1f").mkdir()
    stage(trees["ctrlleak"], "\x1f/leak.txt", SECRET + "\n")
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
    (tasks / "DDD-status").mkdir()
    (tasks / "DDD-status" / ".task-id").write_text(json.dumps({"slug": "status-guard"}), encoding="utf-8")
    (tasks / "DDD-status" / "SPEC.md").write_text(STATUS_SPEC, encoding="utf-8")
    (home / "linked-task").symlink_to(tasks / "DDD-status")
    # The config dirs an install recorded: a background job's scratch directory under one of them is writable.
    # An entry outside `$HOME/.claude*` (here a plain directory of the home) counts for nothing.
    manifest = {"config_dirs": [str(home / ".claude"), str(home / ".claude-work"), str(home / "elsewhere")]}
    (home / ".agent" / "install-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
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
    """Both payload shapes; the tool is the row's `tool_name`, else the one whose fields the row carries."""
    fields = dict(fields)
    tool = fields.pop("tool_name", None) or ("MultiEdit" if "edits" in fields else "Edit" if "old_string" in fields else "Write")
    return [{"hook_event_name": "PreToolUse", "tool_name": tool, "tool_input": fields, "cwd": str(cwd)},
            {"hook_event_name": "preToolUse", "tool_name": tool, **fields, "cwd": str(cwd)}]


def path_without(home: Path, *tools: str) -> str:
    """PATH with `tools` removed: a directory that holds one of them is replaced by a copy of its links
    without it, and every other directory stays as it is (built once, before any thread runs)."""
    entries = []
    for directory in filter(os.path.isdir, os.environ.get("PATH", "").split(os.pathsep) + ["/usr/bin", "/bin"]):
        if not any(os.path.exists(os.path.join(directory, tool)) for tool in tools):
            entries.append(directory)
            continue
        shim = home / "shims" / (directory.strip("/").replace("/", "-") + "-no-" + "-".join(sorted(tools)))
        if not shim.is_dir():
            shim.mkdir(parents=True)
            for entry in os.listdir(directory):
                if entry not in tools:
                    (shim / entry).symlink_to(os.path.join(directory, entry))
        entries.append(str(shim))
    return os.pathsep.join(entries)


def parsers() -> list[str]:
    """Both parsers of `hook_segments`; without shfmt installed only awk runs locally, and CI must have it."""
    if shutil.which("shfmt"):
        return ["shfmt", "awk"]
    assert not os.environ.get("CI"), "CI installs shfmt so the shfmt parser path runs"
    return ["awk"]


def expand(text: str, places: dict[str, Path]) -> str:
    for name, path in places.items():
        text = text.replace("{" + name + "}", str(path))
    return text


def rows_for(kind: str, table: list, places: dict[str, Path], env: dict, guards: list) -> list[dict]:
    rows = []
    for command, tree, by in table:
        for payload in shapes(expand(command, places), places[tree]):
            rows.append({"label": f"{kind} {command[:70]!r} in {tree}", "payload": payload, "cwd": places[tree], "by": by, "env": env,
                         "guards": guards, "command": expand(command, places)})
    return rows


def cases(home: Path, places: dict[str, Path]) -> list[dict]:
    """One row per table entry and payload shape: what to send, where, and what must come back."""
    rows = rows_for("deny", DENY, places, {}, GUARDS)
    rows += rows_for("allow", [(command, tree, None) for command, tree in ALLOW], places, {}, GUARDS)
    for command, tree, by, awk_by, _ in PARSERS_DIFFER:
        rows += [{**row, "awk_by": awk_by} for row in rows_for("parsers differ", [(command, tree, by)], places, {}, GUARDS)]
    credentials = [guard for guard in GUARDS if guard.stem == "credentials"]
    for command, tree, tool, env, by in MISSING:
        found = rows_for(f"no-{tool} {env}", [(command, tree, by)], places, env, credentials)
        rows += [{**row, "loose": True, "missing": (tool,)} for row in found]
    for command, tree, env, by in ENV:
        rows += rows_for(f"env {env}", [(command, tree, by)], places, env, GUARDS)
    for label, claude, cursor in PAYLOADS:
        rows += [{"label": f"allow payload {label}", "payload": payload, "cwd": places["nogit"], "by": None, "env": {}, "guards": GUARDS}
                 for payload in (claude, cursor)]
    for fields, tree, by in FILES:
        filled = {key: expand(value, places) if isinstance(value, str) else value for key, value in fields.items()}
        rows += [{"label": f"file {fields}", "payload": payload, "cwd": places[tree], "by": by, "env": {}, "guards": FILE_HOOKS, "shell": False}
                 for payload in file_shapes(filled, places[tree])]
    # A deny row asks only the guard that must deny (on both parsers); the allow rows run every guard.
    def asked(row: dict) -> list:
        expected = {row["by"], row.get("awk_by", row["by"])}
        return row["guards"] if None in expected else [g for g in row["guards"] if g.stem in expected]
    return [{**row, "guards": asked(row)} for row in rows]


def failure(row: dict, verdicts: dict[str, str], parser: str) -> str:
    where = f"{row['label']} [{row['payload'].get('hook_event_name')}, {parser}]"
    errors = [v for v in verdicts.values() if v.startswith("error")]
    deniers = sorted(name for name, v in verdicts.items() if v == "deny")
    by = row.get("awk_by", row["by"]) if parser == "awk" else row["by"]
    if errors:
        return f"{where}: {errors[0]}"
    if by is None and deniers:
        return f"{where}: denied by {deniers}"
    if by is not None and by not in deniers:
        return f"{where}: expected a deny from {by}, got {deniers or 'allow'}"
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


def parser_env(row: dict, env: dict, home: Path, parser: str) -> dict:
    """The row's environment; the awk parser runs with shfmt removed from PATH."""
    hidden = row.get("missing", ()) + (("shfmt",) if parser == "awk" else ())
    return {**env, **row["env"], **({"PATH": path_without(home, *hidden)} if hidden else {})}


def judge(job: tuple[str, str, dict], env: dict, home: Path) -> str:
    """One row under one bash and one parser."""
    bash, parser, row = job
    verdicts = {guard.stem: run_guard(bash, guard, row, parser_env(row, env, home, parser)) for guard in row["guards"]}
    found = failure(row, verdicts, parser)
    return f"{bash}: {found}" if found else ""


RECORDS = 'HOOK_NAME=records; . "$1"; HOOK_CWD=$2; hook_deny() { printf "deny: %s\\n" "$1"; exit 0; }; hook_segments "$3"; printf "%s\\n" ${HOOK_SEGS[@]+"${HOOK_SEGS[@]}"} ${HOOK_REDIRS[@]+"${HOOK_REDIRS[@]}"}'


def records(bash: str, row: dict, env: dict, home: Path, parser: str) -> tuple:
    """What `hook_segments` gives the guards for the row's command, through one parser."""
    done = subprocess.run([bash, "-c", RECORDS, "records", str(HOOKS / "lib" / "hook.sh"), str(row["cwd"]), row["command"]],
                          capture_output=True, text=True, env=parser_env(row, env, home, parser), cwd=str(row["cwd"]), timeout=120)
    return done.returncode, done.stdout, done.stderr


def agree(job: tuple[str, list], env: dict, home: Path) -> str:
    """The awk parser on the rows that share one command: identical records from both parsers mean the guards,
    which read nothing else of the command, give identical verdicts; otherwise (and for every listed difference)
    each row is judged through awk."""
    bash, group = job
    if "command" in group[0] and "awk_by" not in group[0] and records(bash, group[0], env, home, "shfmt") == records(bash, group[0], env, home, "awk"):
        return ""
    return "\n".join(line for line in (judge((bash, "awk", row), env, home) for row in group) if line)


def jobs_for(rows: list[dict]) -> list[tuple]:
    """Every row through the first parser; with shfmt present, the awk parser through `agree`, once per command."""
    found = parsers()
    jobs = [(judge, (bash, found[0], row)) for bash in bashes() for row in rows]
    if len(found) == 2:
        groups: dict = {}
        for row in filter(lambda row: row.get("shell", True), rows):
            key = (row["command"], str(row["cwd"]), row.get("missing"), json.dumps(row["env"], sort_keys=True), row["by"]) if "command" in row else id(row)
            groups.setdefault(key, []).append(row)
        jobs += [(agree, (bash, group)) for bash in bashes() for group in groups.values()]
    return jobs


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


@pytest.fixture(scope="module")
def world() -> Iterator[tuple[dict, dict[str, Path], list[dict]]]:
    """The environment, the named places and every case row, built once per worker."""
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
        assert review.returncode == 0 and review.stdout.strip() and places["review"].is_absolute(), \
            f"review-dir must print an absolute path (exit {review.returncode}): {review.stdout}{review.stderr}"
        rows = cases(home, places)
        # Every PATH a row or a failure job uses, built here so no thread creates one.
        for missing in {row.get("missing", ()) for row in rows}:
            if missing:
                path_without(home, *missing)
            path_without(home, "shfmt", *missing)
        # Without awk the normaliser can still run on shfmt, so `no awk` hides both to reach the awk check.
        places["no-jq"], places["no-awk"] = Path(path_without(home, "jq")), Path(path_without(home, "awk", "shfmt"))
        yield env, places, rows
    finally:
        shutil.rmtree(home, ignore_errors=True)


def in_parallel(check, jobs: list) -> list[str]:
    """Hook runs are subprocess-bound: threads overlap them, fewer under xdist, whose workers already fill the cores."""
    workers = 4 if os.environ.get("PYTEST_XDIST_WORKER") else max(4, (os.cpu_count() or 2) * 2)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        return [line for line in pool.map(check, jobs) if line]


def test_every_hook_is_classified() -> None:
    assert not unclassified(), unclassified()


def test_the_zsh_rule_follows_the_executing_shell(world: tuple) -> None:
    env, _, _ = world
    assert not shell_choice(env), shell_choice(env)


SLICES = 8


@pytest.mark.parametrize("part", range(SLICES))
def test_cases(part: int, world: tuple) -> None:
    """Every row, in both payload shapes, under every bash and through both parsers: deny rows name their
    guard, allow rows stay silent (the awk parser through `agree`; a file row reads no command, so once).

    The rows are dealt into slices so xdist can spread them; a slice is every SLICES-th job.
    """
    env, places, rows = world
    failed = in_parallel(lambda job: job[0](job[1], env, places["home"]), jobs_for(rows)[part::SLICES])
    assert not failed, "\n".join(failed)


def test_a_broken_shfmt_falls_back_to_awk(world: tuple) -> None:
    """A shfmt that prints invalid JSON makes jq fail, and awk then reads the command: the same records
    and the same deny. The real shfmt path, for its part, runs: on every listed difference its records differ."""
    env, places, _ = world
    home = places["home"]
    stub = home / "broken-shfmt"
    stub.mkdir(exist_ok=True)
    (stub / "shfmt").write_text("#!/bin/sh\ncat >/dev/null\necho '{'\n", encoding="utf-8")
    (stub / "shfmt").chmod(0o755)
    row = {"command": "git reset --hard", "cwd": places["clean"], "env": {"PATH": f"{stub}{os.pathsep}{path_without(home, 'shfmt')}"},
           "payload": shapes("git reset --hard", places["clean"])[0], "by": "destructive-git"}
    guard = HOOKS / "guard" / "destructive-git.sh"
    assert run_guard("bash", guard, row, {**env, **row["env"]}) == "deny"
    assert records("bash", row, env, home, "shfmt") == records("bash", row, env, home, "awk")
    if "shfmt" in parsers():
        for command, tree, *_ in PARSERS_DIFFER:
            real = {"command": command, "cwd": places[tree], "env": {}}
            assert records("bash", real, env, home, "shfmt") != records("bash", real, env, home, "awk"), command


def test_a_deep_pipeline_is_denied_quickly(world: tuple) -> None:
    """shfmt's JSON grows with nesting depth times size (1.6 GB for this one), so a command this deep is read by awk."""
    if "shfmt" not in parsers():
        pytest.skip("shfmt is not installed; the awk path alone has no JSON to grow")
    env, places, _ = world
    payload = shapes("true | " * 3900 + "git reset --hard", places["clean"])[0]
    start = time.monotonic()
    done = run("bash", HOOKS / "guard" / "destructive-git.sh", json.dumps(payload), env, places["clean"])
    elapsed = time.monotonic() - start
    # The unbounded path took 25 s here; 15 s leaves room for a loaded CI runner.
    assert done.returncode == 2 and elapsed < 15, f"exit {done.returncode} after {elapsed:.1f}s: {done.stderr[:300]}"


@pytest.mark.parametrize("label, extra, ago, calls", NOTIFY, ids=[row[0] for row in NOTIFY])
def test_idle_notification_is_quiet(label: str, extra: dict, ago: int | None, calls: int, world: tuple) -> None:
    """A banner only, never an app activation; none in a background job, with the off switch, or twice per session in 10 minutes."""
    env, places, _ = world
    home = places["home"] / "notify" / label.replace(" ", "-")
    stub = home / "bin"
    stub.mkdir(parents=True)
    log = home / "osascript.log"
    (stub / "osascript").write_text(f"#!/bin/sh\nprintf '%s\\n' \"$*\" >> '{log}'\n", encoding="utf-8")
    (stub / "osascript").chmod(0o755)
    stamp = home / ".agent" / "memory" / ".sessions" / (hashlib.sha256(b"s1").hexdigest()[:24] + ".notified")
    if ago is not None:
        stamp.parent.mkdir(parents=True)
        stamp.write_text(f"{int(time.time()) - ago}\n", encoding="utf-8")
    run_env = {k: v for k, v in env.items() if k not in ("CLAUDE_JOB_DIR", "CREW_MEMORY_DIR", "EL_CAPITAN_NOTIFY")}
    run_env.update(extra, HOME=str(home), PATH=f"{stub}{os.pathsep}{env['PATH']}")
    payload = {"session_id": "s1", "hook_event_name": "Notification", "notification_type": "idle_prompt", "cwd": str(places["clean"])}
    done = run("bash", HOOKS / "notify-idle.sh", json.dumps(payload), run_env, places["clean"])
    lines = log.read_text(encoding="utf-8").splitlines() if log.exists() else []
    assert (done.returncode, done.stdout, done.stderr) == (0, "", ""), done
    assert len(lines) == calls and not any("activate" in line for line in lines), lines
    assert not calls or stamp.read_text(encoding="utf-8").strip().isdigit()


def run_probe(home: Path, harness: str, event: str, stdin: str, on: bool, bash: str = "bash") -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items() if not k.startswith(("CLAUDE_", "CURSOR_", "EL_CAPITAN_"))}
    env.update(HOME=str(home), CLAUDE_JOB_DIR="/private/secret-dir/job", CURSOR_SECRET_TOKEN=SECRET)
    if on:
        env["EL_CAPITAN_PROBE"] = "1"
    return subprocess.run([bash, str(HOOKS / "probe.sh"), harness, event], input=stdin, capture_output=True, text=True,
                          env=env, timeout=60)


@pytest.mark.parametrize("harness, event, payload, stdout", PROBE, ids=[f"{row[0]}-{row[1]}" for row in PROBE])
def test_the_probe_logs_names_only(harness: str, event: str, payload: dict, stdout: str, tmp_path: Path) -> None:
    """With EL_CAPITAN_PROBE=1 one JSON line of names per event; no value from the payload or the environment."""
    done = run_probe(tmp_path, harness, event, json.dumps(payload), on=True)
    assert (done.returncode, done.stdout.strip(), done.stderr) == (0, stdout, ""), done
    text = (tmp_path / ".agent" / "state" / "probe.log").read_text(encoding="utf-8")
    leaked = [value for value in (*PROBE_VALUES, "/private/secret-dir/job", "AKIA") if value in text]
    assert not leaked, leaked
    record = json.loads(text)
    assert (record["harness"], record["event"]) == (harness, event)
    assert record["fields"] == sorted(payload) and "CLAUDE_JOB_DIR" in record["env"] and "CURSOR_SECRET_TOKEN" in record["env"]
    if "tool_input" in payload:
        assert record["tool_input_fields"] == sorted(payload["tool_input"]) and record["tool_name"] == payload["tool_name"]
    if event == "afterFileEdit":
        assert record["edits_fields"] == ["new_string", "old_string"]
    if event == "subagentStop":
        assert (record["has_jsonl"], record["jsonl_fields"], record["has_long"], record["long_fields"]) == (
            True, ["transcript_path"], True, ["summary"])


@pytest.mark.parametrize("stdin", ["{not json", "", json.dumps(PROBE[0][2])], ids=["malformed", "empty", "payload"])
@pytest.mark.parametrize("on", [False, True], ids=["off", "on"])
def test_the_probe_never_blocks_and_is_inert_when_off(stdin: str, on: bool, tmp_path: Path) -> None:
    """Exit 0 always, under every bash, `{}` only where Cursor expects a decision; without the variable no file at all."""
    for bash in bashes():
        for harness, event, answer in (("claude", "PreToolUse", ""), ("cursor", "beforeShellExecution", "{}"),
                                       ("cursor", "stop", ""), ("", "", "")):
            done = run_probe(tmp_path, harness, event, stdin, on=on, bash=bash)
            assert (done.returncode, done.stdout.strip(), done.stderr) == (0, answer, ""), (bash, harness, done)
    log = tmp_path / ".agent" / "state" / "probe.log"
    assert log.exists() == on and not (on and SECRET in log.read_text(encoding="utf-8"))


def test_a_status_denial_names_crew_task(world: tuple) -> None:
    """The Status guard's one line tells the agent which commands move a status."""
    env, places, _ = world
    fields = {"file_path": str(places["tasks"] / "DDD-status" / "SPEC.md"), "old_string": "DRAFTING", "new_string": "APPROVED"}
    done = run("bash", HOOKS / "check-task-spec-owner.sh", json.dumps(file_shapes(fields, places["clean"])[0]), env, places["clean"])
    assert done.returncode == 2 and "crew-task.py mark-approved | mark-implementing | mark-done" in done.stderr, done


def test_the_task_file_tripwire_answers_cursor(world: tuple) -> None:
    """Cursor's `beforeShellExecution` payload (the command at the top level): a redirect onto a task SPEC.md gets the
    JSON deny, a `crew-task.py` call gets `{}` (an empty decision: the entry is `failClosed: true`, and Cursor reads
    silence from such a hook as a crash). The table rows run in this shape too; this names it."""
    env, places, _ = world
    guard = HOOKS / "guard" / "task-files.sh"
    spec = places["tasks"] / "DDD-status" / "SPEC.md"
    denied = run("bash", guard, json.dumps(shapes(f"echo x > {spec}", places["clean"])[1]), env, places["clean"])
    allowed = run("bash", guard, json.dumps(shapes(f"~/.agent/bin/crew-task.py mark-approved {spec.parent}", places["clean"])[1]),
                  env, places["clean"])
    assert denied.returncode == 0 and json.loads(denied.stdout)["permission"] == "deny", denied
    assert (allowed.returncode, allowed.stdout, allowed.stderr) == (0, "{}\n", ""), allowed


def test_every_cursor_security_guard_fails_closed_and_answers() -> None:
    """In Cursor a hook that crashes, times out or prints invalid JSON fails open unless `failClosed: true`: every
    security guard has it, the advisory zsh-equals and every observer do not, and each fail-closed guard answers a
    Cursor event it has no objection to with `{}` rather than silence (which Cursor reads as a crash)."""
    template = json.loads((ROOT / ".cursor" / "hooks.template.json").read_text(encoding="utf-8"))["hooks"]

    def script(entry: dict) -> str:
        return entry["command"].split('"')[1].split("/.claude/hooks/", 1)[1]

    closed = {script(entry) for entries in template.values() for entry in entries if entry.get("failClosed") is True}
    guards = {f"guard/{path.name}" for path in GUARDS} - {"guard/zsh-equals.sh"}
    assert closed == guards | {"check-write-boundary.sh", "check-task-spec-owner.sh"}, closed
    for event in ("beforeShellExecution", "preToolUse"):
        for entry in template[event]:
            if script(entry) not in closed:
                continue
            payload = ({"hook_event_name": event, "command": "git status", "cwd": str(ROOT)} if event == "beforeShellExecution"
                       else {"hook_event_name": event, "tool_name": "Write", "file_path": "/tmp/hook-case-x", "content": "x",
                             "cwd": str(ROOT)})
            done = run("bash", HOOKS / script(entry), json.dumps(payload), {**os.environ, "CREW_WORKER_TASK": ""}, ROOT)
            assert (done.returncode, done.stdout) == (0, "{}\n"), (script(entry), done)


def test_only_a_task_spec_needs_the_status_reader(world: tuple) -> None:
    """With `task_status` missing, a write elsewhere is still allowed and a task spec edit is refused (fail closed)."""
    env, places, _ = world
    copy = places["home"] / "no-reader" / ".claude" / "hooks"
    if not copy.exists():
        shutil.copytree(HOOKS, copy, symlinks=True)
    hook = copy / "check-task-spec-owner.sh"
    elsewhere = run("bash", hook, json.dumps(file_shapes({"file_path": str(places["clean"] / "new.md"), "content": "x"},
                                                         places["clean"])[0]), env, places["clean"])
    spec = run("bash", hook, json.dumps(file_shapes({"file_path": str(places["tasks"] / "DDD-status" / "SPEC.md"),
                                                     "old_string": "- [ ] T1: a", "new_string": "- [x] T1: a"},
                                                    places["clean"])[0]), env, places["clean"])
    assert (elsewhere.returncode, elsewhere.stdout, elsewhere.stderr) == (0, "", ""), elsewhere
    assert spec.returncode == 2 and "no verdict" in spec.stderr, spec


def test_every_hook_survives_bad_input(world: tuple) -> None:
    env, places, _ = world
    failed = in_parallel(lambda job: unreadable(job, env, {k: str(v) for k, v in places.items()}), failure_jobs())
    assert not failed, "\n".join(failed)
