"""A subagent run's `agent_end` METRIC on its task (the subagent-stop hook), and a stop's raw `cursor_stop` counts.
The task is the prompt's `crew-task: <TASK_DIR>` line, else the task above an accepted review directory. From a
transcript, `tokens` is the last call's context, the counts summed per message id; an event with `stats` records
`tokens=unknown` with them. A stop event with `usage` keeps its raw counts and ids on the task its workspace resolves
to offline (`task_cost.cursor_session_usage` reads them). Both read the hook's normalised event.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import timedelta
from pathlib import Path

from crew.lib.clock import parse_stamp, utc_now, utc_stamp
from crew.task.task_progress import AGENT_END, CURSOR_STOP, append_metric

TASK_LINE = re.compile(r"^crew-task: (\S.*?)[ \t]*$", re.M)
USAGE = {"input": "input_tokens", "output": "output_tokens", "cache_read": "cache_read_input_tokens", "cache_write": "cache_creation_input_tokens"}
# A stopped subagent's `stats`, recorded as `<name>=<n>` on the `agent_end` line.
STATS = ("duration_ms", "tool_calls", "messages")
# A stop's `usage`, recorded as `<name>=<n>` on the `cursor_stop` line.
STOP_FIELDS = ("input", "output", "cache_read", "cache_write")
NO_TASK = "no task for this workspace; nothing recorded"  # the common case: usage.sh does not log it


def task_of(prompt: str, review_dir: Path | None) -> Path | None:
    """The task the prompt names, else the task directory above an accepted `<task>/review/<run>` review directory."""
    named = TASK_LINE.search(prompt)
    if named:
        return Path(named.group(1)).expanduser()
    return review_dir.parent.parent if review_dir is not None else None


def is_task(path: Path) -> bool:
    """True for a directory directly under `~/.agent/tasks` (resolved) that holds `SPEC.md`."""
    try:
        resolved = path.resolve()
        tasks = (Path.home() / ".agent" / "tasks").resolve()
    except OSError:
        return False
    return resolved.parent == tasks and (resolved / "SPEC.md").is_file()


def text_of(content: object) -> str:
    """The text of a message's content: a string, or its text blocks joined."""
    if isinstance(content, str):
        return content
    blocks = content if isinstance(content, list) else []
    texts = [block for block in blocks if isinstance(block, dict) and block.get("type") == "text"]
    return "\n".join(str(block.get("text") or "") for block in texts)


def count(value: object) -> int:
    return value if isinstance(value, int) and value > 0 else 0


def usage(found: list[dict]) -> dict[str, int] | None:
    """`tokens` (the last call's context) and the per-key sums over calls, each message id once; None without usage."""
    latest: dict[str, dict] = {}
    last: dict = {}
    for index, item in enumerate(found):
        message = item.get("message") if isinstance(item.get("message"), dict) else {}
        if item.get("type") == "assistant" and isinstance(message.get("usage"), dict):
            latest[str(message.get("id") or f"#{index}")] = last = message["usage"]
    if not latest:
        return None
    sums = {key: sum(count(seen.get(field)) for seen in latest.values()) for key, field in USAGE.items()}
    return {"tokens": sum(count(last.get(field)) for field in USAGE.values()), **sums}


def first_call(found: list[dict]) -> list[str]:
    """`started=<UTC stamp>` (the transcript's first timestamp: the dispatch) and the first call's `first_input`,
    `first_cache_read` and `first_cache_write`, as METRIC words; what the transcript lacks is left out. The first call
    is the one a prefix cache shared with an earlier agent can serve."""
    words = []
    stamps = [parse_stamp(str(item["timestamp"]).replace("Z", "+00:00")) for item in found if isinstance(item, dict) and item.get("timestamp")]
    if stamps and stamps[0] is not None:
        words.append(f"started={utc_stamp(stamps[0])}")
    for item in found:
        message = item.get("message") if isinstance(item.get("message"), dict) else {}
        if item.get("type") == "assistant" and isinstance(message.get("usage"), dict):
            words += [f"first_{key}={count(message['usage'].get(USAGE[key]))}" for key in ("input", "cache_read", "cache_write")]
            break
    return words


def word(value: str) -> str:
    """A METRIC value: one word, never empty."""
    return re.sub(r"\s+", "-", value.strip()) or "unknown"


