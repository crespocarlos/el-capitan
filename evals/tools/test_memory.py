#!/usr/bin/env python3
"""Memory: session telemetry, the capture review that reaches a human, the inbox, and the scope key.

The telemetry and capture hooks run for real against a throwaway memory root, so the guard/queue
ordering is observed rather than assumed: the review is queued before the guard is written, and a
session that was asked once stays silent. `crew-inbox.py` is the read side. `repo_key` is the memory
scope a checkout resolves to; a key that changes orphans every unit stored under the old one, and
`crew-repo-info.py --field repo_name` must give the same name, because recall scopes by it.
"""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import io
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
HOOKS = ROOT / ".claude" / "hooks"
INBOX = ROOT / ".agent" / "tools" / "memory" / "crew-inbox.py"
for directory in (ROOT / ".agent" / "tools" / "memory", ROOT / ".agent" / "tools" / "task"):
    sys.path.insert(0, str(directory))
# Both harness shapes, with quotes and non-ASCII in the command and the session id.
TELEMETRY = (
    {"session_id": "claude-✓", "hook_event_name": "PostToolUse", "tool_input": {"command": 'echo "quotes" é→✓'}},
    {"conversation_id": "cursor-✓", "hook_event_name": "postToolUse", "command": 'echo "quotes" é→✓'},
)
# (case, origin URL or None, the key repo_key must return for a checkout named "checkout")
KEYS = (
    ("https remote", "https://github.com/acme/gadgets.git", "gadgets"),
    ("scp remote", "git@github.com:acme/gizmos.git", "gizmos"),
    ("ssh:// remote", "ssh://git@github.com/acme/sprockets.git", "sprockets"),
    ("ssh-alias remote (no user)", "github-work:acme/cogs.git", "cogs"),
    ("git:// remote", "git://github.com/acme/levers", "levers"),
    ("local-path remote", "/srv/git/widgets.git", "widgets"),
    ("file:// remote", "file:///srv/git/tools.git", "tools"),
    ("no remote", None, "checkout"),
)
DRAFT = ("---\nid: procedure-{id}\ntype: procedure\nscope: global\ntitle: {title}\n"
         "status: active\ncreated: 2026-01-01\nmodified: 2026-01-01\nevidence: [x]\n---\nBody.\n")


def check(name: str, condition: bool, detail: object = "") -> None:
    assert condition, f"{name}: {detail}"


def store(root: Path) -> Path:
    (root / ".inbox").mkdir(parents=True)
    (root / ".sessions").mkdir(parents=True)
    return root


def hook(name: str, root: Path, payload: dict) -> tuple[int, dict]:
    result = subprocess.run(["bash", str(HOOKS / name)], input=json.dumps(payload), capture_output=True, text=True,
                            env={**os.environ, "CREW_MEMORY_DIR": str(root)})
    try:
        return result.returncode, json.loads(result.stdout or "{}")
    except json.JSONDecodeError:
        return result.returncode, {"<unparsed>": result.stdout[:200]}


def hashed(session_id: str) -> str:
    """The name both hooks give a session's files: the raw id is never written."""
    return hashlib.sha256(session_id.encode()).hexdigest()[:24]


def queue(root: Path) -> list[dict]:
    path = root / ".sessions" / "review-queue.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()] if path.is_file() else []


def inbox(root: Path, *arguments: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(INBOX), *arguments], capture_output=True, text=True,
                          env={**os.environ, "CREW_MEMORY_DIR": str(root)})


def test_telemetry_and_capture_prompt(tmp: Path) -> None:
    """log-tool-use records both shapes; its session name is the one the capture hook reads."""
    root = store(tmp)
    for payload in TELEMETRY:
        code, body = hook("log-tool-use.sh", root, payload)
        check(f"log-tool-use answers {{}} for {payload['hook_event_name']}", (code, body) == (0, {}), (code, body))
    records = [json.loads(line) for path in (root / ".sessions").glob("*.jsonl") for line in path.read_text().splitlines()]
    check("each record carries event, action and target", len(records) == 2 and all(r["event"] and r["action"] and r["target"] for r in records), records)
    for _ in range(2):
        hook("log-tool-use.sh", root, {"session_id": "s-edit", "hook_event_name": "PostToolUse", "tool_input": {"file_path": "/x/a.py"}})
    code, body = hook("memory-capture-prompt.sh", root, {"hook_event_name": "Stop", "session_id": "s-edit"})
    check("a session with edits returns a followup", "followup_message" in body, body)
    check("the review is queued before the guard is written",
          len(queue(root)) == 1 and (root / ".sessions" / f"{hashed('s-edit')}.memory-prompted").is_file(), queue(root))
    code, again = hook("memory-capture-prompt.sh", root, {"hook_event_name": "Stop", "session_id": "s-edit"})
    check("a second stop is silent and queues nothing", again == {} and len(queue(root)) == 1, (again, queue(root)))
    code, body = hook("memory-capture-prompt.sh", root, {"hook_event_name": "Stop", "session_id": "no-events"})
    check("a session with no telemetry says nothing", body == {}, body)
    (root / ".sessions" / f"{hashed('quiet')}.jsonl").write_text('{"action": "read", "failure": false}\n', encoding="utf-8")
    code, body = hook("memory-capture-prompt.sh", root, {"hook_event_name": "Stop", "session_id": "quiet"})
    check("a read-only session says nothing, queues nothing and writes no guard",
          body == {} and len(queue(root)) == 1 and not (root / ".sessions" / f"{hashed('quiet')}.memory-prompted").exists(), body)


