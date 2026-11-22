#!/usr/bin/env python3
"""The finding record: one review finding, its fingerprint, and the gates a single finding faces.

Built once by `read_findings` at the JSON boundary, then passed inward, so no gate re-derives the
shape from string keys. `to_json` writes back exactly the keys that arrived — an unknown key stays
in `extra` rather than being silently dropped on the way through `normalize`.

`check_findings` holds the per-finding rules and `check_strict` the ones that need a reviewed file
set. They are separate because `persist` used to reach every per-finding rule only when `--files`
carried a path, and a spec or idea review has no path list to pass: the result was a `verified:
true` finding with no validation sentence persisting successfully in exactly the modes that pass no
files, while both `TOOLS.md` and the consolidation protocol said the sentence was required.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path

from review_vocabulary import (
    DISPOSITIONS,
    EMITTED,
    KINDS,
    LABELS,
    canonical_personas,
    normalized_title,
)

# Absent is not the same as empty: `evidence` is optional, and a record must not grow a key the
# persona never wrote, because `normalize` republishes the finding for later steps to parse.
ABSENT = object()


@dataclass
class Finding:
    """One review finding: the fields the gates read, plus everything else the persona wrote."""

    title: str
    label: str
    file: object = ABSENT
    line: object = ABSENT
    kind: object = ABSENT
    disposition: object = ABSENT
    persona: object = ABSENT
    hunks: object = ABSENT
    verified: object = ABSENT
    evidence: object = ABSENT
    validation: object = ABSENT
    reason: object = ABSENT
    memory_ids: object = ABSENT
    fingerprint: str = ""
    extra: dict = field(default_factory=dict)

    def is_emitted(self) -> bool:
        """True for a finding the review stands behind, as opposed to one it deferred."""
        return self.disposition in EMITTED

    def text(self, name: str) -> str:
        """An optional field rendered as text: empty when absent, else `str(value)` as before."""
        value = getattr(self, name)
        return "" if value is ABSENT else str(value)

    def to_json(self) -> dict:
        """The finding as JSON, with a key present only when the persona supplied it."""
        out: dict = {"title": self.title, "label": self.label}
        for key, value in (("file", self.file), ("line", self.line), ("kind", self.kind),
                           ("disposition", self.disposition), ("persona", self.persona),
                           ("hunks", self.hunks), ("verified", self.verified),
                           ("evidence", self.evidence), ("validation", self.validation),
                           ("reason", self.reason), ("memory_ids", self.memory_ids)):
            if value is not ABSENT:
                out[key] = value
        out.update(self.extra)
        out["fingerprint"] = self.fingerprint
        return out

    def merge(self, other: "Finding") -> None:
        """Fold a duplicate into this finding: union the personas each named and the hunks cited.

        A finding that only one of the two anchored still inherits the other's anchors, because the
        merged record is what later steps read; leaving the first one's empty list would lose the
        hunk the duplicate cited.
        """
        if isinstance(other.persona, list):
            for persona in other.persona:
                if not isinstance(self.persona, list):
                    self.persona = []
                if persona not in self.persona:
                    self.persona.append(persona)
        ours = [] if self.hunks is ABSENT else self.hunks
        theirs = [] if other.hunks is ABSENT else other.hunks
        if isinstance(ours, list) and isinstance(theirs, list):
            self.hunks = list(dict.fromkeys(ours + theirs))


def fingerprint(finding: Finding) -> str:
    """This defect in this file: a re-classification keeps the same identity."""
    material = "|".join(
        [
            str(finding.file if finding.file is not ABSENT else "").strip(),
            str(finding.label).strip().lower(),
            normalized_title(str(finding.title)),
        ]
    )
    return hashlib.sha1(material.encode()).hexdigest()


def to_finding(finding: dict, index: int) -> Finding:
    """Build the record from one JSON object, refusing a value the vocabulary does not allow."""
    if not isinstance(finding, dict) or not isinstance(finding.get("title"), str):
        raise ValueError(f"finding {index} requires a string title")
    label = str(finding.get("label", "")).lower()
    if label not in LABELS:
        raise ValueError(f"finding {index} has invalid label: {label!r}")
    disposition = finding.get("disposition")
    if disposition is not None and disposition not in DISPOSITIONS:
        raise ValueError(f"finding {index} has invalid disposition: {disposition!r}")
    # A value outside the vocabulary is a typo and is rejected here, so the set cannot drift one
    # spelling at a time. Absence is a different failure and is refused by `require_kind` at persist,
    # because `normalize` must still be able to read the reviews recorded before `kind` existed.
    kind = ABSENT
    if "kind" in finding:
        kind = str(finding["kind"]).strip().lower()
        if kind not in KINDS:
            raise ValueError(
                f"finding {index} has invalid kind: {finding['kind']!r} "
                f"(expected one of {', '.join(sorted(KINDS))})"
            )
    persona = ABSENT
    if "persona" in finding or "personas" in finding:
        persona = canonical_personas(finding.get("persona", finding.get("personas")))
        if not persona:
            # An absent key is legacy data the tool must still re-read; an empty list is a caller
            # that meant to attribute the finding and did not, so it is refused here rather than
            # landing in an unattributed bucket that no precision number can ever explain.
            raise ValueError(
                f"finding {index} names no persona; attribute it to the one that raised it "
                "(or omit the key entirely for a record written before personas were recorded)"
            )
    known = {"title", "label", "file", "line", "kind", "disposition", "persona", "personas",
             "hunks", "verified", "evidence", "validation", "reason", "memory_ids", "fingerprint"}
    record = Finding(
        title=finding["title"], label=label, kind=kind, persona=persona,
        file=finding.get("file", ABSENT), line=finding.get("line", ABSENT),
        disposition=finding.get("disposition", ABSENT), hunks=finding.get("hunks", ABSENT),
        verified=finding.get("verified", ABSENT), evidence=finding.get("evidence", ABSENT),
        validation=finding.get("validation", ABSENT), reason=finding.get("reason", ABSENT),
        memory_ids=finding.get("memory_ids", ABSENT),
        extra={key: value for key, value in finding.items() if key not in known},
    )
    record.fingerprint = fingerprint(record)
    return record


def require_kind(finding: Finding) -> None:
    """Reject a finding with no `kind`, naming every value the vocabulary allows.

    Required rather than optional, and enforced at persist: measured over 84 reviews, 713 of 719
    findings carried no `kind`, so the one defect axis independent of severity was never populated.
    A recorded review is re-read through `--lenient`, which is where legacy data stays readable.
    """
    if finding.kind is ABSENT:
        raise ValueError(
            f"finding {finding.title!r} has no kind; state what sort of defect it is, one of: "
            f"{', '.join(sorted(KINDS))}"
        )


def read_json_object(path: Path, key: str) -> dict:
    """A JSON object that must carry a `key` list, or ValueError naming the file."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except OSError as error:
        raise ValueError(f"cannot read {path}: {error}") from error
    except json.JSONDecodeError as error:
        raise ValueError(f"{path} is not valid JSON: {error}") from error
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must be a JSON object")
    value = payload.get(key)
    if not isinstance(value, list):
        raise ValueError(f"{path} has no {key!r} list")
    return payload


