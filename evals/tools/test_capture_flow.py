#!/usr/bin/env python3
"""A memory-capture review must reach a human even when the turn that produced it cannot ask.

Two failures produced silent drafts: a subagent's question ends into a parent transcript that is
already finished, and a session that asked once was never asked again because the guard was written
before the ask. The hook now queues the review and the guard is written only after the queue entry
exists; `crew-inbox.py` is the read side that surfaces it.

These cases drive the real hook against a throwaway memory root, so the guard/queue ordering is
observed rather than assumed.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HOOK = ROOT / ".claude/hooks/memory-capture-prompt.sh"
INBOX = ROOT / ".agent/tools/memory/crew-inbox.py"
FAILED: list[str] = []


def check(name: str, condition: bool, detail: object = "") -> None:
    if condition:
        print(f"pass: {name}")
        return
    FAILED.append(name)
    print(f"FAIL: {name}{': ' + str(detail) if detail else ''}")


def store() -> Path:
    root = Path(tempfile.mkdtemp(prefix="capture-hook-"))
    (root / ".inbox").mkdir(parents=True)
    (root / ".sessions").mkdir(parents=True)
    return root


def events(root: Path, session_id: str, substantive: int = 2, failures: int = 0) -> str:
    """Write this session's telemetry under the name the hook derives, and return that name.

    The hook hashes the raw session id before naming the telemetry file, so a test that wrote the raw
    id would exercise the "no telemetry" path and prove nothing.
    """
    hashed = hashlib.sha256(session_id.encode()).hexdigest()[:24]
    lines = [json.dumps({"action": "file-edit", "failure": False}) for _ in range(substantive)]
    lines += [json.dumps({"action": "read", "failure": True}) for _ in range(failures)]
    (root / ".sessions" / f"{hashed}.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return hashed


def run_hook(root: Path, payload: dict) -> tuple[int, dict]:
    env = {**os.environ, "CREW_MEMORY_DIR": str(root)}
    result = subprocess.run(["bash", str(HOOK)], input=json.dumps(payload), capture_output=True,
                            text=True, env=env)
    try:
        body = json.loads(result.stdout or "{}")
    except json.JSONDecodeError:
        body = {"<unparsed>": result.stdout[:200]}
    return result.returncode, body


def queue(root: Path) -> list[dict]:
    path = root / ".sessions" / "review-queue.jsonl"
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def capture_cases() -> None:
    root = store()
    try:
        session = "abc123"
        hashed = events(root, session)
        code, body = run_hook(root, {"hook_event_name": "Stop", "session_id": session})
        check("a substantive session returns a followup", "followup_message" in body, body)
        check("the review is queued before the guard", len(queue(root)) == 1, queue(root))
        check("the guard exists after the ask", (root / ".sessions" / f"{hashed}.memory-prompted").is_file())

        code, again = run_hook(root, {"hook_event_name": "Stop", "session_id": session})
        check("a second stop does not queue twice", len(queue(root)) == 1, queue(root))
        check("a second stop stays silent", again == {}, again)
    finally:
        shutil.rmtree(root, ignore_errors=True)


def quiet_cases() -> None:
    root = store()
    try:
        session = "quiet"
        (root / ".sessions" / f"{session}.jsonl").write_text('{"action": "read", "failure": false}\n',
                                                            encoding="utf-8")
        code, body = run_hook(root, {"hook_event_name": "Stop", "session_id": session})
        check("an empty session says nothing", body == {}, body)
        check("an empty session queues nothing", queue(root) == [], queue(root))
        check("an empty session writes no guard",
              not (root / ".sessions" / f"{session}.memory-prompted").exists())
    finally:
        shutil.rmtree(root, ignore_errors=True)

    root = store()
    try:
        code, body = run_hook(root, {"hook_event_name": "Stop", "session_id": "noevents"})
        check("a session with no telemetry says nothing", body == {}, body)
    finally:
        shutil.rmtree(root, ignore_errors=True)


def inbox_cases() -> None:
    root = store()
    try:
        (root / ".inbox" / "procedure-probe.md").write_text(
            "---\nid: procedure-probe\ntype: procedure\nscope: global\ntitle: Probe draft\n"
            "status: active\ncreated: 2026-01-01\nmodified: 2026-01-01\nevidence: [x]\n---\nBody.\n",
            encoding="utf-8")
        result = subprocess.run([sys.executable, str(INBOX), "--json"], capture_output=True, text=True,
                                env={**os.environ, "CREW_MEMORY_DIR": str(root)})
        body = json.loads(result.stdout or "{}")
        check("the inbox reporter lists the draft", len(body.get("drafts", [])) == 1, body)
        check("the draft carries its title", body["drafts"][0]["title"] == "Probe draft", body)

        (root / ".sessions" / "review-queue.jsonl").write_text(
            json.dumps({"session": "s1", "substantive": 2}) + "\n", encoding="utf-8")
        result = subprocess.run([sys.executable, str(INBOX), "--json"], capture_output=True, text=True,
                                env={**os.environ, "CREW_MEMORY_DIR": str(root)})
        body = json.loads(result.stdout or "{}")
        check("the inbox reporter lists queued reviews", len(body.get("queued_reviews", [])) == 1, body)
    finally:
        shutil.rmtree(root, ignore_errors=True)

    root = store()
    try:
        result = subprocess.run([sys.executable, str(INBOX)], capture_output=True, text=True,
                                env={**os.environ, "CREW_MEMORY_DIR": str(root)})
        check("an empty inbox says so", result.stdout.strip() == "inbox: empty", result.stdout)
        check("an empty inbox exits 0", result.returncode == 0, result.returncode)

        (root / ".inbox" / "procedure-keep.md").write_text(
            "---\nid: procedure-keep\ntype: procedure\nscope: global\ntitle: Keep me\n"
            "status: active\ncreated: 2026-01-01\nmodified: 2026-01-01\nevidence: [x]\n---\nB.\n",
            encoding="utf-8")
        (root / ".sessions" / "review-queue.jsonl").write_text('{"session":"s"}\n', encoding="utf-8")
        drained = subprocess.run([sys.executable, str(INBOX), "--drain"], capture_output=True,
                                 text=True, env={**os.environ, "CREW_MEMORY_DIR": str(root)})
        check("drain clears the ask log", not (root / ".sessions" / "review-queue.jsonl").exists(),
              drained.stdout)
        check("drain leaves the drafts alone", (root / ".inbox" / "procedure-keep.md").is_file())
    finally:
        shutil.rmtree(root, ignore_errors=True)


def main() -> int:
    capture_cases()
    quiet_cases()
    inbox_cases()
    print("all capture-flow checks passed" if not FAILED else f"capture-flow: {len(FAILED)} failed")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
