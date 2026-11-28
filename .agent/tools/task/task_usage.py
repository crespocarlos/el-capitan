"""A subagent run's `agent_end` METRIC on its task (the subagent-stop hook), and a Cursor `stop`'s raw `cursor_stop`.

The task is the prompt's `crew-task: <TASK_DIR>` line, else the task above an accepted review directory, under
`~/.agent/tasks` with `SPEC.md`. Claude Code: `tokens` is the last call's context, the counts summed per message id.
Cursor `subagentStop`: `tokens=unknown` with its counts. A `stop` keeps its raw counts and ids on the task its workspace
resolves to offline (`task_cost.cursor_session_usage` reads them); with no task, nothing is recorded.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

from task_progress import AGENT_END, CURSOR_STOP, append_metric

from lib.clock import utc_stamp

TASK_LINE = re.compile(r"^crew-task: (\S.*?)[ \t]*$", re.M)
USAGE = {"input": "input_tokens", "output": "output_tokens", "cache_read": "cache_read_input_tokens",
         "cache_write": "cache_creation_input_tokens"}
# Cursor `subagentStop` counts, recorded as `<name>=<n>` on the `agent_end` line.
CURSOR_STATS = {"duration_ms": "duration_ms", "tool_calls": "tool_call_count", "messages": "message_count"}
# Cursor `stop` counts, recorded as `<name>=<n>` on the `cursor_stop` line.
STOP_FIELDS = {"input": "input_tokens", "output": "output_tokens", "cache_read": "cache_read_tokens",
               "cache_write": "cache_write_tokens"}
NO_TASK = "no task for this workspace; nothing recorded"  # the common case: cursor-usage.sh does not log it


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


def word(value: str) -> str:
    """A METRIC value: one word, never empty."""
    return re.sub(r"\s+", "-", value.strip()) or "unknown"


def record_usage(prompt: str, found: list[dict], agent: str, persona: str, agent_id: str = "",
                 review_dir: Path | None = None, harness: str = "claude-code", stats: dict | None = None) -> str:
    """Append the run's `agent_end` to its task; the one line saying what was recorded, or "" when no task is named.
    `stats` (Cursor's `subagentStop` payload) records its counts with `tokens=unknown` instead of the transcript's."""
    task = task_of(prompt, review_dir)
    if task is None:
        return ""
    if not is_task(task):
        return f"{task} is not a task directory under ~/.agent/tasks; usage not recorded"
    head = [AGENT_END, f"agent={word(agent)}", f"persona={word(persona or agent)}",
            *([f"agent_id={word(agent_id)}"] if agent_id else [])]
    if stats is not None:
        counts = {key: count(stats.get(field)) for key, field in CURSOR_STATS.items()}
        append_metric(task, " ".join([*head, "tokens=unknown", *(f"{key}={value}" for key, value in counts.items()),
                                      f"harness={word(harness)}"]))
        return f"recorded {AGENT_END} tokens=unknown tool_calls={counts['tool_calls']} on {task}"
    sums = usage(found)
    if sums is None:
        return "no usage in the transcript; nothing recorded"
    counted = [f"{key}={value}" for key, value in sums.items()]
    append_metric(task, " ".join([*head, *counted, f"harness={word(harness)}"]))
    return f"recorded {AGENT_END} tokens={sums['tokens']} output={sums['output']} on {task}"


def resolve_task(root: str) -> Path | None:
    """The task for the checkout at `root` (git state only, no network, as `crew-task-context` resolves it), or None."""
    from task_resolve import ResolverUnavailable, resolve_record

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
    """`<stamp> <conversation_id> <task dir>` lines: the task each Cursor conversation's stops are recorded on."""
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


def record_stop(payload: dict, resolve=resolve_task) -> str:
    """Append one Cursor `stop` payload's raw counts to its conversation's task: the one the conversation's first
    recorded stop resolved to (kept in `~/.agent/state`), so a branch switch never splits a conversation across
    tasks; else the task its workspace resolves to now. The line saying what happened; nothing without both ids, a
    workspace, the four counts, or a task."""
    ids = {name: word(str(payload.get(name) or "")) for name in ("conversation_id", "generation_id")}
    if not all(payload.get(name) for name in ids):
        return "no conversation_id or generation_id in the payload; skipped"
    roots = payload.get("workspace_roots")
    first = roots[0] if isinstance(roots, list) and roots else None
    root = first if isinstance(first, str) else str(payload.get("cwd") or "")
    counts = {key: payload.get(field) for key, field in STOP_FIELDS.items()}
    if not all(isinstance(value, int) and value >= 0 for value in counts.values()):
        return "no token counts in the payload; nothing recorded"
    task = bound_task(ids["conversation_id"])
    if task is None:
        if not root or not Path(root).is_dir():
            return "no workspace in the payload; nothing recorded"
        task = resolve(root)
        if task is None or not is_task(task):
            return NO_TASK
        bind_task(ids["conversation_id"], task)
    if not is_task(task):
        return f"{task}, this conversation's task, is gone; nothing recorded"
    model = word(str(payload.get("model_id") or payload.get("model") or ""))
    fields = [*(f"{name}={value}" for name, value in ids.items()), f"model={model}",
              f"loop_count={count(payload.get('loop_count'))}", *(f"{key}={value}" for key, value in counts.items())]
    append_metric(task, " ".join([CURSOR_STOP, *fields, "harness=cursor"]))
    return f"recorded {CURSOR_STOP} input={counts['input']} output={counts['output']} on {task}"


def main(argv: list[str]) -> int:
    """`crew-task.py usage stop`: one Cursor `stop` payload on stdin, recorded on its task. Always exit 0."""
    parser = argparse.ArgumentParser(prog="crew-task.py usage", description="Record a Cursor session's token usage.")
    commands = parser.add_subparsers(dest="action", required=True)
    commands.add_parser("stop", help="the Cursor `stop` hook: the payload on stdin, raw counts on its task")
    parser.parse_args(argv)
    try:
        payload = json.loads(sys.stdin.read() or "{}")
        line = record_stop(payload if isinstance(payload, dict) else {})
    except (OSError, ValueError) as error:
        line = f"nothing recorded: {error}"
    print(f"usage: {line}")
    return 0
