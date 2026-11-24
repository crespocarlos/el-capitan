#!/usr/bin/env python3
"""The finding record: one review finding, its fingerprint, and the fields the gates read.

Built once by `read_findings` at the JSON boundary, then passed inward, so no gate re-derives the
shape from string keys. `to_json` writes back exactly the keys that arrived — an unknown key stays
in `extra` rather than being silently dropped on the way through `normalize`.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

from lib.files import read_json_object  # noqa: F401 — re-exported: one reader for every caller
from review_vocabulary import (
    CONFIDENCE,
    DISPOSITIONS,
    EMITTED,
    KINDS,
    LABELS,
    canonical_personas,
    confidence_value,
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
    confidence: object = ABSENT
    confidence_from: object = ABSENT
    disposition: object = ABSENT
    persona: object = ABSENT
    hunks: object = ABSENT
    verified: object = ABSENT
    evidence: object = ABSENT
    validation: object = ABSENT
    excerpt: object = ABSENT
    comment: object = ABSENT
    suggestion: object = ABSENT
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
                           ("confidence", self.confidence),
                           ("confidence_from", self.confidence_from),
                           ("disposition", self.disposition), ("persona", self.persona),
                           ("hunks", self.hunks), ("verified", self.verified),
                           ("evidence", self.evidence), ("validation", self.validation),
                           ("excerpt", self.excerpt), ("comment", self.comment),
                           ("suggestion", self.suggestion),
                           ("reason", self.reason), ("memory_ids", self.memory_ids)):
            if value is not ABSENT:
                out[key] = value
        out.update(self.extra)
        out["fingerprint"] = self.fingerprint
        return out

    def merge(self, other: "Finding") -> None:
        """Fold a duplicate in: union the personas each named and the hunks cited, losing neither.

        The score is reconciled to the higher of the two rather than to whichever lens was dispatched
        first: candidate order must not decide whether the run clears the floor gate, and the
        strongest evidence any lens produced is the one a reader can act on. `confidence_from` is
        dropped with it, because a raise no single read produced is not a recorded raise.

        `excerpt`, `comment`, and `suggestion` keep the first value either lens supplied: whichever
        arrives first may be the one that quotes the lines, words the comment, or supplies the
        replacement code, and candidate order must not decide which reaches `comments.md`.
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
        scores = [score for score in (self.confidence, other.confidence)
                  if isinstance(score, int) and not isinstance(score, bool)]
        if scores and max(scores) != self.confidence:
            self.confidence = max(scores)
            self.confidence_from = ABSENT
        for name in ("excerpt", "comment", "suggestion"):
            if getattr(self, name) is ABSENT and getattr(other, name) is not ABSENT:
                setattr(self, name, getattr(other, name))


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


def kind_value(finding: dict, index: int) -> object:
    """The `kind` written, normalized. A typo is refused here; absence is left to `require_kind`."""
    if "kind" not in finding:
        return ABSENT
    kind = str(finding["kind"]).strip().lower()
    if kind not in KINDS:
        raise ValueError(
            f"finding {index} has invalid kind: {finding['kind']!r} "
            f"(expected one of {', '.join(sorted(KINDS))})"
        )
    return kind


def confidence_value_in(finding: dict, index: int) -> object:
    """The score a caller wrote, with absence left to `require_confidence` for the same reason."""
    if "confidence" not in finding:
        return ABSENT
    try:
        return confidence_value(finding["confidence"])
    except ValueError as error:
        raise ValueError(f"finding {index} {error}") from None


def confidence_from_in(finding: dict, index: int) -> object:
    """The score this finding carried before a raise, which is how a raise is told from a guess."""
    if "confidence_from" not in finding:
        return ABSENT
    try:
        return confidence_value(finding["confidence_from"])
    except ValueError as error:
        raise ValueError(f"finding {index} {error} (confidence_from)") from None


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
    kind = kind_value(finding, index)
    confidence = confidence_value_in(finding, index)
    confidence_from = confidence_from_in(finding, index)
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
    known = {"title", "label", "file", "line", "kind", "confidence", "confidence_from",
             "disposition", "persona", "personas", "hunks", "verified", "evidence", "validation",
             "excerpt", "comment", "suggestion", "reason", "memory_ids", "fingerprint"}
    record = Finding(
        title=finding["title"], label=label, kind=kind, confidence=confidence,
        confidence_from=confidence_from, persona=persona,
        file=finding.get("file", ABSENT), line=finding.get("line", ABSENT),
        disposition=finding.get("disposition", ABSENT), hunks=finding.get("hunks", ABSENT),
        verified=finding.get("verified", ABSENT), evidence=finding.get("evidence", ABSENT),
        validation=finding.get("validation", ABSENT), excerpt=finding.get("excerpt", ABSENT),
        comment=finding.get("comment", ABSENT), suggestion=finding.get("suggestion", ABSENT),
        reason=finding.get("reason", ABSENT), memory_ids=finding.get("memory_ids", ABSENT),
        extra={key: value for key, value in finding.items() if key not in known},
    )
    record.fingerprint = fingerprint(record)
    return record


