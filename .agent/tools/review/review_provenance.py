#!/usr/bin/env python3
"""What `persist` learns from the provenance records `save-out` wrote.

Two questions, both answered from `<persona>.provenance.json` beside each reply:

1. Is the reply the one that was saved? The record's sha256 must equal the hash of `<persona>.out.md`
   as it is now. A mismatch is a hard error, because the point of the record is that an edit after
   the save is caught. A persona with no record is a review directory from before this existed: it
   passes, and the report says `provenance: absent (legacy)`. Tamper evidence covers new reviews only.
2. Did that many agents run? Personas are grouped by the agent that answered: the same non-null
   `agent_id` is one agent; a persona declared `degraded` is the orchestrator itself; a null id is
   its own agent, and a resumed reply (the same persona answering again) never shares. When there
   are fewer agents than lenses the review is degraded (`review_degraded.py`), not refused.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from review_degraded import banner
from review_report_sections import PROVENANCE_HEADING
from review_vocabulary import canonical_personas


@dataclass
class Trail:
    """The provenance facts a persisted report states about itself."""

    section: str = ""
    degraded: str = ""


def read_record(review_dir: Path, persona: str) -> dict | None:
    """The persona's provenance record, None when absent, ValueError when unreadable."""
    path = review_dir / f"{persona}.provenance.json"
    if not path.is_file():
        return None
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as error:
        raise ValueError(f"{path.name} is not valid JSON ({error})") from None
    if not isinstance(record, dict) or "sha256" not in record:
        raise ValueError(f"{path.name} carries no sha256")
    return record


def agent_key(persona: str, record: dict | None) -> tuple:
    """Which agent answered: shared ids and declared degraded runs collapse to one key."""
    if record is None or record.get("resumed"):
        return ("persona", persona)
    if record.get("agent_id"):
        return ("id", record["agent_id"])
    return ("degraded",) if record.get("degraded") else ("persona", persona)


def check(review_dir: Path, personas: list[str]) -> Trail:
    """Verify each saved reply's hash and say how many agents answered; ValueError on a mismatch."""
    names = canonical_personas(personas, split_commas=False)
    records = {name: read_record(review_dir, name) for name in names}
    for name, record in records.items():
        reply = review_dir / f"{name}.out.md"
        if record and hashlib.sha256(reply.read_bytes()).hexdigest() != record["sha256"]:
            raise ValueError(
                f"{reply.name} no longer matches its provenance record (sha256 mismatch): it was "
                "edited after save-out; save the persona's real reply again"
            )
    verified = [name for name, record in records.items() if record]
    legacy = [name for name in names if name not in verified]
    if not verified:
        line = "provenance: absent (legacy)"
    else:
        line = f"provenance: verified ({len(verified)} of {len(names)} replies hashed at save-out)"
        if legacy:
            line += f"; absent (legacy) for {', '.join(legacy)}"
    agents = len({agent_key(name, record) for name, record in records.items()})
    degraded = banner(agents, len(names)) if agents < len(names) else ""
    return Trail(section=f"{PROVENANCE_HEADING}\n- {line}\n", degraded=degraded)
