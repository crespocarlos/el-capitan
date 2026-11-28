#!/usr/bin/env python3
"""Every adapter gives every harness-free hook rule the same verdicts, and renders what its manifest declares.

Hook cases: each shell row of `hook_cases.py` is sent as each adapter's `pre_shell` fixture
(`evals/fixtures/harness/<id>/`), each file row as its `pre_write` fixture, through `crew-hook.py <id> <event>`. A
deny names its off switches and the row's rule; a demoted rule (`DEMOTED`) denies only where the adapter's manifest
declares no deny rule that holds (the cursor fallback), so its row expects an allow elsewhere. An allow fails on any
output beyond the harness's empty answer. `gitleaks` is a stub on PATH that finds the AKIA key. The claude-code rows
also run under `/bin/bash` (bash 3.2 on macOS) and through both parsers of `hook_segments` (shfmt on PATH, and PATH
without it), whose verdicts must match, `PARSERS_DIFFER` naming the rows where awk's is another. Every rule script survives unreadable input and a missing
`jq` with exit 0 and at most one stderr line, and every hook file is in `contract.json`.

Render goldens: each contract rule is registered once per native event its manifest maps, with its fail mode and a
timeout that covers it; each always-on rule is delivered; each agent's access class is mapped; every capability has a
value or a declared fallback; the installed files equal `render()` after `harness_install apply`.
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
from hook_cases import ALLOW, DENY, ENV, FILES, MESSAGES, MISSING, NOTIFY, PARSERS_DIFFER, PAYLOADS, SECRET, SILENT, STATUS_SPEC

from crew.harness import adapters, claude_code, codex, cursor, harness_install

ROOT = Path(__file__).resolve().parents[2]
HOOKS = ROOT / ".claude" / "hooks"
FIXTURES = ROOT / "evals" / "fixtures" / "harness"
FILE_HOOKS = [HOOKS / "check-task-spec-owner.sh"]
GUARDS = [HOOKS / "guard" / "shell.sh"]
# The rules a harness with a deny capability holds with its own deny and ask rules (docs/hooks.md).
DEMOTED = {"local-pr-ref", "pr-repo", "source-edit", "status"}
DENIER = re.compile(r"EL_CAPITAN_GUARD_([A-Z_]+)=off for this guard")
# Exit 3 (gitleaks' --exit-code) when the scanned text, or the commits on no remote, hold the fixture's AKIA key.
GITLEAKS = """#!/bin/sh
if [ "$1" = stdin ]; then grep -q AKIA && exit 3; exit 0; fi
for repo; do :; done
git -C "$repo" log -p HEAD --not --remotes | grep -q AKIA && exit 3
exit 0
"""
pytestmark = pytest.mark.timeout(300)
GIT_ID = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid"}


def fixture_for(harness: str, event: str) -> tuple[str, dict]:
    """(native event, fixture payload) of the harness for a canonical event, from its manifest and fixture files."""
    mapped = adapters.manifest(harness)["events"][event]
    native = adapters.natives(mapped)[0]
    matcher = mapped.get("matcher", "")
    names = [f"{native}-{tool}.json" for tool in matcher.split("|") if tool] + [f"{native}.json"]
    path = next(FIXTURES / harness / name for name in names if (FIXTURES / harness / name).is_file())
    return native, json.loads(path.read_text(encoding="utf-8"))


def fill(payload: object, values: dict) -> object:
    """The payload with each `"{name}"` value replaced by `values[name]`, whatever its type, and `{name}` in a string."""
    if isinstance(payload, dict):
        return {key: fill(value, values) for key, value in payload.items()}
    if isinstance(payload, list):
        return [fill(value, values) for value in payload]
    if isinstance(payload, str) and payload.startswith("{") and payload.endswith("}") and payload[1:-1] in values:
        return values[payload[1:-1]]
    return payload


def shell_harnesses() -> list[str]:
    return [harness for harness in adapters.IDS if adapters.manifest(harness)["events"]["pre_shell"].get("native")]


def write_harnesses() -> list[str]:
    return [harness for harness in adapters.IDS if adapters.manifest(harness)["events"]["pre_write"].get("native")]


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
    names = ("clean", "locked", "stale", "detached", "large", "addable", "staged", "bigleak", "loose", "corrupt")
    trees = {name: repository(home / name, {}) for name in names}
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
    (home / ".agent" / "hooks").symlink_to(HOOKS)
    return trees


def decode(code: int, out: str, err: str, loose: bool = False) -> tuple[str, str]:
    """(`allow`, `deny` or `unknown`, the message): an exit-2 denial with one stderr line (Claude-shaped), or one JSON
    object with `permission: deny`; an allow is exit 0 with nothing but the harness's empty answer."""
    if code == 2 and len(err.splitlines()) == 1 and not out:
        return "deny", err
    if code != 0 or (err and not loose) or len(err.splitlines()) > 1:
        return "unknown", out + err
    if out in ("", "{}"):
        return "allow", ""
    try:
        answer = json.loads(out)
    except ValueError:
        return "unknown", out
    return ("deny", str(answer.get("user_message"))) if answer.get("permission") == "deny" else ("unknown", out)


