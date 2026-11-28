"""Reply capture: `expect` writes an agent's nonce at dispatch; `capture` (the subagent-stop hook) saves its reply.

The marker `crew-review-out: <dir> <name> <nonce>` in the first user message counts only when `<name>.expect` holds
its nonce; the latest reply to a marker is `<name>.out.md` (the earlier one `<name>.prev.md`), and one that answers
nothing leaves `<name>.unanswered`. Usage goes to the task, a builder's reply to REPORT.md. Claude Code's
`SubagentStop` and Cursor's `subagentStop` (`subagent_*` fields, `role` lines) are read alike. Exit 0.
"""
from __future__ import annotations

import argparse
import hmac
import json
import re
import sys
from pathlib import Path

from review_render import provenance_path, saved_persona, store_reply
from review_vocabulary import PROBE, has_review_content
from task_builder_report import capture_builder
from task_usage import record_usage, text_of

from lib.files import atomic_write
from lib.reply_marker import MARKER, write_expect

HANDBACK = "SubagentHandback"
FAILED = re.compile(r"\A\s*(?:#+[^\n]*\n+\s*)?status:\s*(failed|truncated)\b", re.I)
# What makes a crew-specwriter subagent's reply an answer: a critic's verdict line, an explorer's sections.
ANSWERED = {"specwriter-scope": re.compile(r"^\W*Verdict:", re.M | re.I),
            "specwriter-adversarial": re.compile(r"^\W*Verdict:", re.M | re.I),
            "specwriter-explorer": re.compile(r"^#{2,3} \S", re.M)}


def add_capture_parsers(commands) -> None:
    expect = commands.add_parser("expect", help="write <persona>.expect and print the dispatch marker line")
    expect.add_argument("--review-dir", required=True, type=Path)
    expect.add_argument("--persona", required=True, help="a reviewer persona, probe, or a specwriter-* subagent")
    commands.add_parser("capture", help="the subagent-stop hook: save the reply its marker names (payload on stdin)")


def expect(args: argparse.Namespace) -> int:
    """Write a fresh nonce to `<persona>.expect` and print the marker line the dispatch prompt carries."""
    print(write_expect(args.review_dir, saved_persona(args.persona)))
    return 0


def entries(path: Path) -> list[dict]:
    """The transcript's JSON lines that are objects with a message, each with a `type`: Claude Code's own, or Cursor's
    `role`. A line that does not parse is skipped."""
    found = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            item = json.loads(line)
        except ValueError:
            continue
        if isinstance(item, dict) and isinstance(item.get("message"), dict):
            found.append(item if item.get("type") else {**item, "type": item.get("role")})
    return found


def normalized(payload: dict) -> dict:
    """The payload with `agent_id`, `agent_type` and `harness` in either harness's spelling."""
    cursor = "cursor_version" in payload or payload.get("hook_event_name") == "subagentStop"
    return {**payload, "agent_id": str(payload.get("agent_id") or payload.get("subagent_id") or ""),
            "agent_type": str(payload.get("agent_type") or payload.get("subagent_type") or ""),
            "harness": "cursor" if cursor else "claude-code"}


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


def last_text(found: list[dict]) -> str:
    """The text of the last assistant message that has any, or ""."""
    texts = (text_of(item["message"].get("content")) for item in reversed(found) if item.get("type") == "assistant")
    return next((text for text in texts if text.strip()), "")


def reply_of(found: list[dict], payload: dict) -> str:
    """The run's reply, one rule for every capture: the handback, else the transcript's last assistant text, else
    the payload's `last_assistant_message` (which a harness may fill with a summary)."""
    return handback(found) or last_text(found) or str(payload.get("last_assistant_message") or "")


def model_of(found: list[dict], payload: dict) -> str | None:
    """The model of the last assistant message, else the payload's `subagent_model` (Cursor), or None."""
    found_model = next((str(item["message"]["model"]) for item in reversed(found)
                        if item.get("type") == "assistant" and item["message"].get("model")), None)
    return found_model or (str(payload["subagent_model"]) if payload.get("subagent_model") else None)


