#!/usr/bin/env python3
"""The finding vocabulary: the closed sets a finding's fields must come from.

Kept apart from the finding record so the sets can be read as a table. `kind` is separate from
`label` because they answer different questions — severity says how bad, kind says what sort of
defect — and `kind` is deliberately absent from a fingerprint, because identity is "this defect in
this file" and re-classifying must not split one finding into two.

`PERSONA_STATUSES` is the closed vocabulary for a leading `status:` line in `<persona>.out.md`.
Only these three failure words are authoritative; anything else (`dispatched`, `done`) falls through
to the content check, so a placeholder cannot claim a persona completed.
"""
from __future__ import annotations

import re

LABELS = {"blocking", "attention", "nit", "needs more info", "concern"}
KINDS = {"security", "correctness", "reliability", "documentation", "testing", "other"}
OUTCOMES = {"fixed", "rejected", "deferred", "skipped"}
PERSONAS = {"adversarial", "architecture", "code-quality", "product-flow", "prompt-quality", "explorer"}
LEGACY_PERSONAS = {"fresh-eyes"}  # removed persona; kept so old review dirs still normalize
CODE_MODES = {"self", "changes", "pr"}
PERSONA_STATUSES = {"failed", "skipped", "truncated"}
# Tiered output cap, counted separately so polish cannot evict severity: a nit has a 4-slot budget
# and non-nits a 12-slot one, so a flat cap cannot bind a real finding out to make room for polish.
MAX_FINDINGS = 12
MAX_NITS = 4
EMITTED = {"patch", "decide"}
DISPOSITIONS = {"patch", "decide", "defer", "dropped", "merged"}
EVIDENCE_LOCATION = re.compile(r"^[^:\s][^:]*:\d+(?:@[0-9a-f]{7,40})?$")
SELECT_RULES = {
    "prompt-quality": re.compile(r"(^|/)(agents|skills|evals)/|\.mdc$"),
    "architecture": re.compile(r"router|orchestrator|install|dispatch|tools\.json|(^|/)\.claude/"),
}


def mode_arg(value: str) -> str:
    """Normalize a mode before the choices check, so `--mode PR` is accepted.

    The protocol names the mode `PR` while the CLI enumerates lowercase values, which made a
    correct review fail on an argparse error before any persona was dispatched. Accept the
    documented casing and the `auto`/`auto-loop` modifiers instead of failing the run.
    """
    normalized = value.strip().lower()
    for modifier in (" auto-loop", " auto", "-auto-loop", "-auto"):
        normalized = normalized.replace(modifier, "")
    return normalized


def normalized_title(title: str) -> str:
    return re.sub(r"\s+", " ", title.strip().lower())


def canonical_personas(value: object, *, split_commas: bool = True) -> list[str]:
    """The persona names a caller named, normalized and validated against the vocabulary."""
    if not split_commas and isinstance(value, str) and "," in value:
        raise ValueError("comma-separated personas are invalid; pass each persona as a separate argument")
    raw = value if isinstance(value, list) else str(value or "").split(",")
    result = []
    for item in raw:
        name = re.sub(r"\s+", "-", str(item).strip().lower()).removeprefix("reviewer-")
        if not split_commas and "," in str(item):
            raise ValueError("comma-separated personas are invalid; pass each persona as a separate argument")
        if not name:
            continue
        if name not in PERSONAS | LEGACY_PERSONAS:
            raise ValueError(f"unknown persona: {item!r} (expected one of {sorted(PERSONAS)})")
        if name not in result:
            result.append(name)
    return result
