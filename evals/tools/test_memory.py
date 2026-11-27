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
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HOOKS = ROOT / ".claude" / "hooks"
INBOX = ROOT / ".agent" / "tools" / "memory" / "crew-inbox.py"
for directory in (ROOT / ".agent" / "tools" / "memory", ROOT / ".agent" / "tools" / "task"):
    sys.path.insert(0, str(directory))
FAILED: list[str] = []
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
    print(("pass: " if condition else "FAIL: ") + name + ("" if condition else f": {detail}"))
    if not condition:
        FAILED.append(name)


def store() -> Path:
    root = Path(tempfile.mkdtemp(prefix="memory-"))
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


def telemetry_cases() -> None:
    """log-tool-use records both shapes; its session name is the one the capture hook reads."""
    root = store()
    try:
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
    finally:
        shutil.rmtree(root, ignore_errors=True)


def inbox_cases() -> None:
    root = store()
    try:
        empty = inbox(root)
        check("an empty inbox says so and exits 0", (empty.returncode, empty.stdout.strip()) == (0, "inbox: empty"), empty.stdout)
        (root / ".inbox" / "procedure-probe.md").write_text(DRAFT.format(id="probe", title="Probe draft"), encoding="utf-8")
        (root / ".sessions" / "review-queue.jsonl").write_text(json.dumps({"session": "s1", "substantive": 2}) + "\n", encoding="utf-8")
        body = json.loads(inbox(root, "--json").stdout or "{}")
        check("the inbox lists the draft with its title and the queued review",
              [d["title"] for d in body.get("drafts", [])] == ["Probe draft"] and len(body.get("queued_reviews", [])) == 1, body)
        drained = inbox(root, "--drain")
        check("drain clears the ask log and leaves the drafts alone",
              not (root / ".sessions" / "review-queue.jsonl").exists() and (root / ".inbox" / "procedure-probe.md").is_file(), drained.stdout)
    finally:
        shutil.rmtree(root, ignore_errors=True)


def key_cases() -> None:
    import memory_bootstrap  # noqa: F401

    import memory_paths
    import task_repo_facts

    check("a checkout with neither upstream nor origin reports its first remote",
          task_repo_facts.primary_remote(["fork", "mirror"]) == "fork")
    check("upstream wins over origin, whatever the order", task_repo_facts.primary_remote(["origin", "upstream"]) == "upstream")
    saved_cwd, saved_env = os.getcwd(), os.environ.get("GIT_CONFIG_GLOBAL")
    os.environ["GIT_CONFIG_GLOBAL"] = os.devnull
    try:
        with tempfile.TemporaryDirectory() as temp:
            for index, (case, url, expected) in enumerate(KEYS):
                checkout = Path(temp) / str(index) / "checkout"
                checkout.mkdir(parents=True)
                subprocess.run(["git", "init", "-q", str(checkout)], check=True)
                if url:
                    subprocess.run(["git", "-C", str(checkout), "remote", "add", "origin", url], check=True)
                os.chdir(checkout)
                check(f"{case}: key is {expected}", memory_paths.repo_key() == expected, memory_paths.repo_key())
                if url:
                    with contextlib.redirect_stderr(io.StringIO()):  # an unborn HEAD is reported, and is not the case
                        named = task_repo_facts.collect(argparse.Namespace(root=None, remote=None, network=False))["repo_name"]
                    check(f"{case}: crew-repo-info's repo_name is the same {expected}", named == expected, named)
    finally:
        os.chdir(saved_cwd)
        if saved_env is None:
            os.environ.pop("GIT_CONFIG_GLOBAL", None)
        else:
            os.environ["GIT_CONFIG_GLOBAL"] = saved_env


def main() -> int:
    telemetry_cases()
    inbox_cases()
    key_cases()
    print("memory: fail" if FAILED else "memory: pass")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