def saved_nonce(review_dir: Path, persona: str) -> str | None:
    """The marker nonce recorded for an existing reply: None when there is no reply, "" when it was saved by hand
    (`save-out`) or before nonces were recorded."""
    if not (review_dir / f"{persona}.out.md").exists():
        return None
    try:
        record = json.loads(provenance_path(review_dir, persona).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    return str(record.get("nonce") or "") if isinstance(record, dict) else ""


def answered(text: str, persona: str) -> bool:
    """Whether a reply answers its dispatch: not empty, not a `status: failed|truncated` artifact, and for a persona a
    finding or the no-findings line (a pointer to an earlier turn is not); for a crew-specwriter subagent its verdict
    line or sections; for the probe, any text."""
    if not text.strip() or FAILED.match(text):
        return False
    rule = ANSWERED.get(persona)
    if rule:
        return bool(rule.search(text))
    return persona == PROBE or has_review_content(text)


def keep_previous(review_dir: Path, persona: str) -> None:
    """Move the earlier reply to the marker, and its record, to `<persona>.prev.md` and `.prev.provenance.json`."""
    (review_dir / f"{persona}.out.md").replace(review_dir / f"{persona}.prev.md")
    record = provenance_path(review_dir, persona)
    if record.exists():
        record.replace(provenance_path(review_dir, f"{persona}.prev"))


def save_reply(payload: dict, found: list[dict], match: re.Match | None) -> str:
    """Save the reply the marker names; the one line saying what happened.

    The nonce is the check, never the agent id: `.expect` stays after a save and the record keeps the nonce, so any
    later reply to the same marker (a resume, whatever its id) becomes `<name>.out.md` and the earlier one
    `<name>.prev.md`: the latest reply to a marker is the reply. A reply that does not answer leaves
    `<name>.unanswered` beside it, so the dispatch stays pending."""
    if not match:
        return "no marker in the dispatch prompt; nothing saved"
    review_dir, persona, nonce = Path(match.group(1)), saved_persona(match.group(2)), match.group(3)
    expected_file = review_dir / f"{persona}.expect"
    expected = expected_file.read_text(encoding="utf-8").strip() if expected_file.is_file() else ""
    if not expected:
        return f"{persona}: no {expected_file.name} for this marker; nothing saved"
    if not hmac.compare_digest(expected, nonce):
        return f"{persona}: the marker's nonce does not match {expected_file.name}; nothing saved"
    previous = saved_nonce(review_dir, persona)
    if previous and previous != nonce:
        return f"{persona}: {persona}.out.md answers another dispatch (a name collision); kept"
    text = reply_of(found, payload)
    reply, out, pending = text.encode("utf-8"), review_dir / f"{persona}.out.md", review_dir / f"{persona}.unanswered"
    if previous is not None and out.read_bytes() == reply:
        return f"{persona}: {out.name} already holds this reply; nothing saved"
    if not answered(text, persona):
        atomic_write(pending, "the reply is empty, a failure, or answers nothing; the dispatch is pending\n")
    else:
        pending.unlink(missing_ok=True)
    if not text.strip():
        return f"{persona}: the reply is empty; nothing saved, {pending.name} written"
    if previous is not None:
        keep_previous(review_dir, persona)
    args = argparse.Namespace(review_dir=review_dir, persona=persona, harness=payload["harness"],
                              agent_id=payload["agent_id"] or None, model=model_of(found, payload),
                              resume=previous is not None, degraded=False)
    saved = store_reply(args, reply, nonce=nonce)
    how = (", resumed; the earlier reply is " + f"{persona}.prev.md") if args.resume else ""
    flag = f"; unanswered: {pending.name} written" if pending.exists() else ""
    return f"saved {saved['saved']} ({saved['outcome']}{how}){flag}"


def recorded_usage(payload: dict, found: list[dict], prompt: str, match: re.Match | None, accepted: bool) -> str:
    """Record the run's usage on its task (`task_usage`): the transcript's tokens in Claude Code, the payload's counts
    in Cursor. The marker's review directory names the task only when `save_reply` accepted that marker. "" when no
    task is named."""
    persona = match.group(2).strip().lower().removeprefix("reviewer-") if match else ""
    review_dir = Path(match.group(1)) if match and accepted else None
    cursor = payload["harness"] == "cursor"
    return record_usage(prompt, found, payload["agent_type"] or "agent", persona, payload["agent_id"], review_dir,
                        payload["harness"], payload if cursor else None)


def capture(args: argparse.Namespace) -> int:
    """The `capture` subcommand: one subagent-stop payload on stdin; the reply line, then the usage line when the
    prompt names a task. A transcript with no message line is skipped, saying so. Always exit 0."""
    lines = []
    try:
        payload = json.loads(sys.stdin.read() or "{}")
        payload = normalized(payload if isinstance(payload, dict) else {})
        path = payload.get("agent_transcript_path")
        found = entries(Path(path)) if isinstance(path, str) and Path(path).is_file() else None
    except (OSError, ValueError) as error:
        payload, found, lines = {}, None, [f"nothing saved: {error}"]
    if found is None:
        print(f"capture-reply: {lines[0] if lines else 'no transcript; nothing saved'}")
        return 0
    if not found:
        print(f"capture-reply: malformed transcript {payload['agent_transcript_path']}: no message line; skipped")
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
    try:
        lines.append(capture_builder(payload, prompt, reply_of(found, payload), model_of(found, payload),
                                     payload["harness"]))
    except (OSError, ValueError) as error:
        lines.append(f"no report saved: {error}")
    for line in filter(None, lines):
        print(f"capture-reply: {line}")
    return 0
