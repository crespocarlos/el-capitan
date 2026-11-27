"""Token usage of one subagent run, recorded on its task as an `agent_end` METRIC (the `SubagentStop` hook).

The task is the `crew-task: <TASK_DIR>` line of the dispatch prompt, else the task above a review directory whose
marker `save_reply` accepted; either must be a directory under `~/.agent/tasks` holding `SPEC.md`. `tokens` is the last
call's context (input + cache write + cache read + output); the four counts are summed over calls (each message id
once). `agent_id` lets a resumed agent's later stop replace its earlier one. Anything else records nothing.
"""
from __future__ import annotations

import re
from pathlib import Path

from task_progress import AGENT_END, append_metric

TASK_LINE = re.compile(r"^crew-task: (\S.*?)[ \t]*$", re.M)
USAGE = {"input": "input_tokens", "output": "output_tokens", "cache_read": "cache_read_input_tokens",
         "cache_write": "cache_creation_input_tokens"}


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
                 review_dir: Path | None = None) -> str:
    """Append the run's `agent_end` to its task; the one line saying what was recorded, or "" when no task is named."""
    task = task_of(prompt, review_dir)
    if task is None:
        return ""
    if not is_task(task):
        return f"{task} is not a task directory under ~/.agent/tasks; usage not recorded"
    counts = usage(found)
    if counts is None:
        return "no usage in the transcript; nothing recorded"
    payload = " ".join([AGENT_END, f"agent={word(agent)}", f"persona={word(persona or agent)}",
                        *([f"agent_id={word(agent_id)}"] if agent_id else []),
                        *(f"{key}={value}" for key, value in counts.items())])
    append_metric(task, payload)
    return f"recorded {AGENT_END} tokens={counts['tokens']} output={counts['output']} on {task}"