def hook(harness: str, native: str, payload: dict, env: dict, cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-m", "crew.harness.crew_hook", harness, native], input=json.dumps(payload), capture_output=True,
                          text=True, env=env, cwd=str(cwd), timeout=120)


def run_row(row: dict, env: dict) -> str:
    """`deny <rule>`, `allow`, or `error: ...` for one row through crew-hook; a deny names its off switches."""
    done = hook(row["harness"], row["native"], row["payload"], env, row["cwd"])
    verdict, said = decode(done.returncode, done.stdout.strip(), done.stderr.strip(), row.get("loose", False))
    if verdict == "unknown":
        return f"error: exit {done.returncode} stdout={done.stdout[:200]!r} stderr={done.stderr[:300]!r}"
    if verdict == "allow":
        return verdict
    found = DENIER.search(said)
    if not found or "EL_CAPITAN_GUARDS=off" not in said:
        return f"error: a denial without its rule's switch and EL_CAPITAN_GUARDS=off: {said[:300]!r}"
    rule = found.group(1).lower().replace("_", "-")
    says, never = MESSAGES.get(rule, ((), ()))
    if rule == row["by"] and (any(text not in said for text in says) or any(text in said for text in never)):
        return f"error: {rule} denial must say {says} and never {never}: {said[:300]!r}"
    return f"deny {rule}"


def expected(by: str | None, harness: str) -> str | None:
    """The rule a row expects from this harness: a demoted rule is silent where the manifest's deny rules hold."""
    return None if by in DEMOTED and adapters.deny_rules(adapters.manifest(harness), "default") else by


def expand(text: str, places: dict[str, Path]) -> str:
    for name, path in places.items():
        text = text.replace("{" + name + "}", str(path))
    return text


def shell_rows(kind: str, table: list, places: dict[str, Path], env: dict, harnesses: list[str]) -> list[dict]:
    rows = []
    for command, tree, by in table:
        filled = expand(command, places)
        for harness in harnesses:
            native, payload = fixture_for(harness, "pre_shell")
            rows.append({"label": f"{kind} {command[:70]!r} in {tree}", "harness": harness, "native": native, "cwd": places[tree], "env": env,
                         "payload": fill(payload, {"command": filled, "cwd": str(places[tree]), "session": "s"}), "by": expected(by, harness),
                         "command": filled})
    return rows


def file_rows(places: dict[str, Path]) -> list[dict]:
    """Each file row in each harness's `pre_write` shape, for a tool its registration's matcher serves; the tool is the
    row's `tool_name`, else the one whose fields the row carries."""
    rows = []
    for fields, tree, by in FILES:
        filled = {key: expand(value, places) if isinstance(value, str) else value for key, value in fields.items()}
        tool = filled.pop("tool_name", None) or ("MultiEdit" if "edits" in filled else "Edit" if "old_string" in filled else "Write")
        for harness in write_harnesses():
            native, payload = fixture_for(harness, "pre_write")
            if "pre_write" not in adapters.events_for(adapters.manifest(harness), native, tool):
                continue  # the harness never sends this tool to the file guard
            rows.append({"label": f"file {fields}", "harness": harness, "native": native, "cwd": places[tree], "env": {},
                         "payload": fill(payload, {"tool": tool, "fields": filled, "cwd": str(places[tree]), "session": "s"}),
                         "by": expected(by, harness)})
    return rows


