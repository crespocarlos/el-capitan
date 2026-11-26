#!/usr/bin/env python3
"""`crew-review-findings.py save-out`: store a persona's raw reply and record where it came from.

Every reviewer reply used to be paid for twice: the reply itself, then a verbatim rewrite to
`<persona>.out.md`. `save-out` takes the reply on stdin and stores its raw bytes, so the rewrite is
a shell pipe and not model output. Beside it goes `<persona>.provenance.json`:

    {"schema_version": 1, "persona", "harness", "agent_id": <str|null>, "model": <str|null>,
     "time": <UTC>, "sha256", "bytes", "resumed": <bool>, "degraded": <bool>}

`persist` verifies the hash (`review_provenance.py`), so an edit after the save is caught, and reads
the ids to tell a review run by distinct agents from one agent playing several lenses. An id the
harness does not report is null, never guessed. `--resume` marks a persona's re-emitted reply (one
resume is allowed by the dispatch rules); `--degraded` is how an orchestrator that plays the lens
itself declares it, because such a run has no second id to compare.

The digest rejection is not here: a digest is saved like any reply and refused by `persist`, whose
check has not changed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from lib.files import atomic_write
from review_classify import persona_outcome
from review_vocabulary import canonical_personas

SCHEMA_VERSION = 1


def provenance_path(review_dir: Path, persona: str) -> Path:
    return review_dir / f"{persona}.provenance.json"


def add_save_out_parser(commands) -> None:
    parser = commands.add_parser(
        "save-out", help="store a persona reply from stdin as <persona>.out.md with its provenance")
    parser.add_argument("--review-dir", required=True, type=Path)
    parser.add_argument("--persona", required=True)
    parser.add_argument("--harness", required=True, help="cursor, claude-code, codex, ...")
    parser.add_argument("--agent-id", default=None, help="the dispatched agent's id, when known")
    parser.add_argument("--model", default=None, help="the model that answered, when known")
    parser.add_argument("--resume", action="store_true", help="this reply is a resume of the persona")
    parser.add_argument("--degraded", action="store_true",
                        help="the orchestrator played this lens itself (no separate agent)")


def save_out(args: argparse.Namespace) -> int:
    """Write the raw reply and its provenance record; warn, without refusing, on a digest."""
    (persona,) = canonical_personas([args.persona], split_commas=False)
    if not args.review_dir.is_dir():
        raise ValueError(f"no such review directory: {args.review_dir}")
    raw = sys.stdin.buffer.read()
    if not raw.strip():
        raise ValueError("stdin is empty: there is no reply to save")
    target = args.review_dir / f"{persona}.out.md"
    target.write_bytes(raw)
    record = {
        "schema_version": SCHEMA_VERSION, "persona": persona, "harness": args.harness,
        "agent_id": args.agent_id or None, "model": args.model or None,
        "time": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw),
        "resumed": bool(args.resume), "degraded": bool(args.degraded),
    }
    atomic_write(provenance_path(args.review_dir, persona), json.dumps(record, indent=2) + "\n")
    outcome = persona_outcome(target)
    if outcome in ("summarized", "unknown"):
        print(f"warning: {target.name} reads as `{outcome}`; persist will refuse it unless it is "
              "the persona's real reply", file=sys.stderr)
    print(json.dumps({"saved": str(target), "sha256": record["sha256"], "outcome": outcome}))
    return 0
