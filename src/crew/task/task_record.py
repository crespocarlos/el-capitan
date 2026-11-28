"""The status a task's PROGRESS.md records: the gate stamp, a transition's target, what crew-progress refuses.

`crew-task.py`'s gates end each status transition they write with `GATE_STAMP`, and `crew-progress.py` refuses a
text, or a `CREW_WORKFLOW`/`CREW_MEMBER` value, that carries it or an arrow to a status token. `task_state` compares
the spec's `## Status` with `recorded_status` (TAMPERED on a mismatch). This is a record, not a lock: see
docs/hooks.md "Status integrity" for what it does and does not stop.
"""

from __future__ import annotations

import json
import re

from crew.task.task_progress import Entry
from crew.task.task_status import ACCEPTED
from crew.task.task_status import head as state_head

GATE_STAMP = "[gate]"  # ends every status transition crew-task writes; crew-progress.py refuses it
TARGET = re.compile(r"(?:→|->)\s*(\S+)")  # the state a TRANSITION body moves to (its first arrow)
ARROW = re.compile(r"→|->")


def status_target(text: str) -> str:
    """The status token a transition text moves to (its first arrow), or "" for a pipeline step or no arrow."""
    found = TARGET.search(text)
    token = state_head(found.group(1)) if found else ""
    return token if token in ACCEPTED else ""


def forged_transition(text: str, env: bool = False) -> str:
    """Why `crew-progress.py` refuses a transition text (or, with `env`, a `CREW_WORKFLOW`/`CREW_MEMBER` value, which
    may carry no arrow at all): the gate stamp, or a move to a status token; "" when it is a progress note."""
    if GATE_STAMP in text:
        return f"the {GATE_STAMP} stamp is written only by crew-task.py"
    if env and ARROW.search(text):
        return "an environment value carries an arrow"
    target = status_target(text)
    return (f"{target} is a status, and only crew-task.py's gates record a status (mark-approved, mark-implementing, mark-done)") if target else ""


def transition_text(body: str) -> str:
    """A TRANSITION body without the JSON suffix `CREW_WORKFLOW`/`CREW_MEMBER` add (`append_transition`)."""
    stripped = body.rstrip()
    start = stripped.rfind(" {")
    if not stripped.endswith("}") or start < 0:
        return stripped
    try:
        json.loads(stripped[start + 1 :])
    except ValueError:
        return stripped
    return stripped[:start].rstrip()


def stamped(entry: Entry) -> bool:
    """A TRANSITION whose text, before any JSON suffix, ends with the gate stamp: a crew-task status move."""
    return entry.kind == "TRANSITION" and transition_text(entry.body).endswith(GATE_STAMP)


def recorded_status(entries: list[Entry]) -> tuple[str, bool]:
    """`(status, legacy)`: the status crew-task last recorded, "" for none (`task_state.recorded_state`: DRAFTING).

    Only a gate-stamped TRANSITION counts (`stamped`), its target read from the text before any JSON suffix. A task
    with no stamped line is legacy, from before the stamp: its status is the newest transition line, typed or untyped
    (as `pr_urls` reads them), that moves to a status token. `task_state.load` makes a task with a `.task-id` and no
    PROGRESS entries strict instead, so deleting the record never makes a task lenient.
    """
    gated = [entry for entry in entries if stamped(entry)]
    if gated:
        return status_target(transition_text(gated[-1].body)), False
    for entry in reversed(entries):
        target = status_target(transition_text(entry.body)) if entry.kind in ("TRANSITION", "") else ""
        if target:
            return target, True
    return "", True