def cases(places: dict[str, Path]) -> list[dict]:
    """One row per table entry and harness: what to send, where, and what must come back."""
    every = shell_harnesses()
    rows = shell_rows("deny", DENY, places, {}, every) + shell_rows("allow", [(c, t, None) for c, t in ALLOW], places, {}, every)
    for command, tree, by, awk_by, _ in PARSERS_DIFFER:
        rows += [{**row, "awk_by": expected(awk_by, row["harness"])} for row in shell_rows("parsers differ", [(command, tree, by)], places, {}, every)]
    for command, tree, tool, env, by in MISSING:
        rows += [{**row, "loose": True, "missing": (tool,)} for row in shell_rows(f"no-{tool} {env}", [(command, tree, by)], places, env, every)]
    for command, tree, env, by in ENV:
        rows += shell_rows(f"env {env}", [(command, tree, by)], places, env, every)
    for label, *payloads in PAYLOADS:
        rows += [{"label": f"allow payload {label}", "harness": "cursor" if payload["hook_event_name"][:1].islower() else "claude-code",
                  "native": payload["hook_event_name"], "payload": payload, "cwd": places["nogit"], "by": None, "env": {}} for payload in payloads]
    return rows + file_rows(places)


def path_without(home: Path, *tools: str) -> str:
    """PATH with `tools` removed: a directory that holds one of them is replaced by a copy of its links without it, and
    every other directory stays as it is (built once, before any thread runs)."""
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


def bashes(home: Path) -> list[str]:
    """PATH prefixes: none (the bash on PATH), and one whose `bash` is /bin/bash when that is another bash."""
    found = shutil.which("bash") or "/bin/bash"
    if os.path.realpath(found) == os.path.realpath("/bin/bash") or not os.path.exists("/bin/bash"):
        return [""]
    shim = home / "bash32"
    if not shim.is_dir():
        shim.mkdir()
        (shim / "bash").symlink_to("/bin/bash")
    return ["", str(shim)]


def row_env(row: dict, env: dict, home: Path, parser: str, bash: str) -> dict:
    """The row's environment; the awk parser runs with shfmt removed from PATH, a bash prefix goes first."""
    hidden = row.get("missing", ()) + (("shfmt",) if parser == "awk" else ())
    path = path_without(home, *hidden) if hidden else env["PATH"]
    return {**env, **row["env"], "PATH": os.pathsep.join(filter(None, [bash, path]))}


def failure(row: dict, verdict: str, parser: str, bash: str) -> str:
    where = f"{row['label']} [{row['harness']} {row['native']}, {parser}{', /bin/bash' if bash else ''}]"
    by = row.get("awk_by", row["by"]) if parser == "awk" else row["by"]
    if verdict.startswith("error"):
        return f"{where}: {verdict}"
    if by is None and verdict != "allow":
        return f"{where}: denied by {verdict}"
    if by is not None and verdict != f"deny {by}":
        return f"{where}: expected a deny from {by}, got {verdict}"
    return ""


def judge(job: tuple[dict, str, str], env: dict, home: Path) -> str:
    row, parser, bash = job
    return failure(row, run_row(row, row_env(row, env, home, parser, bash)), parser, bash)


RECORDS = 'HOOK_NAME=records; . "$1"; HOOK_CWD=$2; hook_segments "$3"; printf "%s\\n" ${HOOK_SEGS[@]+"${HOOK_SEGS[@]}"} ${HOOK_REDIRS[@]+"${HOOK_REDIRS[@]}"}'


