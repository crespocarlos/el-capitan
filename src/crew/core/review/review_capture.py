"""Reply capture: `expect` writes an agent's nonce at dispatch; `capture` (the subagent-stop hook, on the normalised
event) saves its reply. The marker `crew-review-out: <dir> <name> <nonce>` (the event's `prompt`, else the
transcript's first user line) counts only when `<name>.expect` holds its nonce. The latest reply is `<name>.out.md`
(the earlier `.prev.md`); one that answers nothing leaves `.unanswered` and, once per nonce, a `capture-continue:`
line. The same stop twice changes nothing. Usage goes to the task, a builder's reply to REPORT.md. Exit 0.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import hmac
import json
import re
import sys
import time
from pathlib import Path

from crew.core.review.review_render import provenance_path, save_out, saved_persona, store_reply
from crew.core.review.review_transcript import diagnostic, resolve
from crew.core.review.review_vocabulary import PROBE, has_review_content
from crew.core.task.task_builder_report import capture_builder
from crew.core.task.task_usage import record_usage, text_of
from crew.lib.files import atomic_write
from crew.lib.reply_marker import MARKER, write_expect

HANDBACK = "SubagentHandback"
FAILED = re.compile(r"\A\s*(?:#+[^\n]*\n+\s*)?status:\s*(failed|truncated)\b", re.I)
# What makes a crew-specwriter subagent's reply an answer: a critic's verdict line, an explorer's sections.
VERDICT = re.compile(r"^\W*Verdict:", re.M | re.I)
ANSWERED = {"specwriter-scope": VERDICT, "specwriter-adversarial": VERDICT, "specwriter-explorer": re.compile(r"^#{2,3} \S", re.M)}
TASK_LINE = re.compile(r"^crew-task: \S.*$", re.M)
# The one resume text, shared with dispatch.md's no-reply rule: the hook's continue sends it once per nonce.
DELIVER_NOW = "deliver now: write your findings (a critic: your critique) from what you have read, and name what you did not check"
ALREADY = "already saved"
SEEN_KEEP = 500
LOCK_WAIT = 10.0  # seconds: a stuck hook never stalls later stops longer than this; past it they run unlocked


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


def reply_and_origin(found: list[dict], payload: dict) -> tuple[str, str]:
    """The run's reply and where it came from: the `SubagentHandback` message (the explicit reply, ahead of any text
    after it), else the event's `reply` (the harness's final response; the transcript may lag), else the transcript's
    last assistant text, else a completed run's `summary`, recorded as `reply_from` so a summary is never taken for
    the reply."""
    message = payload.get("reply")
    text = handback(found) or (str(message) if isinstance(message, str) and message.strip() else "") or last_text(found)
    if text:
        return text, "transcript"
    summary = payload.get("summary")
    if isinstance(summary, str) and summary.strip():
        return summary, "summary"
    return "", "transcript"


def reply_of(found: list[dict], payload: dict) -> str:
    return reply_and_origin(found, payload)[0]


def model_of(found: list[dict], payload: dict) -> str | None:
    """The model of the last assistant message, else the event's `model`, or None."""
    found_model = next((str(item["message"]["model"]) for item in reversed(found) if item.get("type") == "assistant" and item["message"].get("model")), None)
    return found_model or (str(payload["model"]) if payload.get("model") else None)


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


def save_reply(payload: dict, found: list[dict], match: re.Match | None, source: str = "hook") -> str:
    """Save the reply the marker names; the one line saying what happened.

    The nonce is the check, never the agent id: `.expect` stays after a save and the record keeps the nonce, so any
    later, different reply to the same marker (a resume, whatever its id) becomes `<name>.out.md` and the earlier one
    `<name>.prev.md`: the latest reply to a marker is the reply. The same bytes again change nothing (`already
    saved`). A reply that does not answer leaves `<name>.unanswered` beside it, so the dispatch stays pending."""
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
    text, origin = reply_and_origin(found, payload)
    reply, out, pending = text.encode("utf-8"), review_dir / f"{persona}.out.md", review_dir / f"{persona}.unanswered"
    if previous is not None and out.read_bytes() == reply:
        return f"{persona}: {ALREADY} ({out.name} holds this reply); nothing changed"
    if origin == "summary" or not answered(text, persona):  # a harness summary is a digest: the reply is still owed
        atomic_write(pending, "the reply is empty, a failure, a summary, or answers nothing; the dispatch is pending\n")
    else:
        pending.unlink(missing_ok=True)
    if not text.strip():
        return f"{persona}: the reply is empty; nothing saved, {pending.name} written"
    if previous is not None:
        keep_previous(review_dir, persona)
    args = argparse.Namespace(
        review_dir=review_dir,
        persona=persona,
        harness=payload["harness"],
        agent_id=payload["agent_id"] or None,
        model=model_of(found, payload),
        resume=previous is not None,
        degraded=False,
    )
    saved = store_reply(args, reply, nonce=nonce, source=source, reply_from=None if origin == "transcript" else origin)
    how = (", resumed; the earlier reply is " + f"{persona}.prev.md") if args.resume else ""
    flag = f"; unanswered: {pending.name} written" if pending.exists() else ""
    via = f"; from the payload's {origin}" if origin != "transcript" else ""
    return f"saved {saved['saved']} ({saved['outcome']}{how}){flag}{via}"


