"""`ToolError`: how a core function refuses or fails, with an enumerated `code`, the step, and the next move.

The agent tool (`crew-tool.py`) turns it into the envelope's `error`; an owner script prints its `message`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Code = Literal[
    "usage",  # a bad invocation
    "not_a_task",  # no task directory, SPEC.md or .task-id there
    "not_a_repo",  # not inside a git checkout
    "unresolved",  # no task, repository or path could be resolved
    "config",  # ~/.agent/config.json is unreadable or wrong
    "refused",  # a gate or guard rule said no; the message names the rule
    "worker_tree",  # another task's live worker holds the tree
    "nothing_to_review",  # an empty diff
    "git",  # a git command failed
    "gh",  # a gh command failed
    "memory",  # the memory store is unavailable or refused the unit
    "review",  # a review artifact is missing or malformed
    "unavailable",  # the fact asked for does not exist here
    "failed",  # a setup step could not finish; the step names which
]


@dataclass
class ToolError(Exception):
    """A refusal or failure: what went wrong (the full message), at which step, and what to do next."""

    code: Code
    message: str
    step: str = ""
    hint: str = ""
    exit: int = 1

    def __str__(self) -> str:
        return self.message


class StepFailed(ToolError):
    """One setup step could not finish: exit 1 when the user decides the next move (`refused`), else 2 (`failed`)."""

    def __init__(self, step: str, message: str, exit: int = 2) -> None:
        super().__init__("refused" if exit == 1 else "failed", f"{step}: {message}", step, exit=exit)