def records(row: dict, env: dict, home: Path, parser: str) -> tuple:
    """What `hook_segments` gives the guards for the row's command, through one parser."""
    done = subprocess.run(["bash", "-c", RECORDS, "records", str(HOOKS / "lib" / "hook.sh"), str(row["cwd"]), row["command"]],
                          capture_output=True, text=True, env=row_env(row, env, home, parser, ""), cwd=str(row["cwd"]), timeout=120)
    return done.returncode, done.stdout, done.stderr


def jobs_for(rows: list[dict], home: Path) -> list[tuple]:
    """Every row through the first parser in every harness; the claude-code rows also under /bin/bash and, when the
    two parsers give different records, through the awk parser."""
    found = parsers()
    jobs = [(row, found[0], "") for row in rows]
    jobs += [(row, found[0], bash) for row in rows if row["harness"] == "claude-code" for bash in bashes(home)[1:]]
    if len(found) == 2:
        jobs += [(row, "awk", "") for row in rows if row["harness"] == "claude-code" and "command" in row]
    return jobs


def fixture_home() -> Path:
    """A home outside /tmp (a bare `mkdtemp` lands there on Linux), as the guards' fixtures expect."""
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
    for key in [k for k in env if k.startswith(("CREW_", "EL_CAPITAN_", "CURSOR_"))]:
        env.pop(key)
    try:
        places: dict[str, Path] = {**fixture(home), "home": home, "tmp": tmp, "tasks": home / ".agent" / "tasks"}
        review = subprocess.run([sys.executable, str(ROOT / "src/crew/review/crew_review_findings.py"), "review-dir", "--repo", "boundary-probe"],
                                capture_output=True, text=True, env=env)
        places["review"] = Path(review.stdout.strip())
        assert review.returncode == 0 and places["review"].is_absolute(), review
        rows = cases(places)
        for missing in {row.get("missing", ()) for row in rows}:
            path_without(home, *missing, "shfmt")
            if missing:
                path_without(home, *missing)
        bashes(home)
        places["no-jq"], places["no-awk"] = Path(path_without(home, "jq")), Path(path_without(home, "awk", "shfmt"))
        yield env, places, rows
    finally:
        shutil.rmtree(home, ignore_errors=True)


def in_parallel(check, jobs: list) -> list[str]:
    """Hook runs are subprocess-bound: threads overlap them, fewer under xdist, whose workers already fill the cores."""
    workers = 4 if os.environ.get("PYTEST_XDIST_WORKER") else max(4, (os.cpu_count() or 2) * 2)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        return [line for line in pool.map(check, jobs) if line]


SLICES = 8


@pytest.mark.parametrize("part", range(SLICES))
def test_hook_cases(part: int, world: tuple) -> None:
    """Every row, in every adapter's shape: deny rows name their rule, allow rows stay silent. The rows are dealt into
    slices so xdist can spread them."""
    env, places, rows = world
    failed = in_parallel(lambda job: judge(job, env, places["home"]), jobs_for(rows, places["home"])[part::SLICES])
    assert not failed, "\n".join(failed)


def test_every_hook_is_in_the_contract() -> None:
    """Every rule script is a contract rule, and every contract rule's script exists."""
    named = {rule["run"] for rule in adapters.contract(HOOKS)["rules"]}
    present = {str(path.relative_to(HOOKS)) for path in HOOKS.rglob("*.sh") if "fixtures" not in path.parts and "lib" not in path.parts}
    assert named == present, (sorted(named - present), sorted(present - named))
    assert {Path(name).name for name in named} - {"shell.sh", *(path.name for path in FILE_HOOKS)} == set(SILENT)


def test_an_unreadable_index_skips_the_commit_scan(world: tuple) -> None:
    """A commit in a repository whose index git cannot read is not scanned: one stderr line, no denial."""
    env, places, _ = world
    native, payload = fixture_for("claude-code", "pre_shell")
    done = hook("claude-code", native, fill(payload, {"command": "git commit -m x", "cwd": str(places["corrupt"])}), env, places["corrupt"])
    assert done.returncode == 0 and "cannot read the git index" in done.stderr, done


