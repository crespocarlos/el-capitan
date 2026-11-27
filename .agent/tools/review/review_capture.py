"""Reply capture: `expect` writes a persona's nonce at dispatch; `capture` (the `SubagentStop` hook) saves its reply.

The marker `crew-review-out: <review dir> <persona> <nonce>` in the subagent's first user message names the reply's
place, and counts only when `<persona>.expect` holds that nonce, or, with no `.expect`, for a resume of the agent
that saved it. The reply is the `SubagentHandback` message, else the last assistant message, saved by `store_reply`;
another agent's reply is never overwritten. The same run's token usage goes to its task (`task_usage`). Exit 0.
"""
from __future__ import annotations

import argparse
import hmac
import json
import re
import secrets
import sys
from pathlib import Path

from review_render import provenance_path, saved_persona, store_reply
from task_usage import record_usage

from lib.files import atomic_write

MARKER = re.compile(r"^crew-review-out: (.+) (\S+) ([0-9a-f]{32})[ \t]*$", re.M)
HANDBACK = "SubagentHandback"


def add_capture_parsers(commands) -> None:
    expect = commands.add_parser("expect", help="write <persona>.expect and print the dispatch marker line")
    expect.add_argument("--review-dir", required=True, type=Path)
    expect.add_argument("--persona", required=True)
    commands.add_parser("capture", help="the SubagentStop hook: save the reply its marker names (payload on stdin)")


def expect(args: argparse.Namespace) -> int:
    """Write a fresh nonce to `<persona>.expect` and print the marker line the dispatch prompt carries."""
    persona = saved_persona(args.persona)
    if not args.review_dir.is_dir():
        raise ValueError(f"no such review directory: {args.review_dir}")
    nonce = secrets.token_hex(16)
    atomic_write(args.review_dir / f"{persona}.expect", nonce + "\n")
    print(f"crew-review-out: {args.review_dir.resolve()} {persona} {nonce}")
    return 0


def entries(path: Path) -> list[dict]:
    """The transcript's JSON lines that are objects; a line that does not parse is skipped."""
    found = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            item = json.loads(line)
        except ValueError:
            continue
        if isinstance(item, dict) and isinstance(item.get("message"), dict):
            found.append(item)
    return found


def text_of(content: object) -> str:
    """The text of a message's content: a string, or its text blocks joined."""
    if isinstance(content, str):
        return content
    blocks = content if isinstance(content, list) else []
    texts = [block for block in blocks if isinstance(block, dict) and block.get("type") == "text"]
    return "\n".join(str(block.get("text") or "") for block in texts)


def first_prompt(found: list[dict]) -> str:
    """The text of the first user message: the dispatch prompt."""
    return next((text_of(item["message"].get("content")) for item in found if item.get("type") == "user"), "")


def handback(found: list[dict]) -> str:
    """The `message` of the last `SubagentHandback` call, or ""."""
    for item in reversed(found):
        content = item["message"].get("content")
        for block in reversed(content if isinstance(content, list) else []):
            if isinstance(block, dict) and block.get("type") == "tool_use" and block.get("name") == HANDBACK:
                message = (block.get("input") or {}).get("message")
                if isinstance(message, str) and message.strip():
                    return message
    return ""


def model_of(found: list[dict]) -> str | None:
    """The model of the last assistant message, or None."""
    return next((str(item["message"]["model"]) for item in reversed(found)
                 if item.get("type") == "assistant" and item["message"].get("model")), None)


def saved_by(review_dir: Path, persona: str) -> str | None:
    """The agent id recorded for an existing reply: None when there is none, "" when it carries no id."""
    if not (review_dir / f"{persona}.out.md").exists():
        return None
    try:
        record = json.loads(provenance_path(review_dir, persona).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    return str(record.get("agent_id") or "") if isinstance(record, dict) else ""


def save_reply(payload: dict, found: list[dict], match: re.Match | None) -> str:
    """Save the reply the marker names; the one line saying what happened."""
    agent = str(payload.get("agent_id") or "")
    if not match:
        return "no marker in the dispatch prompt; nothing saved"
    review_dir, persona, nonce = Path(match.group(1)), saved_persona(match.group(2)), match.group(3)
    expected_file = review_dir / f"{persona}.expect"
    expected = expected_file.read_text(encoding="utf-8").strip() if expected_file.is_file() else ""
    previous = saved_by(review_dir, persona)
    if expected and not hmac.compare_digest(expected, nonce):
        return f"{persona}: the marker's nonce does not match {expected_file.name}; nothing saved"
    if not expected and not (agent and previous == agent):
        return f"{persona}: no {expected_file.name} for this marker; nothing saved"
    if previous is not None and previous != agent:
        return f"{persona}: {persona}.out.md is another agent's reply; kept"
    reply = handback(found) or str(payload.get("last_assistant_message") or "")
    args = argparse.Namespace(review_dir=review_dir, persona=persona, harness="claude-code", agent_id=agent or None,
                              model=model_of(found), resume=previous is not None, degraded=False)
    saved = store_reply(args, reply.encode("utf-8"))
    expected_file.unlink(missing_ok=True)
    return f"saved {saved['saved']} ({saved['outcome']}{', resumed' if args.resume else ''})"


def recorded_usage(payload: dict, found: list[dict], prompt: str, match: re.Match | None, accepted: bool) -> str:
    """Record the run's token usage on its task (`task_usage`); the marker's review directory names the task only
    when `save_reply` accepted that marker. "" when no task is named."""
    persona = match.group(2).strip().lower().removeprefix("reviewer-") if match else ""
    review_dir = Path(match.group(1)) if match and accepted else None
    return record_usage(prompt, found, str(payload.get("agent_type") or "agent"), persona,
                        str(payload.get("agent_id") or ""), review_dir)


def capture(args: argparse.Namespace) -> int:
    """The `capture` subcommand: one `SubagentStop` payload on stdin; the reply line, then the usage line when the
    prompt names a task. Always exit 0."""
    lines = []
    try:
        payload = json.loads(sys.stdin.read() or "{}")
        payload = payload if isinstance(payload, dict) else {}
        path = payload.get("agent_transcript_path")
        found = entries(Path(path)) if isinstance(path, str) and Path(path).is_file() else None
    except (OSError, ValueError) as error:
        payload, found, lines = {}, None, [f"nothing saved: {error}"]
    if found is None:
        print(f"capture-reply: {lines[0] if lines else 'no transcript; nothing saved'}")
        return 0
    prompt = first_prompt(found)
    match = MARKER.search(prompt)
    try:
        lines.append(save_reply(payload, found, match))
    except (OSError, ValueError) as error:
        lines.append(f"nothing saved: {error}")
    try:
        lines.append(recorded_usage(payload, found, prompt, match, lines[-1].startswith("saved ")))
    except (OSError, ValueError) as error:
        lines.append(f"usage not recorded: {error}")
    for line in filter(None, lines):
        print(f"capture-reply: {line}")
    return 0
