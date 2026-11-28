#!/usr/bin/env python3
"""Every hook's contract, table-driven, in both harness payload shapes and under both bashes.

A shell command is sent as Claude's `PreToolUse` (`tool_input.command`) and as Cursor's
`beforeShellExecution` (top-level `command`) to the shell guard, `guard/shell.sh`; a file write as
`PreToolUse` and Cursor's `preToolUse` to the file guard. Each runs under the `bash` on PATH and under
`/bin/bash` (bash 3.2 on macOS). A deny names its off switches, and the rule they name must be the row's;
a demoted rule (`DEMOTED`) denies only in Cursor's shape, so its row expects an allow from Claude's. An
allow fails on any output at all, so an internal error fails the allow corpus as surely as a wrong
denial. `gitleaks` is a stub on PATH that finds the AKIA key. Every shell row also runs through both parsers of `hook_segments`: with `shfmt` on
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
import re
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
    COUNTERPART_DECOYS,
    CURSOR_COPY,
    DENY,
    ENV,
    FILES,
    MESSAGES,
    MISSING,
    NOTIFY,
    PARSERS_DIFFER,
    PAYLOADS,
    SECRET,
    SILENT,
    STATUS_SPEC,
)

ROOT = Path(__file__).resolve().parents[2]
HOOKS = ROOT / ".claude" / "hooks"
GUARDS = [HOOKS / "guard" / "shell.sh"]
FILE_HOOKS = [HOOKS / "check-task-spec-owner.sh"]
# The rules Claude Code holds with permission rules: they deny only in Cursor's shape (docs/hooks.md).
DEMOTED = {"local-pr-ref", "pr-repo", "source-edit", "status"}
DENIER = re.compile(r"EL_CAPITAN_GUARD_([A-Z_]+)=off for this guard")
# Exit 3 (gitleaks' --exit-code) when the scanned text, or the commits on no remote, hold the fixture's AKIA key.
GITLEAKS = """#!/bin/sh
if [ "$1" = stdin ]; then grep -q AKIA && exit 3; exit 0; fi
for repo; do :; done
git -C "$repo" log -p HEAD --not --remotes | grep -q AKIA && exit 3
exit 0
"""
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
    trees["pushleak"] = repository(home / "pushleak", {"leak.txt": SECRET + "\n"})
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
    """`deny <rule>`, `allow`, or `error: ...` for one hook run in one shape; a deny names its off switches."""
    done = run(bash, guard, json.dumps(row["payload"]), env, row["cwd"])
    out, err = done.stdout.strip(), done.stderr.strip()
    claude = row["payload"].get("hook_event_name") == "PreToolUse"
    verdict = classify(claude, done.returncode, out, err, row.get("loose", False))
    if verdict == "unknown":
        return f"error: {guard.name} exit {done.returncode} stdout={out[:200]!r} stderr={err[:300]!r}"
    found = DENIER.search(out + err)
    if verdict == "allow":
        return verdict
    if not found or "EL_CAPITAN_GUARDS=off" not in out + err:
        return f"error: {guard.name} denies without naming its rule's switch and EL_CAPITAN_GUARDS=off: {(out + err)[:300]!r}"
    rule = found.group(1).lower().replace("_", "-")
    says, never = MESSAGES.get(rule, ((), ()))
    if rule == row["by"] and (any(text not in out + err for text in says) or any(text in out + err for text in never)):
        return f"error: {rule} denial must say {says} and never {never}: {(out + err)[:300]!r}"
    return f"deny {rule}"


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
    for directory in filter(os.path.isdir, [str(home / "gitleaks-bin"), *os.environ.get("PATH", "").split(os.pathsep), "/usr/bin", "/bin"]):
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


def shaped(by: str | None, payload: dict) -> str | None:
    """The rule a row expects in this payload's shape: a demoted rule is silent in Claude Code's."""
    return None if by in DEMOTED and payload["hook_event_name"] == "PreToolUse" else by


def rows_for(kind: str, table: list, places: dict[str, Path], env: dict, guards: list) -> list[dict]:
    rows = []
    for command, tree, by in table:
        for payload in shapes(expand(command, places), places[tree]):
            rows.append({"label": f"{kind} {command[:70]!r} in {tree}", "payload": payload, "cwd": places[tree], "by": shaped(by, payload), "env": env,
                         "guards": guards, "command": expand(command, places)})
    return rows


def cases(home: Path, places: dict[str, Path]) -> list[dict]:
    """One row per table entry and payload shape: what to send, where, and what must come back."""
    rows = rows_for("deny", DENY, places, {}, GUARDS)
    rows += rows_for("allow", [(command, tree, None) for command, tree in ALLOW], places, {}, GUARDS)
    for command, tree, by, awk_by, _ in PARSERS_DIFFER:
        rows += [{**row, "awk_by": shaped(awk_by, row["payload"])} for row in rows_for("parsers differ", [(command, tree, by)], places, {}, GUARDS)]
    for command, tree, tool, env, by in MISSING:
        found = rows_for(f"no-{tool} {env}", [(command, tree, by)], places, env, GUARDS)
        rows += [{**row, "loose": True, "missing": (tool,)} for row in found]
    for command, tree, env, by in ENV:
        rows += rows_for(f"env {env}", [(command, tree, by)], places, env, GUARDS)
    for label, claude, cursor in PAYLOADS:
        rows += [{"label": f"allow payload {label}", "payload": payload, "cwd": places["nogit"], "by": None, "env": {}, "guards": GUARDS}
                 for payload in (claude, cursor)]
    for fields, tree, by in FILES:
        filled = {key: expand(value, places) if isinstance(value, str) else value for key, value in fields.items()}
        rows += [{"label": f"file {fields}", "payload": payload, "cwd": places[tree], "by": shaped(by, payload), "env": {}, "guards": FILE_HOOKS,
                  "shell": False} for payload in file_shapes(filled, places[tree])]
    return rows


def failure(row: dict, verdicts: dict[str, str], parser: str) -> str:
    where = f"{row['label']} [{row['payload'].get('hook_event_name')}, {parser}]"
    errors = [v for v in verdicts.values() if v.startswith("error")]
    deniers = sorted(v.split()[1] for v in verdicts.values() if v.startswith("deny "))
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
    quiet = done.stdout.strip() == ""
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
    (home / "gitleaks-bin").mkdir()
    (home / "gitleaks-bin" / "gitleaks").write_text(GITLEAKS, encoding="utf-8")
    (home / "gitleaks-bin" / "gitleaks").chmod(0o755)
    env = {**os.environ, **GIT_ID, "HOME": str(home), "SHELL": "/bin/zsh", "TMPDIR": str(tmp), "GIT_CEILING_DIRECTORIES": str(home.parent),
           "PATH": f"{home / 'gitleaks-bin'}{os.pathsep}{os.environ.get('PATH', '')}"}
    for key in [k for k in env if k.startswith(("CREW_", "EL_CAPITAN_"))]:
        env.pop(key)
    try:
        places: dict[str, Path] = {**fixture(home), "home": home, "tmp": tmp, "tasks": home / ".agent" / "tasks"}
        review = subprocess.run([sys.executable, str(ROOT / "src/crew/review/crew_review_findings.py"), "review-dir", "--repo", "boundary-probe"],
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
           "payload": shapes("git reset --hard", places["clean"])[1], "by": "destructive-git"}
    assert run_guard("bash", GUARDS[0], row, {**env, **row["env"]}) == "deny destructive-git"
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
    payload = shapes("true | " * 3900 + "git reset --hard", places["clean"])[1]
    start = time.monotonic()
    done = run("bash", GUARDS[0], json.dumps(payload), env, places["clean"])
    elapsed = time.monotonic() - start
    # The unbounded path took 25 s here; 15 s leaves room for a loaded CI runner.
    assert '"deny"' in done.stdout and elapsed < 15, f"{done.stdout[:200]} after {elapsed:.1f}s: {done.stderr[:300]}"


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
    if "CURSOR_VERSION" in extra:  # Cursor's copy carries both signals
        payload["cursor_version"] = extra["CURSOR_VERSION"]
    done = run("bash", HOOKS / "notify-idle.sh", json.dumps(payload), run_env, places["clean"])
    lines = log.read_text(encoding="utf-8").splitlines() if log.exists() else []
    assert (done.returncode, done.stdout, done.stderr) == (0, "", ""), done
    assert len(lines) == calls and not any("activate" in line for line in lines), lines
    assert not calls or stamp.read_text(encoding="utf-8").strip().isdigit()


def test_the_shell_guard_answers_cursor(world: tuple) -> None:
    """Cursor's `beforeShellExecution` payload (the command at the top level): an `rm` of a task SPEC.md gets the
    JSON deny, a `crew-task.py` call gets `{}` (an empty decision: the entry is `failClosed: true`, and Cursor reads
    silence from such a hook as a crash). The table rows run in this shape too; this names it."""
    env, places, _ = world
    guard = GUARDS[0]
    spec = places["tasks"] / "DDD-status" / "SPEC.md"
    denied = run("bash", guard, json.dumps(shapes(f"rm {spec}", places["clean"])[1]), env, places["clean"])
    allowed = run("bash", guard, json.dumps(shapes(f"~/.agent/bin/crew-task.py mark-approved {spec.parent}", places["clean"])[1]),
                  env, places["clean"])
    assert denied.returncode == 0 and json.loads(denied.stdout)["permission"] == "deny", denied
    assert (allowed.returncode, allowed.stdout, allowed.stderr) == (0, "{}\n", ""), allowed


def test_every_cursor_security_guard_fails_closed_and_answers() -> None:
    """In Cursor a hook that crashes, times out or prints invalid JSON fails open unless `failClosed: true`: every
    security guard has it, every observer does not, and each fail-closed guard answers a
    Cursor event it has no objection to with `{}` rather than silence (which Cursor reads as a crash)."""
    template = json.loads((ROOT / ".cursor" / "hooks.template.json").read_text(encoding="utf-8"))["hooks"]

    def script(entry: dict) -> str:
        return entry["command"].split('"')[1].split("/.claude/hooks/", 1)[1]

    closed = {script(entry) for entries in template.values() for entry in entries if entry.get("failClosed") is True}
    assert closed == {"guard/shell.sh", "check-task-spec-owner.sh"}, closed
    for event in ("beforeShellExecution", "preToolUse"):
        for entry in template[event]:
            if script(entry) not in closed:
                continue
            payload = ({"hook_event_name": event, "command": "git status", "cwd": str(ROOT)} if event == "beforeShellExecution"
                       else {"hook_event_name": event, "tool_name": "Write", "file_path": "/tmp/hook-case-x", "content": "x",
                             "cwd": str(ROOT)})
            done = run("bash", HOOKS / script(entry), json.dumps(payload), {**os.environ, "CREW_WORKER_TASK": ""}, ROOT)
            assert (done.returncode, done.stdout) == (0, "{}\n"), (script(entry), done)


HOOK_SCRIPT = re.compile(r"/\.claude/hooks/([\w./-]+\.sh)")
STAND_DOWN = re.compile(r"^hook_stand_down[ \t]+(\S+)([ \t]+fail-closed)?[ \t]*$", re.M)
DROPPED = re.compile(r"^hook_dropped_in_cursor[ \t]*$", re.M)
COUNTERPART_EVENTS = json.loads((HOOKS / "lib" / "cursor-counterparts.json").read_text(encoding="utf-8"))


def cursor_rows() -> dict[str, tuple[str, str]]:
    """docs/hooks.md "Each hook in Cursor": hook -> (what it does in Cursor, counterpart or reason)."""
    section = (ROOT / "docs" / "hooks.md").read_text(encoding="utf-8").split("\n## Each hook in Cursor\n", 1)[1]
    rows = {}
    for line in section.split("\n## ", 1)[0].splitlines():
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) == 4 and cells[0].startswith("`"):
            rows[cells[0].strip("`")] = (cells[2], cells[3])
    return rows


def template_scripts(name: str, nested: bool) -> dict[str, bool]:
    """Each script a template registers, and whether any of its entries is `failClosed: true`."""
    found: dict[str, bool] = {}
    for entries in json.loads((ROOT / name).read_text(encoding="utf-8"))["hooks"].values():
        for hook in (inner for entry in entries for inner in (entry["hooks"] if nested else [entry])):
            script = HOOK_SCRIPT.search(hook["command"]).group(1)
            found[script] = found.get(script, False) or hook.get("failClosed") is True
    return found


def test_every_claude_hook_has_a_cursor_row() -> None:
    """Every hook the Claude template registers has a row; the row's verdict is what its script does first: a stand-down
    names the Cursor-template counterpart it waits for, fail-closed exactly when that entry is, before reading input."""
    rows, cursor = cursor_rows(), template_scripts(".cursor/hooks.template.json", False)
    missing = sorted(set(template_scripts(".claude/settings.template.json", True)) - set(rows))
    assert not missing, f"hooks with no row in docs/hooks.md, Each hook in Cursor: {missing}"
    assert {hook for hook, _, _ in CURSOR_COPY} | {"notify-idle.sh"} == set(rows), "CURSOR_COPY covers every row"
    for hook, (verdict, cell) in rows.items():
        text = (HOOKS / hook).read_text(encoding="utf-8")
        call, dropped = STAND_DOWN.search(text), DROPPED.search(text)
        first = (call or dropped).start() < text.index("\nhook_input") if call or dropped else True
        if verdict == "stands down":
            assert call and not dropped and first, f"{hook}: no hook_stand_down before hook_input"
            counterpart, closed = call.group(1), bool(call.group(2))
            assert f"`{counterpart}`" in cell and counterpart in cursor, f"{hook}: counterpart {counterpart}"
            assert closed == cursor[counterpart] == ("fail-closed" in cell), f"{hook}: fail-closed differs"
            event = COUNTERPART_EVENTS.get(counterpart)
            assert event and f"`{event}`" in cell, f"{hook}: lib/cursor-counterparts.json names {event} for {counterpart}"
            native = json.loads((ROOT / ".cursor" / "hooks.template.json").read_text(encoding="utf-8"))["hooks"][event]
            assert any(f'"$HOME/.claude/hooks/{counterpart}"' in entry["command"] for entry in native), \
                f"{hook}: the Cursor template does not register {counterpart} under {event}"
        elif verdict == "dropped":
            assert dropped and not call and first, f"{hook}: no hook_dropped_in_cursor before hook_input"
        else:
            assert verdict == "keeps running" and not call and not dropped, f"{hook}: {verdict}"


def home_state(home: Path) -> set[tuple[str, int, int]]:
    return {(str(path), path.stat().st_size, path.stat().st_mtime_ns) for path in home.rglob("*")
            if path.is_file() and not path.is_symlink()}


def cursor_copy_run(hook: str, payload: dict, cwd: Path, env: dict, home: Path) -> tuple[bool, int, str]:
    """Whether the run said nothing and changed nothing in HOME, its exit code, and a summary for a failure message."""
    before = home_state(home)
    done = run("bash", HOOKS / hook, json.dumps(payload), env, cwd)
    quiet = (done.returncode, done.stdout, done.stderr) == (0, "", "") and home_state(home) == before
    return quiet, done.returncode, f"exit {done.returncode} stdout={done.stdout[:160]!r} stderr={done.stderr[:200]!r}"


def decoyed(template: dict, counterpart: str, event: str | None, command: str) -> dict:
    """The Cursor template with every entry for `counterpart` replaced by one fail-closed decoy."""
    path = f"/.claude/hooks/{counterpart}"
    hooks = {name: [entry for entry in entries if path not in entry["command"]] for name, entries in template["hooks"].items()}
    target = event or COUNTERPART_EVENTS[counterpart]
    hooks[target] = hooks.get(target, []) + [{"command": command.format(script=counterpart), "failClosed": True}]
    return {**template, "hooks": hooks}


def test_the_cursor_copy_runs_once(world: tuple) -> None:
    """Cursor's Claude-format copy of an event (`cursor_version` in the payload) does nothing in a hook that stands down
    or is dropped, while Claude Code's copy does something; a hook that keeps running answers both alike. Without its
    counterpart registered in ~/.cursor/hooks.json (fail-closed with `failClosed: true`), or with only a decoy of it
    (`COUNTERPART_DECOYS`), a stand-down keeps running."""
    env, places, _ = world
    home, rows, failed = places["home"], cursor_rows(), []
    installed = home / ".cursor" / "hooks.json"
    installed.parent.mkdir(exist_ok=True)
    template = json.loads((ROOT / ".cursor" / "hooks.template.json").read_text(encoding="utf-8"))
    fail_open = {**template, "hooks": {event: [{key: value for key, value in entry.items() if key != "failClosed"}
                                               for entry in entries] for event, entries in template["hooks"].items()}}
    try:
        for hook, payload, tree in CURSOR_COPY:
            verdict, cell = rows[hook]
            claude = {**json.loads(expand(json.dumps(payload), places)), "cwd": str(places[tree])}
            copy = {**claude, "cursor_version": "2.1.0"}
            installed.write_text(json.dumps(template), encoding="utf-8")
            quiet, code, said = cursor_copy_run(hook, copy, places[tree], env, home)
            own_quiet, own_code, own_said = cursor_copy_run(hook, claude, places[tree], env, home)
            if verdict == "keeps running" and (quiet, code) != (own_quiet, own_code):
                failed.append(f"{hook} keeps running, yet Cursor's copy differs: {said} vs Claude Code's {own_said}")
            if verdict != "keeps running" and (not quiet or own_quiet):
                failed.append(f"{hook} {verdict}: Cursor's copy {said}; Claude Code's {own_said}")
            if verdict != "stands down":
                continue
            installed.write_text(json.dumps(fail_open), encoding="utf-8")
            if "fail-closed" in cell and cursor_copy_run(hook, copy, places[tree], env, home)[0]:
                failed.append(f"{hook} stood down although its Cursor counterpart is fail-open")
            installed.unlink()
            if cursor_copy_run(hook, copy, places[tree], env, home)[0]:
                failed.append(f"{hook} stood down although Cursor registers no counterpart")
            counterpart = STAND_DOWN.search((HOOKS / hook).read_text(encoding="utf-8")).group(1)
            for label, event, command in COUNTERPART_DECOYS:
                installed.write_text(json.dumps(decoyed(template, counterpart, event, command)), encoding="utf-8")
                if cursor_copy_run(hook, copy, places[tree], env, home)[0]:
                    failed.append(f"{hook} stood down for {label}")
    finally:
        if installed.exists():
            installed.unlink()
    assert not failed, "\n".join(failed)


def test_an_inherited_input_flag_changes_nothing(world: tuple) -> None:
    """`HOOK_INPUT_READ` exported by the harness is reset when lib/hook.sh is sourced, so the payload is still read."""
    env, places, _ = world
    payload = json.dumps(shapes("crew-task.py restore-status /x --accept ok", places["clean"])[0])
    done = run("bash", GUARDS[0], payload, {**env, "HOOK_INPUT_READ": "1"}, places["clean"])
    assert done.returncode == 2 and "Owner only" in done.stderr, done


def test_every_hook_survives_bad_input(world: tuple) -> None:
    env, places, _ = world
    failed = in_parallel(lambda job: unreadable(job, env, {k: str(v) for k, v in places.items()}), failure_jobs())
    assert not failed, "\n".join(failed)