def test_a_broken_shfmt_falls_back_to_awk(world: tuple) -> None:
    """A shfmt that prints invalid JSON makes jq fail, and awk then reads the command: the same deny."""
    env, places, _ = world
    stub = places["home"] / "broken-shfmt"
    stub.mkdir(exist_ok=True)
    (stub / "shfmt").write_text("#!/bin/sh\ncat >/dev/null\necho '{'\n", encoding="utf-8")
    (stub / "shfmt").chmod(0o755)
    native, payload = fixture_for("cursor", "pre_shell")
    row = {"harness": "cursor", "native": native, "cwd": places["clean"], "by": "destructive-git", "env": {},
           "payload": fill(payload, {"command": "git reset --hard", "cwd": str(places["clean"])})}
    assert run_row(row, {**env, "PATH": f"{stub}{os.pathsep}{path_without(places['home'], 'shfmt')}"}) == "deny destructive-git"


def test_a_deep_pipeline_is_denied_quickly(world: tuple) -> None:
    """shfmt's JSON grows with nesting depth times size (1.6 GB for this one), so a command this deep is read by awk."""
    if "shfmt" not in parsers():
        pytest.skip("shfmt is not installed; the awk path alone has no JSON to grow")
    env, places, _ = world
    native, payload = fixture_for("cursor", "pre_shell")
    start = time.monotonic()
    done = hook("cursor", native, fill(payload, {"command": "true | " * 3900 + "git reset --hard", "cwd": str(places["clean"])}), env, places["clean"])
    elapsed = time.monotonic() - start
    assert '"deny"' in done.stdout and elapsed < 15, f"{done.stdout[:200]} after {elapsed:.1f}s: {done.stderr[:300]}"


@pytest.mark.parametrize("label, extra, ago, calls", NOTIFY, ids=[row[0] for row in NOTIFY])
def test_idle_notification_is_quiet(label: str, extra: dict, ago: int | None, calls: int, world: tuple) -> None:
    """A banner only, never an app activation; none in a background job, with the off switch, or twice per session in 10 minutes."""
    env, places, _ = world
    home = places["home"] / "notify" / label.replace(" ", "-")
    stub = home / "bin"
    stub.mkdir(parents=True)
    (home / ".agent").mkdir()
    (home / ".agent" / "hooks").symlink_to(HOOKS)
    log = home / "osascript.log"
    (stub / "osascript").write_text(f"#!/bin/sh\nprintf '%s\\n' \"$*\" >> '{log}'\n", encoding="utf-8")
    (stub / "osascript").chmod(0o755)
    stamp = home / ".agent" / "memory" / ".sessions" / (hashlib.sha256(b"s1").hexdigest()[:24] + ".notified")
    if ago is not None:
        stamp.parent.mkdir(parents=True)
        stamp.write_text(f"{int(time.time()) - ago}\n", encoding="utf-8")
    run_env = {k: v for k, v in env.items() if k not in ("CLAUDE_JOB_DIR", "CREW_MEMORY_DIR", "EL_CAPITAN_NOTIFY")}
    run_env.update(extra, HOME=str(home), PATH=f"{stub}{os.pathsep}{env['PATH']}")
    native, payload = fixture_for("claude-code", "idle")
    done = hook("claude-code", native, fill(payload, {"session": "s1", "cwd": str(places["clean"])}), run_env, places["clean"])
    lines = log.read_text(encoding="utf-8").splitlines() if log.exists() else []
    assert (done.returncode, done.stdout, done.stderr) == (0, "", ""), done
    assert len(lines) == calls and not any("activate" in line for line in lines), lines