def recorded_usage(payload: dict, found: list[dict], prompt: str, match: re.Match | None, accepted: bool) -> str:
    """Record the run's usage on its task (`task_usage`): the event's `stats` when its harness sends them, else the
    transcript's tokens. The marker's review directory names the task only when `save_reply` accepted that marker.
    "" when no task is named."""
    persona = match.group(2).strip().lower().removeprefix("reviewer-") if match else ""
    review_dir = Path(match.group(1)) if match and accepted else None
    stats = payload.get("stats") if isinstance(payload.get("stats"), dict) else None
    return record_usage(prompt, found, payload["agent_type"] or "agent", persona, payload["agent_id"], review_dir, payload["harness"], stats)


def continue_text(payload: dict, found: list[dict], match: re.Match | None) -> str:
    """`DELIVER_NOW` when the reply just handled left `<name>.unanswered`, this nonce was never continued and the
    harness can resume the run now (`resumable`), recorded in `<name>.continued`; else ""."""
    if not match:
        return ""
    review_dir, persona, nonce = Path(match.group(1)), saved_persona(match.group(2)), match.group(3)
    marker = review_dir / f"{persona}.continued"
    if not (review_dir / f"{persona}.unanswered").exists():
        return ""
    if marker.is_file() and marker.read_text(encoding="utf-8").strip() == nonce:
        return ""
    if payload.get("resumable") is not True:
        return ""
    atomic_write(marker, nonce + "\n")
    return DELIVER_NOW


class Seen:
    """The stops already handled (`~/.agent/state/capture-seen.txt`), behind one lock, so two copies of one stop
    (a harness may fire one stop twice) run one after the other and the second changes nothing."""

    def __init__(self) -> None:
        self.path = Path.home() / ".agent" / "state" / "capture-seen.txt"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = (self.path.parent / "capture-reply.lock").open("a")
        self.busy = True
        deadline = time.monotonic() + LOCK_WAIT
        while self.busy and time.monotonic() < deadline:
            try:
                fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                self.busy = False
            except BlockingIOError:
                time.sleep(0.1)

    @staticmethod
    def key(payload: dict, needle: str, reply: str, found: list[dict]) -> str:
        """One stop: the agent, its dispatch, its reply, and how far its transcript and loop had run, so a resume
        that grew the transcript (same reply text or not) is a new stop."""
        parts = (payload["harness"], payload["agent_id"], needle, hashlib.sha256(reply.encode()).hexdigest(), str(len(found)), str(payload.get("loop") or 0))
        return hashlib.sha256("\0".join(parts).encode()).hexdigest()

    def keys(self) -> list[str]:
        return self.path.read_text(encoding="utf-8").split() if self.path.is_file() else []

    def add(self, key: str) -> None:
        atomic_write(self.path, "\n".join([*self.keys()[-SEEN_KEEP:], key]) + "\n")

    def close(self) -> None:
        self.lock.close()


def needle_of(text: str) -> str:
    """What identifies a dispatch in a transcript's first user line: its marker's nonce, else its task line."""
    match = MARKER.search(text)
    if match:
        return match.group(3)
    task = TASK_LINE.search(text)
    return task.group(0).strip() if task else ""


def located(payload: dict) -> tuple[Path | None, list[Path], str]:
    """The transcript, the candidates tried, and the dispatch prompt when the event's `prompt` names a marker or a task
    (else ""): the transcript must then carry the same nonce or task line."""
    task = payload["prompt"] if isinstance(payload.get("prompt"), str) else ""
    needle = needle_of(task)
    if needle:
        path, tried = resolve(payload, lambda line: needle in line, needle)
        return path, tried, task
    path, tried = resolve(payload, lambda line: "crew-review-out: " in line or "crew-task: " in line)
    return path, tried, ""


