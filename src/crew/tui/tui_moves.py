"""The status moves the TUI offers: each `crew-task.py` call a task's state allows, and why another is unavailable.
Pure: the app's dialog shows them and its runner runs the one confirmed. The CLI still checks every gate."""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

from crew.core.task.task_gates import CLOSABLE
from crew.core.task.task_report import number_cell
from crew.core.task.task_state import TaskState, head, recorded_state

CREW_TASK = (sys.executable, "-m", "crew.scripts.crew_task")  # what ~/.agent/bin/crew-task.py runs

# The default `--pr-url` note of the close move (`mark-done --force`): shipped work for IMPLEMENTING, else stale.
SHIPPED_NOTE, STALE_NOTE = "none (committed to main)", "closed: stale"


@dataclass(frozen=True)
class Move:
    """One `crew-task.py` call the status dialog offers: `key` picks it, the task goes from `source` to `target`; a call
    that takes free text has its prompt (`ask`) and default, the text last. With `why` it is unavailable, and says why."""

    key: str
    label: str
    source: str
    target: str
    args: tuple[str, ...] = ()
    ask: str = ""
    default: str = ""
    why: str = ""

    def title(self) -> str:
        return f"{self.source} → {self.target} [{self.key}] {self.label}" + (f" (unavailable: {self.why})" if self.why else "")

    def argv(self, text: str = "") -> list[str]:
        return [*CREW_TASK, *self.args, *([text] if self.ask else [])]


def moves(state: str, task: Path, prs: list[str], branch: str = "") -> list[Move]:
    """The calls `crew-task.py` accepts from `state`: its gate (start on the spec's `## Branch:`, mark done with the newest
    PR), then `blocked` with a reason for any task not DONE, and close as done (`mark-done --force` with a note) for a
    state the CLI closes (`CLOSABLE`), except an IMPLEMENTING task with a PR. A gate the task cannot pass yet, and close
    for a state the CLI does not close, come back unavailable with the reason. The CLI still checks every gate."""
    t = str(task)
    found = []
    if state == "DRAFTING":
        found.append(Move("a", "Approve", state, "APPROVED", ("mark-approved", t)))
    elif state == "APPROVED":
        why = "" if branch else "SPEC.md names no `## Branch:`; run crew-task.py mark-implementing <TASK_DIR> from its checkout"
        found.append(Move("i", f"Start on {branch}" if branch else "Start", state, "IMPLEMENTING", ("mark-implementing", t, "--branch", branch), why=why))
    elif state == "IMPLEMENTING":
        pr = prs[-1] if prs else ""
        found.append(
            Move(
                "d",
                f"Mark done with PR {number_cell(pr)}" if pr else "Mark done with its PR",
                state,
                "DONE",
                ("mark-done", t, "--pr-url", pr),
                why="" if pr else "no PR recorded",
            )
        )
    if state == "DONE":
        return found
    found.append(Move("b", "Block, with a reason", state, "BLOCKED", ("blocked", t), ask="reason"))
    if not (state == "IMPLEMENTING" and prs):
        note = SHIPPED_NOTE if state == "IMPLEMENTING" else STALE_NOTE
        why = "" if state in CLOSABLE else f"crew-task.py does not close {state or 'an unset status'}"
        found.append(Move("c", "Close as done (--force), with a note", state, "DONE", ("mark-done", t, "--force", "--pr-url"), "note", note, why))
    return found


def restore_moves(r: TaskState) -> list[Move]:
    """The only calls a TAMPERED task takes (every gate refuses it): write the recorded status back, or keep the
    spec's with a note."""
    t = str(r.task)
    return [
        Move("r", "Restore the recorded status", "TAMPERED", recorded_state(r), ("restore-status", t)),
        Move("k", "Keep the spec's status (--accept), with a note", "TAMPERED", head(r) or "?", ("restore-status", t, "--accept"), ask="note"),
    ]