@pytest.mark.parametrize("event", ["pre_shell", "pre_write", "post_shell", "subagent_stop", "stop", "session_start"])
def test_cursors_copy_of_a_claude_registration_does_nothing_beside_the_plugin(event: str, world: tuple) -> None:
    """Cursor also runs the Claude-format registrations: while the plugin's hooks are installed, that copy
    (`cursor_version` in the payload) answers nothing and changes nothing; without them it is judged."""
    env, places, _ = world
    native, payload = fixture_for("claude-code", event)
    spec = str(places["tasks"] / "DDD-status" / "SPEC.md")
    values = {"command": "git reset --hard", "cwd": str(places["clean"]), "tool": "Write", "fields": {"file_path": spec}}
    copy = {**fill(payload, values), "cursor_version": "2.1.0"}
    plugin = places["home"] / cursor.PLUGIN / "hooks" / "hooks.json"
    plugin.parent.mkdir(parents=True, exist_ok=True)
    plugin.write_text("{}", encoding="utf-8")
    try:
        done = hook("claude-code", native, copy, env, places["clean"])
    finally:
        plugin.unlink()
    assert (done.returncode, done.stdout, done.stderr) == (0, "", ""), done
    if event == "pre_shell":
        judged = hook("claude-code", native, copy, env, places["clean"])
        assert judged.returncode == 2 and "EL_CAPITAN_GUARD_DESTRUCTIVE_GIT" in judged.stderr, judged


@pytest.mark.parametrize("harness", adapters.IDS)
def test_an_unreadable_payload_is_denied_where_a_closed_rule_judges(harness: str, world: tuple) -> None:
    """An internal error (here a payload that is not JSON) answers deny for an event a closed rule serves, and allow for
    one only open rules serve, with one stderr line either way."""
    env, places, _ = world
    for event, verdict in (("pre_shell", "deny"), ("stop", "allow")):
        native, _ = fixture_for(harness, event)
        done = subprocess.run([sys.executable, "-m", "crew.harness.crew_hook", harness, native], input="{not json", capture_output=True, text=True, env=env)
        assert decode(done.returncode, done.stdout.strip(), done.stderr.strip(), loose=True)[0] == verdict, (event, done)


@pytest.mark.parametrize("label, script, fail, timeout, version, verdict", [
    ("a missing closed rule", None, "closed", 5, 1, "deny"),
    ("a closed rule that crashes", "exit 3", "closed", 5, 1, "deny"),
    ("a closed rule that times out", "sleep 3", "closed", 0.3, 1, "deny"),
    ("an open rule that crashes", "exit 3", "open", 5, 1, "allow"),
    ("rules of another version than crew-hook", "exit 0", "closed", 5, 99, "deny"),
])
def test_a_closed_rule_that_cannot_judge_denies(label: str, script: str | None, fail: str, timeout: float, version: int, verdict: str, tmp: Path) -> None:
    """A `fail: closed` rule that is missing, fails or times out denies the call, and so do rules stamped with another
    version (re-run install.sh); an open rule that fails is skipped."""
    home = tmp / "home"
    (home / ".agent" / "hooks").mkdir(parents=True)
    rule = {"name": "probe-rule", "event": "pre_shell", "run": "probe-rule.sh", "fail": fail, "timeout": timeout}
    (home / ".agent" / "hooks" / "contract.json").write_text(json.dumps({"version": version, "rules": [rule]}), encoding="utf-8")
    if script:
        (home / ".agent" / "hooks" / "probe-rule.sh").write_text(script + "\n", encoding="utf-8")
    native, payload = fixture_for("cursor", "pre_shell")
    done = hook("cursor", native, fill(payload, {"command": "ls", "cwd": str(tmp)}), {**os.environ, "HOME": str(home)}, tmp)
    said = decode(done.returncode, done.stdout.strip(), done.stderr.strip(), loose=True)
    assert said[0] == verdict and (verdict == "allow" or "crew doctor" in said[1] or "re-run install.sh" in said[1]), (label, done)


def unreadable(job: tuple[Path, str, str], env: dict, places: dict[str, str]) -> str:
    """A rule that cannot read its event or lacks `jq` reports one line and gets out of the way."""
    script, label, stdin = job
    blocking = script in GUARDS + FILE_HOOKS
    run_env = {**env, "PATH": places[label.replace(" ", "-")]} if label in ("no jq", "no awk") else env
    done = subprocess.run(["bash", str(script)], input=stdin, capture_output=True, text=True, env=run_env, cwd=places["nogit"], timeout=120)
    lines = len(done.stderr.strip().splitlines())
    expected = 0 if label == "empty input" else 1  # no input is an empty event: nothing to judge, nothing to say
    ok = done.returncode == 0 and (lines == expected and done.stdout.strip() == "" if blocking else lines <= 1)
    if label == "no awk":  # a rule that needs awk says so in one line; one that does not judges as usual
        ok = done.returncode == 0 and lines <= 1 and "not found" not in done.stderr
    return "" if ok else f"{script.name} {label}: exit {done.returncode} stdout={done.stdout[:200]!r} stderr={done.stderr[:300]!r}"