def record_usage(
    prompt: str,
    found: list[dict],
    agent: str,
    persona: str,
    agent_id: str = "",
    review_dir: Path | None = None,
    harness: str = "claude-code",
    stats: dict | None = None,
) -> str:
    """Append the run's `agent_end` to its task; the one line saying what was recorded, or "" when no task is named.
    `stats` (the stop event's counts, when its harness sends them) records them with `tokens=unknown` instead of the
    transcript's."""
    task = task_of(prompt, review_dir)
    if task is None:
        return ""
    if not is_task(task):
        return f"{task} is not a task directory under ~/.agent/tasks; usage not recorded"
    head = [AGENT_END, f"agent={word(agent)}", f"persona={word(persona or agent)}", *([f"agent_id={word(agent_id)}"] if agent_id else [])]
    if stats is not None:
        counts = {key: count(stats.get(key)) for key in STATS}
        started = utc_stamp(utc_now() - timedelta(milliseconds=counts["duration_ms"]))
        append_metric(
            task, " ".join([*head, "tokens=unknown", *(f"{key}={value}" for key, value in counts.items()), f"started={started}", f"harness={word(harness)}"])
        )
        return f"recorded {AGENT_END} tokens=unknown tool_calls={counts['tool_calls']} on {task}"
    sums = usage(found)
    if sums is None:
        return "no usage in the transcript; nothing recorded"
    counted = [f"{key}={value}" for key, value in sums.items()]
    append_metric(task, " ".join([*head, *counted, *first_call(found), f"harness={word(harness)}"]))
    return f"recorded {AGENT_END} tokens={sums['tokens']} output={sums['output']} on {task}"


def resolve_task(root: str) -> Path | None:
    """The task for the checkout at `root` (git state only, no network, as `crew-task-context` resolves it), or None."""
    from crew.task.task_resolve import ResolverUnavailable, resolve_record

    here = os.getcwd()
    try:
        os.chdir(root)
        record = resolve_record()
    except (OSError, ResolverUnavailable):
        return None
    finally:
        os.chdir(here)
    found = record.get("task_dir")
    return Path(found) if found else None


def conversations_file() -> Path:
    """`<stamp> <session> <task dir>` lines: the task each session's stops are recorded on."""
    return Path.home() / ".agent" / "state" / "cursor-conversations.txt"


def bound_task(conversation: str) -> Path | None:
    """The task the conversation's first recorded stop resolved to, or None."""
    try:
        lines = conversations_file().read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    found = [line.split(" ", 2) for line in lines]
    return next((Path(parts[2]) for parts in found if len(parts) == 3 and parts[1] == conversation), None)


def bind_task(conversation: str, task: Path) -> None:
    path = conversations_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(f"{utc_stamp()} {conversation} {task}\n")


def record_stop(event: dict, resolve=resolve_task) -> str:
    """Append one stop event's raw `usage` counts to its session's task: the one the session's first recorded stop
    resolved to (kept in `~/.agent/state`), so a branch switch never splits a session across tasks; else the task its
    workspace resolves to now. The line saying what happened; nothing without the four counts, both ids, a
    workspace, or a task."""
    given = raw if isinstance(raw := event.get("usage"), dict) else {}
    counts = {key: given.get(key) for key in STOP_FIELDS}
    if not all(isinstance(value, int) and value >= 0 for value in counts.values()):
        return "no token counts in the event; nothing recorded"
    if not (event.get("session") and event.get("generation")):
        return "no session or generation id in the event; skipped"
    ids = {"conversation_id": word(str(event["session"])), "generation_id": word(str(event["generation"]))}
    root = str(event.get("workspace") or event.get("cwd") or "")
    task = bound_task(ids["conversation_id"])
    if task is None:
        if not root or not Path(root).is_dir():
            return "no workspace in the event; nothing recorded"
        task = resolve(root)
        if task is None or not is_task(task):
            return NO_TASK
        bind_task(ids["conversation_id"], task)
    if not is_task(task):
        return f"{task}, this conversation's task, is gone; nothing recorded"
    fields = [
        *(f"{name}={value}" for name, value in ids.items()),
        f"model={word(str(event.get('model') or ''))}",
        f"loop_count={count(event.get('loop'))}",
        *(f"{key}={value}" for key, value in counts.items()),
    ]
    append_metric(task, " ".join([CURSOR_STOP, *fields, f"harness={word(str(event.get('harness') or 'unknown'))}"]))
    return f"recorded {CURSOR_STOP} input={counts['input']} output={counts['output']} on {task}"


def main(argv: list[str]) -> int:
    """`crew-task.py usage stop`: one normalised stop event on stdin, recorded on its task. Always exit 0."""
    parser = argparse.ArgumentParser(prog="crew-task.py usage", description="Record a session's token usage.")
    commands = parser.add_subparsers(dest="action", required=True)
    commands.add_parser("stop", help="the stop hook rule: the event on stdin, raw counts on its task")
    parser.parse_args(argv)
    try:
        payload = json.loads(sys.stdin.read() or "{}")
        line = record_stop(payload if isinstance(payload, dict) else {})
    except (OSError, ValueError) as error:
        line = f"nothing recorded: {error}"
    print(f"usage: {line}")
    return 0