def test_inbox(tmp: Path) -> None:
    root = store(tmp)
    empty = inbox(root)
    check("an empty inbox says so and exits 0", (empty.returncode, empty.stdout.strip()) == (0, "inbox: empty"), empty.stdout)
    (root / ".inbox" / "procedure-probe.md").write_text(DRAFT.format(id="probe", title="Probe draft"), encoding="utf-8")
    (root / ".sessions" / "review-queue.jsonl").write_text(json.dumps({"session": "s1", "substantive": 2}) + "\n", encoding="utf-8")
    body = json.loads(inbox(root, "--json").stdout or "{}")
    check("the inbox lists the draft with its title and the queued review",
          [d["title"] for d in body.get("drafts", [])] == ["Probe draft"] and len(body.get("queued_reviews", [])) == 1, body)
    old = root / ".inbox" / "procedure-old.md"
    old.write_text(DRAFT.format(id="old", title="Old draft"), encoding="utf-8")
    os.utime(old, (1_700_000_000, 1_700_000_000))
    scoped = json.loads(inbox(root, "--json", "--since", "2024-01-01T00:00:00Z").stdout or "{}")
    shown = inbox(root, "--since", "2024-01-01T00:00:00Z").stdout
    check("--since lists only the drafts written after it and counts the rest",
          [d["title"] for d in scoped.get("drafts", [])] == ["Probe draft"] and scoped.get("older") == 1
          and "since 2024-01-01T00:00:00Z" in shown and "Old draft" not in shown, (scoped, shown))
    drained = inbox(root, "--drain")
    check("drain clears the ask log and leaves the drafts alone",
          not (root / ".sessions" / "review-queue.jsonl").exists() and (root / ".inbox" / "procedure-probe.md").is_file(), drained.stdout)


def test_add_cite_and_journal_round_trip(tmp: Path) -> None:
    """The write side the prompts use: `add` a unit from stdin, `cite` it, `journal add` an entry."""
    from cli_runner import run as cli

    env = {"CREW_MEMORY_DIR": str(tmp / "memory"), "CREW_JOURNAL_DIR": str(tmp / "journal"), "HOME": str(tmp)}

    def mem(*arguments: str, stdin: str = "") -> subprocess.CompletedProcess:
        return cli(ROOT / ".agent" / "tools" / "memory" / "crew-mem.py", *arguments, env=env, cwd=tmp, stdin=stdin)

    check("init prepares the store", mem("init").returncode == 0)
    added = mem("add", "--type", "procedure", "--scope", "global", "--title", "Run the hook suite first",
                "--evidence", "x", stdin="Run the hook suite before any guard change.\n")
    check("add writes one unit", added.returncode == 0, added.stderr)
    units = json.loads(mem("list", "--json").stdout)
    unit = units[0] if isinstance(units, list) and units else {}
    check("list shows the unit with its title", unit.get("title") == "Run the hook suite first", units)
    cited = mem("cite", "--outcome", "helped", unit.get("id", "none"))
    check("cite records the outcome on the unit", cited.returncode == 0 and "helped: 1" in next(
        (tmp / "memory").rglob(f"*{unit.get('id', 'none').split('-', 1)[-1]}*.md")).read_text(), cited.stderr)
    journal = mem("journal", "add", "--title", "PR review: probe", "--tags", "probe", "--repo", "demo",
                  stdin="The probe confirmed the guard runs first.\n")
    stored = list((tmp / "memory" / "observations" / "demo").glob("observation-*.md"))
    check("journal add stores the entry as one observation in its repo's scope",
          journal.returncode == 0 and len(stored) == 1, journal.stderr)
    (tmp / "not-a-dir").write_text("x", encoding="utf-8")
    env["CREW_MEMORY_DIR"] = str(tmp / "not-a-dir" / "memory")
    plain, warned = mem("context", "--query", "x"), mem("context", "--query", "x", "--warn-unavailable")
    check("an unavailable store exits 2, or with --warn-unavailable prints none and a warning and exits 0",
          plain.returncode == 2 and (warned.returncode, warned.stdout.strip()) == (0, "none")
          and "warning: memory unavailable" in warned.stderr, (plain.returncode, warned.stdout, warned.stderr))


def test_primary_remote() -> None:
    import memory_bootstrap  # noqa: F401

    import task_repo_facts

    check("a checkout with neither upstream nor origin reports its first remote",
          task_repo_facts.primary_remote(["fork", "mirror"]) == "fork")
    check("upstream wins over origin, whatever the order", task_repo_facts.primary_remote(["origin", "upstream"]) == "upstream")


@pytest.mark.parametrize("case,url,expected", KEYS)
def test_repo_key(case: str, url: str | None, expected: str, tmp: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import memory_bootstrap  # noqa: F401

    import memory_paths
    import task_repo_facts

    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    checkout = tmp / "checkout"
    checkout.mkdir()
    subprocess.run(["git", "init", "-q", str(checkout)], check=True)
    if url:
        subprocess.run(["git", "-C", str(checkout), "remote", "add", "origin", url], check=True)
    monkeypatch.chdir(checkout)
    check(f"{case}: key is {expected}", memory_paths.repo_key() == expected, memory_paths.repo_key())
    if url:
        with contextlib.redirect_stderr(io.StringIO()):  # an unborn HEAD is reported, and is not the case
            named = task_repo_facts.collect(argparse.Namespace(root=None, remote=None, network=False))["repo_name"]
        check(f"{case}: crew-repo-info's repo_name is the same {expected}", named == expected, named)