def test_every_rule_survives_bad_input(world: tuple) -> None:
    env, places, _ = world
    probe = json.dumps({"event": "pre_shell", "harness": "cursor", "input": {"command": "git reset --hard", "file_path": "/outside/file"}})
    scripts = [HOOKS / rule["run"] for rule in adapters.contract(HOOKS)["rules"]]
    inputs = (("malformed JSON", "{not json"), ("empty input", ""), ("no jq", probe), ("no awk", probe))
    failed = in_parallel(lambda job: unreadable(job, env, {k: str(v) for k, v in places.items()}), [(s, label, i) for s in scripts for label, i in inputs])
    assert not failed, "\n".join(failed)


# Render goldens.
CAPABILITIES = ("always_on", "rules", "agents", "skills", "max_turns", "mcp")


@pytest.mark.parametrize("harness", adapters.IDS)
def test_every_capability_has_a_value_or_a_fallback(harness: str) -> None:
    spec = adapters.manifest(harness)
    events = adapters.contract(HOOKS)["events"]
    missing = [event for event in events if not (spec["events"].get(event, {}).get("native") or spec["events"].get(event, {}).get("fallback"))]
    missing += [name for name in CAPABILITIES if not (spec.get(name, {}).get("value") or spec.get(name, {}).get("fallback"))]
    missing += [f"access.{kind}" for kind in adapters.ACCESS if not spec.get("access", {}).get(kind)]
    missing += [] if "*" in spec["deny"]["modes"] and spec["deny"].get("why") else ["deny"]
    assert not missing and spec["live"], missing


def registered(harness: str, home: Path) -> list[dict]:
    """The registrations each harness's rendered config holds: (event, matcher, command, fail closed, timeout)."""
    rendered = adapters.adapter(harness).render(ROOT, home)
    if harness == "claude-code":
        hooks = json.loads(rendered[".claude/settings.json"][1])["hooks"]
    elif harness == "codex":
        hooks = json.loads(rendered[".codex/hooks.json"][1])["hooks"]
    else:
        hooks = {event: [{"matcher": e.get("matcher"), "hooks": [e]} for e in entries]
                 for event, entries in json.loads(cursor.render(ROOT, home)[f"{cursor.PLUGIN}/hooks/hooks.json"][1])["hooks"].items()}
    return [{"event": event, "matcher": entry.get("matcher"), "command": hook["command"], "closed": hook.get("failClosed") is True, "timeout": hook["timeout"]}
            for event, entries in hooks.items() for entry in entries for hook in entry["hooks"]]


@pytest.mark.parametrize("harness", adapters.IDS)
def test_each_rule_is_registered_once_with_its_fail_mode_and_timeout(harness: str, tmp: Path) -> None:
    """Each contract rule's canonical event is served by one registration per native event its manifest maps, which
    runs `crew-hook.py <harness> <event>`, fails closed in Cursor exactly when a rule it serves does, and allows the
    rule's timeout; no other registration exists."""
    spec, rules = adapters.manifest(harness), adapters.contract(HOOKS)["rules"]
    found = registered(harness, tmp)
    own = "cursor" if harness == "cursor-cli" else harness  # the CLI loads the cursor plugin
    natives = {native for event in spec["events"].values() for native in adapters.natives(event)}
    assert sorted(entry["event"] for entry in found) == sorted(natives), found
    for entry in found:
        assert entry["command"] == f'{adapters.ENTRY} {own} {entry["event"]}', entry
        served = [rule for rule in rules for event, mapped in spec["events"].items() if rule["event"] == event and entry["event"] in adapters.natives(mapped)]
        assert served and entry["timeout"] >= max(rule["timeout"] for rule in served), entry
        assert entry["closed"] == (own == "cursor" and any(rule["fail"] == "closed" for rule in served)), entry