def process(payload: dict) -> tuple[list[str], str]:
    """The outcome lines and the continue text for one normalised event."""
    if payload.get("stopped"):
        why = diagnostic(payload, [])
        return [f"status {payload.get('status')}; nothing saved, the dispatch stays pending ({why})"], ""
    path, tried, task_prompt = located(payload)
    own = next(iter(payload.get("transcripts") or []), None)
    if path is None and isinstance(own, str) and own and Path(own).is_file() and Path(own).stat().st_size:
        if not entries(Path(own)):  # only to say so: a transcript that failed the marker check is never read
            return [f"malformed transcript {own}: no message line; skipped"], ""
    found = entries(path) if path else []
    if path and not found:
        return [f"malformed transcript {path}: no message line; skipped"], ""
    prompt = task_prompt or first_prompt(found)
    needle = needle_of(prompt)
    if not needle:
        readable = path or any(candidate.is_file() for candidate in tried)
        why = "no marker; nothing saved" if readable else "no transcript and no marker; nothing saved"
        lines = [why + ("" if path else f" ({diagnostic(payload, tried)})")]
        if payload["agent_type"].rsplit(":", 1)[-1] == "crew-builder":
            lines.append("no report saved: the dispatch prompt has no `crew-task: <TASK_DIR>` line")
        return lines, ""
    note = [f"no transcript; the marker is from the payload's task ({diagnostic(payload, tried)})"] if not path else []
    seen = Seen()
    if seen.busy:
        note.append(f"lock busy after {LOCK_WAIT:.0f} s; handled unlocked")
    try:
        key = seen.key(payload, needle, reply_of(found, payload), found)
        if key in seen.keys():
            return [f"{ALREADY} (agent {payload['agent_id'] or '-'}, the same reply); nothing changed"], ""
        lines, cont = handle(payload, found, prompt)
        if any(wrote(line) for line in lines):
            seen.add(key)  # a stop that wrote nothing stays unrecorded, so a repeat of it retries
        return note + lines, cont
    finally:
        seen.close()


def wrote(line: str) -> bool:
    """Whether an outcome line says state was written: a save, an already-saved reply, a pending mark, a usage line."""
    return line.startswith(("saved ", "recorded ")) or ALREADY in line or ".unanswered" in line


def handle(payload: dict, found: list[dict], prompt: str) -> tuple[list[str], str]:
    """Save the reply, then record the usage and the builder's report, unless the reply was already saved."""
    match = MARKER.search(prompt)
    try:
        lines = [save_reply(payload, found, match)]
    except (OSError, ValueError) as error:
        lines = [f"nothing saved: {error}"]
    if ALREADY in lines[0]:
        return lines, ""
    accepted = lines[0].startswith("saved ")
    cont = continue_text(payload, found, match) if accepted or "the reply is empty" in lines[0] else ""
    try:
        lines.append(recorded_usage(payload, found, prompt, match, accepted))
    except (OSError, ValueError) as error:
        lines.append(f"usage not recorded: {error}")
    try:
        lines.append(capture_builder(payload, prompt, reply_of(found, payload), model_of(found, payload), payload["harness"]))
    except (OSError, ValueError) as error:
        lines.append(f"no report saved: {error}")
    return lines, cont


def capture(args: argparse.Namespace) -> int:
    """The `capture` subcommand: one normalised subagent-stop event on stdin; `capture-reply:` outcome lines, and one
    `capture-continue:` line when the hook should ask the agent to deliver. Always exit 0."""
    try:
        event = json.loads(sys.stdin.read() or "{}")
        lines, cont = process({"harness": "unknown", "agent_id": "", "agent_type": "", **(event if isinstance(event, dict) else {})})
    except (OSError, ValueError) as error:
        lines, cont = [f"nothing saved: {error}"], ""
    for line in filter(None, lines):
        print(f"capture-reply: {line}")
    if cont:
        print(f"capture-continue: {cont}")
    return 0


def save_out_command(args: argparse.Namespace) -> int:
    """`save-out`: the reply on stdin (`source: manual`), or `--from-transcript <file>`: the reply extracted as the
    hook extracts it, saved only when the file's marker names this directory and persona and `.expect` holds its
    nonce (`source: transcript`)."""
    if not args.from_transcript:
        return save_out(args)
    found = entries(args.from_transcript)
    match = MARKER.search(first_prompt(found))
    if not match:
        raise ValueError(f"{args.from_transcript}: the first user message carries no crew-review-out marker")
    if Path(match.group(1)).resolve() != args.review_dir.resolve() or saved_persona(match.group(2)) != saved_persona(args.persona):
        raise ValueError(f"{args.from_transcript}: its marker names {match.group(1)} {match.group(2)}, not {args.review_dir} {args.persona}")
    payload = {"harness": args.harness, "agent_id": args.agent_id or "", "model": args.model}
    line = save_reply(payload, found, match, source="transcript")
    print(f"save-out: {line}")
    return 0 if line.startswith("saved ") or ALREADY in line else 1