@pytest.mark.parametrize("harness", adapters.IDS)
def test_each_rendered_path_is_one_its_manifest_declares(harness: str, tmp: Path) -> None:
    declared = adapters.manifest(harness)["paths"]
    stray = [rel for rel in adapters.adapter(harness).render(ROOT, tmp) if not rel.startswith(tuple(declared))]
    assert not stray, stray


def test_the_cursor_cli_shares_the_cursor_plugin(tmp: Path) -> None:
    """The CLI loads the local plugin: its manifest maps the same native events, and its own render is the deny tokens."""
    assert adapters.manifest("cursor-cli")["events"] == adapters.manifest("cursor")["events"]
    assert list(adapters.adapter("cursor-cli").render(ROOT, tmp)) == [".cursor/cli-config.json"]


def test_each_always_on_rule_is_delivered(tmp: Path) -> None:
    """Claude Code imports each always-on rule from a file its adapter renders; the plugin carries each with
    `alwaysApply: true`; Codex declares its fallback."""
    on = adapters.always_on(ROOT)
    blocks = (ROOT / ".claude" / "CLAUDE.md").read_text(encoding="utf-8")
    rendered = claude_code.render(ROOT, tmp)
    assert on and all(f"@~/.claude/el-capitan/{stem}.md" in blocks and f".claude/el-capitan/{stem}.md" in rendered for stem in on), on
    plugin = cursor.render(ROOT, tmp)
    assert all(f"{cursor.PLUGIN}/rules/{stem}.mdc" in plugin for stem in on)
    assert adapters.manifest("codex")["always_on"].get("fallback")


def test_access_classes_are_mapped(tmp: Path) -> None:
    """Every agent has an access class; Codex renders each dispatched one with that class's sandbox, never an inline
    orchestrator; Claude Code and the plugin carry every agent."""
    kinds = {agent.stem: adapters.access(agent) for agent in adapters.agents(ROOT)}
    assert set(kinds.values()) == set(adapters.ACCESS), kinds
    rendered = codex.render(ROOT, tmp)
    sandbox = adapters.manifest("codex")["sandbox"]
    for name, kind in kinds.items():
        toml = rendered.get(f".codex/agents/{name}.toml")
        assert (toml is None) if kind == "inline" else f'sandbox_mode = "{sandbox[kind]}"' in toml[1], (name, kind)
        assert f".claude/agents/{name}.md" in claude_code.render(ROOT, tmp) and f"{cursor.PLUGIN}/agents/{name}.md" in cursor.render(ROOT, tmp)
    assert 'prefix_rule(pattern = ["git", "reset", "--hard"], decision = "forbidden")' in rendered[".codex/rules/el-capitan.rules"][1]


@pytest.mark.parametrize("harness", adapters.IDS)
def test_every_mapped_event_has_a_fixture_that_normalises(harness: str) -> None:
    """Each native event the manifest maps has a fixture, and the adapter normalises it into the events it serves."""
    spec = adapters.manifest(harness)
    for event, mapped in spec["events"].items():
        if not mapped.get("native"):
            continue
        native, payload = fixture_for(harness, event)
        values = {"command": "ls", "cwd": "/", "tool": "Write", "fields": {}, "session": "s"}
        normal = adapters.adapter(harness).normalize(native, fill(payload, values))
        assert normal and event in normal["events"] and normal["harness"] == harness, (event, normal)


def test_doctor_compares_the_installed_files_with_render(tmp: Path) -> None:
    """After `apply`, `diff` finds nothing; one rendered file edited by hand is named."""
    home = tmp / "home"
    (home / ".agent").mkdir(parents=True)
    harness_install.apply(ROOT, home)
    assert harness_install.diff(ROOT, home) == []
    plugin_hooks = home / cursor.PLUGIN / "hooks" / "hooks.json"
    plugin_hooks.write_text("{}", encoding="utf-8")
    assert harness_install.diff(ROOT, home) == [f"~/{cursor.PLUGIN}/hooks/hooks.json differs from its render"]
